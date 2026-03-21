from __future__ import annotations

import asyncio
import base64
import contextlib
import contextvars
import json
import logging
import re
from dataclasses import dataclass
from time import perf_counter
from urllib.parse import urlencode
from typing import Any, AsyncIterator, Callable
import weakref

import httpx
import websockets

logger = logging.getLogger(__name__)


@dataclass
class SttTranscript:
    text: str
    confidence: float
    is_final: bool
    source: str


class BaseSttClient:
    provider_name = "base"

    async def start_session(self, session_id: str, payload: dict | None = None) -> None:
        del payload
        return None

    async def end_session(self, session_id: str) -> None:
        return None

    async def finalize_utterance(self, payload: dict) -> SttTranscript:
        raise NotImplementedError

    async def trigger_finalization(self) -> None:
        return None


class BaseLlmClient:
    provider_name = "base"

    async def warm_session(self, session_id: str) -> None:
        del session_id
        return None

    async def stream_reply(self, *, rep_text: str, stage: str, system_prompt: str, max_tokens: int = 80) -> AsyncIterator[str]:
        raise NotImplementedError


class BaseTtsClient:
    provider_name = "base"

    async def warm_session(self, session_id: str) -> None:
        del session_id
        return None

    async def stream_audio(self, text: str) -> AsyncIterator[dict]:
        raise NotImplementedError


@dataclass
class JsonLlmAttempt:
    provider: str
    model: str
    outcome: str
    latency_ms: int
    real_call: bool
    task: str | None = None
    error: str | None = None


@dataclass
class JsonLlmResult:
    payload: Any
    provider: str
    model: str
    real_call: bool
    latency_ms: int
    fallback_used: bool
    attempts: list[JsonLlmAttempt]
    status: str


class JsonLlmRouterError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        retryable: bool = True,
        attempts: list[JsonLlmAttempt] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.attempts = list(attempts or [])


def _extract_json_block(raw_text: str) -> Any:
    text = raw_text.strip()
    if not text:
        raise ValueError("empty_response")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    for opening, closing in (("{", "}"), ("[", "]")):
        start = text.find(opening)
        end = text.rfind(closing)
        if start == -1 or end == -1 or end <= start:
            continue
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    raise ValueError("invalid_json")


def _extract_openai_text_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    content = message.get("content") if isinstance(message, dict) else ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts).strip()
    return ""


def _extract_anthropic_text_content(payload: dict[str, Any]) -> str:
    content = payload.get("content", [])
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts).strip()


class MockJsonLlmClient:
    provider_name = "mock"
    model_name = "mock-json"

    def complete_json(self, *, system_prompt: str, user_prompt: str, max_tokens: int) -> Any:
        del system_prompt, max_tokens
        prompt = user_prompt

        if '"intent": one of [' in prompt:
            return {
                "intent": "general",
                "rep_name_mentioned": None,
                "scenario_mentioned": None,
                "category_mentioned": None,
            }

        if '"key_metric_label"' in prompt and '"data_points"' in prompt:
            return {
                "answer": "The team is stable overall, with the clearest coaching opportunity still centered on objection handling.",
                "key_metric": "6.8",
                "key_metric_label": "Team Average Score",
                "follow_up_suggestions": [
                    "Who is most at risk this week?",
                    "Which scenario is dragging the team average down?",
                ],
                "action_suggestion": "Open the coaching view and review the lowest objection-handling cluster.",
                "data_points": [{"label": "At Risk", "value": "2 reps"}],
            }

        if '"headline"' in prompt and '"coaching_script"' in prompt:
            return {
                "headline": "Price objections still break momentum",
                "primary_weakness": "Objection Handling",
                "root_cause": "The rep is acknowledging the objection but not pivoting fast enough into value. That leaves the homeowner in control of the frame.",
                "drill_recommendation": "Assign a skeptical homeowner objection scenario at medium difficulty.",
                "coaching_script": "You are earning attention, but you are letting the price objection slow the conversation down. Acknowledge it once, then move straight into why the service is different. Practice the bridge until it sounds automatic.",
                "expected_improvement": "Objection handling should improve within the next 3 to 5 sessions.",
            }

        if '"discussion_topics"' in prompt and '"readiness_summary"' in prompt:
            return {
                "discussion_topics": [
                    {
                        "topic": "Objection handling is still the biggest drag",
                        "evidence": "Objection handling is the lowest category across the recent session sample.",
                        "suggested_opener": "I want to start with the pattern that is costing you the most right now: objection handling.",
                    },
                    {
                        "topic": "The opener is buying time",
                        "evidence": "Opening scores are holding up better than the rest of the scorecard.",
                        "suggested_opener": "You are buying yourself enough time at the door, which is a real strength to keep.",
                    },
                    {
                        "topic": "The next scenario should stress the same weakness",
                        "evidence": "The adaptive plan is still pointing at objection work before difficulty increases.",
                        "suggested_opener": "The next rep block should stay focused on objection reps until that pattern improves.",
                    },
                ],
                "strength_to_acknowledge": {
                    "skill": "Opening",
                    "what_to_say": "You are consistently earning the first few seconds. Keep that same calm, direct opener.",
                },
                "pattern_to_challenge": {
                    "skill": "Objection Handling",
                    "pattern": "The rep acknowledges pushback but does not convert it into a tighter value pivot.",
                    "what_to_say": "When the objection shows up, do not defend everything at once. Acknowledge it, narrow the issue, then re-close.",
                },
                "suggested_next_scenario": {
                    "scenario_type": "Skeptical homeowner objection drill",
                    "difficulty": 3,
                    "rationale": "The rep still needs more repetitions under objection pressure before moving up in difficulty.",
                },
                "readiness_summary": "The rep is coachable and stable, but objection handling is still the gate to the next level.",
            }

        if '"team_pulse"' in prompt and '"manager_action_items"' in prompt:
            return {
                "team_pulse": "The team is moving, but objection handling is still the shared drag on scores. The strongest reps are separating themselves by getting back to a clear next step faster.",
                "standout_rep": {"name": "Top Rep", "why": "Top Rep posted the highest average score and strongest recent trend."},
                "needs_attention": [
                    {"name": "Rep One", "concern": "Recent scores are slipping and objection handling remains weak."},
                    {"name": "Rep Two", "concern": "Activity is inconsistent and closes are still stalling."},
                ],
                "shared_weakness": {"skill": "Objection Handling", "team_average": 5.8, "note": "The team still gives up too much control once a homeowner pushes back."},
                "huddle_topic": {
                    "topic": "Acknowledge, narrow, then re-close",
                    "suggested_talking_points": [
                        "Teach one bridge for the first objection.",
                        "Separate price from value before defending service.",
                        "Re-close immediately after the answer.",
                    ],
                },
                "manager_action_items": [
                    "Run one objection-handling block with the full team.",
                    "Assign a retry scenario to the two reps slipping most.",
                ],
            }

        if "Return JSON array:" in prompt and '"turn_id"' in prompt:
            turn_ids = [match for match in re.findall(r"TURN_ID ([^\]\s]+)", prompt)]
            first_turn = turn_ids[0] if turn_ids else "turn-1"
            second_turn = turn_ids[1] if len(turn_ids) > 1 else first_turn
            return [
                {
                    "turn_id": first_turn,
                    "type": "strength",
                    "label": "Strong opener",
                    "explanation": "The rep opened with a clear reason for the conversation. That kept the interaction moving.",
                    "coaching_tip": None,
                },
                {
                    "turn_id": second_turn,
                    "type": "weakness",
                    "label": "Soft objection pivot",
                    "explanation": "The rep acknowledged the objection but did not redirect quickly enough. That let resistance stay in control.",
                    "coaching_tip": "Acknowledge briefly, ask one narrowing question, then move back to the next step.",
                },
            ]

        if '"summary": "Exactly 3 sentences.' in prompt or '"summary": "Exactly 3 sentences' in prompt:
            return {
                "summary": "Objection handling is still the biggest coaching opportunity across the team. Your strongest intervention pattern is visible, specific coaching tied to a follow-up retry. Tighten calibration on overrides this week while keeping the retry loop focused on the same weakness.",
            }

        if 'Provided company training material:' in prompt and '"answer"' in prompt:
            return {
                "answer": "The material says to confirm the concern, identify what feels weak in the current service, and compare the gap before talking about price.",
            }

        return {"answer": "No mock JSON response was defined for this prompt."}


class JsonLlmRouter:
    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self._mock = MockJsonLlmClient()

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        fast: bool = False,
        task: str = "manager_ai",
        validator: Callable[[Any], Any] | None = None,
        allow_mock_fallback: bool | None = None,
    ) -> JsonLlmResult:
        primary_provider = self._normalize_provider(self.settings.llm_provider)
        fallback_provider = self._resolve_fallback_provider(primary_provider)
        providers: list[str] = []
        for provider in [primary_provider, fallback_provider]:
            if provider and provider not in providers:
                providers.append(provider)
        if not providers:
            providers.append("mock")

        attempts: list[JsonLlmAttempt] = []
        last_error: JsonLlmRouterError | None = None
        success_index = 0

        for index, provider in enumerate(providers):
            model = self._resolve_model(provider, fast=fast, is_fallback=index > 0)
            payload, attempt, retryable, error = self._attempt_provider(
                provider=provider,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                task=task,
                validator=validator,
            )
            attempts.append(attempt)
            if error is None:
                success_index = index
                status = "mock" if provider == "mock" else ("fallback" if index > 0 else "live")
                return JsonLlmResult(
                    payload=payload,
                    provider=provider,
                    model=model,
                    real_call=attempt.real_call,
                    latency_ms=sum(item.latency_ms for item in attempts),
                    fallback_used=index > 0 and provider != "mock",
                    attempts=attempts,
                    status=status,
                )
            last_error = error
            if not retryable:
                break

        should_allow_mock = self._should_allow_mock_fallback() if allow_mock_fallback is None else bool(allow_mock_fallback)
        if should_allow_mock and "mock" not in providers:
            payload, attempt, _, error = self._attempt_provider(
                provider="mock",
                model=self._resolve_model("mock", fast=fast, is_fallback=True),
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                task=task,
                validator=validator,
            )
            attempts.append(attempt)
            if error is None:
                return JsonLlmResult(
                    payload=payload,
                    provider="mock",
                    model=attempt.model,
                    real_call=False,
                    latency_ms=sum(item.latency_ms for item in attempts),
                    fallback_used=success_index > 0 or any(item.real_call for item in attempts[:-1]),
                    attempts=attempts,
                    status="mock",
                )
            last_error = error

        if last_error is None:
            last_error = JsonLlmRouterError(
                "AI analysis is not configured for this environment.",
                code="ai_not_configured",
                retryable=False,
                attempts=attempts,
            )
        raise JsonLlmRouterError(str(last_error), code=last_error.code, retryable=last_error.retryable, attempts=attempts)

    def _attempt_provider(
        self,
        *,
        provider: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        task: str,
        validator: Callable[[Any], Any] | None,
    ) -> tuple[Any | None, JsonLlmAttempt, bool, JsonLlmRouterError | None]:
        if provider == "mock":
            started = perf_counter()
            payload = self._mock.complete_json(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=max_tokens)
            latency_ms = max(1, int((perf_counter() - started) * 1000))
            attempt = JsonLlmAttempt(
                provider="mock",
                model=self._mock.model_name,
                outcome="mock_success",
                latency_ms=latency_ms,
                real_call=False,
                task=task,
            )
            try:
                validated = validator(payload) if validator else payload
            except Exception as exc:
                attempt.outcome = "invalid_schema"
                attempt.error = str(exc)[:240]
                return None, attempt, False, JsonLlmRouterError(
                    "Mock AI returned an invalid response payload.",
                    code="ai_invalid_response",
                    retryable=False,
                    attempts=[attempt],
                )
            return validated, attempt, False, None

        api_key = self._provider_api_key(provider)
        if not api_key:
            attempt = JsonLlmAttempt(
                provider=provider,
                model=model,
                outcome="skipped_no_key",
                latency_ms=0,
                real_call=False,
                task=task,
                error="provider_api_key_missing",
            )
            error = JsonLlmRouterError(
                f"{provider.title()} is not configured for manager AI.",
                code="ai_not_configured",
                retryable=True,
                attempts=[attempt],
            )
            return None, attempt, True, error

        started = perf_counter()
        try:
            raw_payload = (
                self._call_openai_json(
                    api_key=api_key,
                    model=model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_tokens,
                )
                if provider == "openai"
                else self._call_anthropic_json(
                    api_key=api_key,
                    model=model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_tokens,
                )
            )
            latency_ms = max(1, int((perf_counter() - started) * 1000))
            attempt = JsonLlmAttempt(
                provider=provider,
                model=model,
                outcome="success",
                latency_ms=latency_ms,
                real_call=True,
                task=task,
            )
            try:
                validated = validator(raw_payload) if validator else raw_payload
            except Exception as exc:
                attempt.outcome = "ai_invalid_response"
                attempt.error = str(exc)[:240]
                error = JsonLlmRouterError(
                    f"{provider.title()} returned an invalid response payload.",
                    code="ai_invalid_response",
                    retryable=True,
                    attempts=[attempt],
                )
                return None, attempt, True, error
            return validated, attempt, False, None
        except JsonLlmRouterError as exc:
            latency_ms = max(1, int((perf_counter() - started) * 1000))
            attempt = JsonLlmAttempt(
                provider=provider,
                model=model,
                outcome=exc.code,
                latency_ms=latency_ms,
                real_call=True,
                task=task,
                error=str(exc)[:240],
            )
            return None, attempt, exc.retryable, JsonLlmRouterError(
                str(exc),
                code=exc.code,
                retryable=exc.retryable,
                attempts=[attempt],
            )
        except Exception as exc:
            latency_ms = max(1, int((perf_counter() - started) * 1000))
            attempt = JsonLlmAttempt(
                provider=provider,
                model=model,
                outcome="ai_provider_unavailable",
                latency_ms=latency_ms,
                real_call=True,
                task=task,
                error=str(exc)[:240],
            )
            error = JsonLlmRouterError(
                f"{provider.title()} is temporarily unavailable.",
                code="ai_provider_unavailable",
                retryable=True,
                attempts=[attempt],
            )
            return None, attempt, True, error

    def _call_openai_json(
        self,
        *,
        api_key: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> Any:
        with httpx.Client(timeout=self.settings.provider_timeout_seconds) as client:
            try:
                response = client.post(
                    f"{self.settings.openai_base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "temperature": 0.2,
                        "max_tokens": max_tokens,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                    },
                )
            except httpx.TimeoutException as exc:
                raise JsonLlmRouterError("OpenAI timed out during manager AI generation.", code="ai_timeout", retryable=True) from exc
            except httpx.TransportError as exc:
                raise JsonLlmRouterError("OpenAI is temporarily unreachable.", code="ai_provider_unavailable", retryable=True) from exc

        if response.status_code == 429:
            raise JsonLlmRouterError("OpenAI rate limited the request.", code="ai_provider_unavailable", retryable=True)
        if response.status_code >= 500:
            raise JsonLlmRouterError("OpenAI returned a server error.", code="ai_provider_unavailable", retryable=True)
        if response.status_code >= 400:
            raise JsonLlmRouterError("OpenAI rejected the manager AI request.", code="ai_invalid_response", retryable=False)

        text_content = _extract_openai_text_content(response.json())
        try:
            return _extract_json_block(text_content)
        except ValueError as exc:
            raise JsonLlmRouterError("OpenAI returned an invalid JSON payload.", code="ai_invalid_response", retryable=True) from exc

    def _call_anthropic_json(
        self,
        *,
        api_key: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> Any:
        with httpx.Client(timeout=self.settings.provider_timeout_seconds) as client:
            try:
                response = client.post(
                    f"{self.settings.anthropic_base_url.rstrip('/')}/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model,
                        "max_tokens": max_tokens,
                        "temperature": 0.2,
                        "system": system_prompt,
                        "messages": [{"role": "user", "content": user_prompt}],
                    },
                )
            except httpx.TimeoutException as exc:
                raise JsonLlmRouterError("Anthropic timed out during manager AI generation.", code="ai_timeout", retryable=True) from exc
            except httpx.TransportError as exc:
                raise JsonLlmRouterError("Anthropic is temporarily unreachable.", code="ai_provider_unavailable", retryable=True) from exc

        if response.status_code == 429:
            raise JsonLlmRouterError("Anthropic rate limited the request.", code="ai_provider_unavailable", retryable=True)
        if response.status_code >= 500:
            raise JsonLlmRouterError("Anthropic returned a server error.", code="ai_provider_unavailable", retryable=True)
        if response.status_code >= 400:
            raise JsonLlmRouterError("Anthropic rejected the manager AI request.", code="ai_invalid_response", retryable=False)

        text_content = _extract_anthropic_text_content(response.json())
        try:
            return _extract_json_block(text_content)
        except ValueError as exc:
            raise JsonLlmRouterError("Anthropic returned an invalid JSON payload.", code="ai_invalid_response", retryable=True) from exc

    def _resolve_fallback_provider(self, primary_provider: str) -> str | None:
        configured = self._normalize_provider(self.settings.manager_ai_fallback_provider)
        if configured:
            return configured
        if primary_provider == "openai" and self.settings.anthropic_api_key:
            return "anthropic"
        if primary_provider == "anthropic" and self.settings.openai_api_key:
            return "openai"
        if primary_provider == "mock":
            if self.settings.openai_api_key:
                return "openai"
            if self.settings.anthropic_api_key:
                return "anthropic"
        return None

    def _resolve_model(self, provider: str, *, fast: bool, is_fallback: bool) -> str:
        if provider == "mock":
            return self._mock.model_name
        if is_fallback:
            explicit = (
                self.settings.manager_ai_fallback_fast_model
                if fast and self.settings.manager_ai_fallback_fast_model
                else self.settings.manager_ai_fallback_model
            )
            if explicit:
                return explicit
        explicit = self.settings.manager_ai_fast_model if fast and self.settings.manager_ai_fast_model else self.settings.manager_ai_model
        if explicit:
            return explicit
        if provider == "anthropic":
            return self.settings.anthropic_chat_classification_model if fast else self.settings.anthropic_chat_answer_model
        return self.settings.openai_model

    def _provider_api_key(self, provider: str) -> str | None:
        if provider == "openai":
            return self.settings.openai_api_key
        if provider == "anthropic":
            return self.settings.anthropic_api_key
        return None

    def _normalize_provider(self, provider: str | None) -> str:
        normalized = (provider or "").strip().lower()
        if normalized in {"openai", "anthropic", "mock"}:
            return normalized
        return ""

    def _should_allow_mock_fallback(self) -> bool:
        environment = (getattr(self.settings, "environment", "") or "").strip().lower()
        return environment in {"", "dev", "development", "local", "test"}


async def _iter_sse_json_payloads(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    async for line in response.aiter_lines():
        if not line:
            continue
        line = line.strip()
        if not line or line.startswith(":") or not line.startswith("data:"):
            continue
        raw = line.removeprefix("data:").strip()
        if raw == "[DONE]":
            break
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            yield parsed


def _decode_base64_audio(payload: dict) -> bytes | None:
    audio_b64 = payload.get("audio_base64")
    if not audio_b64:
        return None
    if isinstance(audio_b64, str) and "," in audio_b64 and audio_b64.startswith("data:"):
        audio_b64 = audio_b64.split(",", 1)[1]
    try:
        return base64.b64decode(audio_b64)
    except Exception:
        return None


def _emit_handler(payload: dict, key: str, transcript: str, is_final: bool) -> None:
    handler = payload.get(key)
    if callable(handler):
        try:
            handler(transcript, is_final)
        except Exception:
            return


class _TaskConversationHistoryMixin:
    def __init__(self) -> None:
        # Keyed by session_id so history survives WebSocket reconnects.
        self._history_by_session: dict[str, list[dict[str, str]]] = {}
        self._active_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
            "llm_active_session_id", default=None
        )

    def set_session(self, session_id: str) -> None:
        """Call once when a WebSocket session binds to this LLM client."""
        self._active_session_id.set(session_id)
        if session_id not in self._history_by_session:
            self._history_by_session[session_id] = []

    def clear_session(self, session_id: str) -> None:
        """Call when a session ends to free memory."""
        self._history_by_session.pop(session_id, None)

    def _history_for_current_task(self) -> list[dict[str, str]]:
        session_id = self._active_session_id.get()
        if not session_id:
            # Fallback: no session context, return empty (won't be stored)
            return []
        if session_id not in self._history_by_session:
            self._history_by_session[session_id] = []
        return self._history_by_session[session_id]

    def _remember_exchange(self, *, user_text: str, assistant_text: str) -> None:
        history = self._history_for_current_task()
        history.extend(
            [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": assistant_text},
            ]
        )
        # Keep the last 16 messages (8 exchanges) to bound context size.
        if len(history) > 16:
            del history[:-16]


class MockSttClient(BaseSttClient):
    provider_name = "mock_stt"

    async def finalize_utterance(self, payload: dict) -> SttTranscript:
        hint = str(payload.get("transcript_hint", "")).strip()
        return SttTranscript(text=hint, confidence=0.98 if hint else 0.0, is_final=bool(hint), source=self.provider_name)


@dataclass
class _DeepgramSessionState:
    ws: Any
    lock: asyncio.Lock
    keepalive_task: asyncio.Task[Any]
    listen_url: str


class DeepgramSttClient(BaseSttClient):
    provider_name = "deepgram"
    KEEPALIVE_INTERVAL_SECONDS = 10.0

    def __init__(self, api_key: str | None, base_url: str, model: str, timeout_seconds: float) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._fallback = MockSttClient()
        self._sessions: dict[str, _DeepgramSessionState] = {}
        self._session_ids: set[str] = set()
        self._active_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
            "deepgram_active_session_id",
            default=None,
        )

    async def finalize_utterance(self, payload: dict) -> SttTranscript:
        hint = str(payload.get("transcript_hint", "")).strip()
        if not self.api_key:
            return await self._fallback.finalize_utterance(payload)

        audio_bytes = _decode_base64_audio(payload)
        if not audio_bytes:
            if hint:
                return SttTranscript(text=hint, confidence=0.98, is_final=True, source=self.provider_name)
            return await self._fallback.finalize_utterance(payload)

        try:
            return await self._stream_utterance(payload, audio_bytes, hint)
        except Exception:
            if hint:
                return SttTranscript(text=hint, confidence=0.98, is_final=True, source=self.provider_name)
            return await self._fallback.finalize_utterance(payload)

    async def start_session(self, session_id: str, payload: dict | None = None) -> None:
        if not self.api_key:
            return
        self._session_ids.add(session_id)
        self._active_session_id.set(session_id)
        # Pre-warm the Deepgram WebSocket so the first utterance doesn't pay
        # the WebSocket handshake cost (~150 ms).  Use the default WAV/linear16
        # params that the mobile client always sends.
        default_payload = payload or {
            "codec": "linear16",
            "content_type": "audio/wav",
            "sample_rate": 16000,
            "channels": 1,
            "session_id": session_id,
        }
        with contextlib.suppress(Exception):
            await self._get_or_open_session(session_id, payload=default_payload)

    async def end_session(self, session_id: str) -> None:
        self._session_ids.discard(session_id)
        if self._active_session_id.get() == session_id:
            self._active_session_id.set(None)
        state = self._sessions.pop(session_id, None)
        if state is None:
            return
        state.keepalive_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await state.keepalive_task
        with contextlib.suppress(Exception):
            await state.ws.send(json.dumps({"type": "CloseStream"}))
        with contextlib.suppress(Exception):
            await state.ws.close()

    async def trigger_finalization(self) -> None:
        session_id = self._active_session_id.get()
        if not self.api_key or not session_id:
            return
        state = self._sessions.get(session_id)
        if state is None or getattr(state.ws, "closed", False):
            return
        try:
            async with state.lock:
                await state.ws.send(json.dumps({"type": "Finalize"}))
        except Exception:
            return

    def _normalized_audio_params(self, payload: dict) -> tuple[str, str, int, int]:
        content_type = str(payload.get("content_type") or "").lower().strip()
        codec = str(payload.get("codec") or "").lower().strip()
        if content_type in {"audio/ogg", "audio/opus"} and not codec:
            codec = "opus"
        if content_type in {"audio/wav", "audio/x-wav"} and codec in {"wav", ""}:
            codec = "linear16"
        sample_rate = int(payload.get("sample_rate") or 16000)
        channels = int(payload.get("channels") or 1)
        if sample_rate <= 0:
            sample_rate = 16000
        if channels <= 0:
            channels = 1
        return content_type, codec, sample_rate, channels

    def _listen_url(self, payload: dict) -> str:
        content_type, codec, sample_rate, channels = self._normalized_audio_params(payload)
        ws_base = self.base_url.replace("https://", "wss://").replace("http://", "ws://")
        params: dict[str, str | list[str]] = {
            "model": self.model,
            "smart_format": "true",
            "punctuate": "true",
            "interim_results": "true",
            "endpointing": str(int(payload.get("endpointing_ms") or 300)),
            "utterance_end_ms": str(int(payload.get("utterance_end_ms") or 1200)),
            "language": "en-US",
            "no_delay": "true",
            "disfluencies": "false",
        }
        vocabulary_hints = [
            " ".join(str(term or "").split()).strip()
            for term in (payload.get("vocabulary_hints") or [])
            if " ".join(str(term or "").split()).strip()
        ]
        if vocabulary_hints:
            # Deepgram nova-3 expects repeated `keyterm` query params, not a comma-joined `keywords` param.
            params["keyterm"] = vocabulary_hints[:100]
        if codec == "opus" or "opus" in content_type:
            params["encoding"] = "opus"
            params["sample_rate"] = str(sample_rate)
        elif content_type in ("audio/mp4", "audio/webm", "audio/mpeg"):
            params["mimetype"] = content_type
        else:
            params["encoding"] = "linear16"
            params["sample_rate"] = str(sample_rate)
            params["channels"] = str(channels)
        return f"{ws_base}/v1/listen?{urlencode(params, doseq=True)}"

    async def _open_session(self, session_id: str, payload: dict) -> _DeepgramSessionState:
        listen_url = self._listen_url(payload)
        ws = await websockets.connect(
            listen_url,
            additional_headers={"Authorization": f"Token {self.api_key}"},
            open_timeout=self.timeout_seconds,
            close_timeout=self.timeout_seconds,
            max_size=4_000_000,
        )
        state = _DeepgramSessionState(
            ws=ws,
            lock=asyncio.Lock(),
            keepalive_task=asyncio.create_task(asyncio.sleep(0)),
            listen_url=listen_url,
        )

        async def keepalive_loop() -> None:
            while True:
                await asyncio.sleep(self.KEEPALIVE_INTERVAL_SECONDS)
                try:
                    async with state.lock:
                        await state.ws.send(json.dumps({"type": "KeepAlive"}))
                except asyncio.CancelledError:
                    raise
                except Exception:
                    break

        state.keepalive_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await state.keepalive_task
        state.keepalive_task = asyncio.create_task(keepalive_loop())
        self._sessions[session_id] = state
        return state

    async def _get_or_open_session(self, session_id: str, *, payload: dict, force_reconnect: bool = False) -> _DeepgramSessionState:
        state = self._sessions.get(session_id)
        desired_listen_url = self._listen_url(payload)
        if state is not None and (force_reconnect or state.listen_url != desired_listen_url):
            await self.end_session(session_id)
            state = None
        if state is not None:
            return state
        return await self._open_session(session_id, payload)

    async def _stream_utterance(self, payload: dict, audio_bytes: bytes, hint: str) -> SttTranscript:
        session_id = str(payload.get("session_id") or "")
        if not session_id:
            raise RuntimeError("deepgram session_id required")
        MAX_RETRIES = 2
        retry_count = 0
        reopened_state: _DeepgramSessionState | None = None

        while True:
            latest_partial = ""
            final_segments: list[str] = []
            confidences: list[float] = []
            finalize_sent = asyncio.Event()
            state = reopened_state or await self._get_or_open_session(session_id, payload=payload)
            reopened_state = None

            if getattr(state.ws, "closed", False):
                await self.end_session(session_id)
                if retry_count >= MAX_RETRIES:
                    raise RuntimeError("deepgram_connection_closed")
                retry_count += 1
                await asyncio.sleep(min(0.5 * retry_count, 1.0))
                reopened_state = await self._open_session(session_id, payload)
                continue

            async def consume_results() -> None:
                nonlocal latest_partial, final_segments, confidences
                while True:
                    recv_timeout = 0.2 if (finalize_sent.is_set() and final_segments) else self.timeout_seconds
                    try:
                        raw_message = await asyncio.wait_for(state.ws.recv(), timeout=recv_timeout)
                    except TimeoutError:
                        break

                    if isinstance(raw_message, bytes):
                        continue

                    try:
                        message = json.loads(raw_message)
                    except json.JSONDecodeError:
                        continue

                    message_type = str(message.get("type", ""))
                    if message_type == "Results":
                        channel = (message.get("channel") or {}).get("alternatives") or []
                        alternative = channel[0] if channel else {}
                        transcript = str(alternative.get("transcript", "")).strip()
                        # is_final: this time-window is finalized (more windows may follow)
                        # speech_final: Deepgram VAD detected end of speech — stop here
                        is_final_window = bool(message.get("is_final"))
                        speech_final = bool(message.get("speech_final"))
                        if not transcript:
                            # Empty window: only stop if speech is truly finished
                            if speech_final:
                                break
                            continue

                        confidence = float(alternative.get("confidence", 0.0) or 0.0)
                        if is_final_window or speech_final:
                            # Accumulate every finalized window — long utterances span multiple windows
                            final_segments.append(transcript)
                            confidences.append(confidence)
                            _emit_handler(payload, "on_final", transcript, True)
                            if speech_final:
                                # Speaker has stopped — we have the full utterance
                                break
                            # Otherwise keep consuming: more windows may still arrive
                        else:
                            latest_partial = transcript
                            _emit_handler(payload, "on_partial", transcript, False)
                        continue

                    if message_type == "UtteranceEnd":
                        break
                    if message_type == "Error":
                        raise RuntimeError(str(message.get("description") or "deepgram_error"))

            try:
                # Hold the lock only during the send phase so that
                # trigger_finalization() isn't blocked while Deepgram processes.
                async with state.lock:
                    for idx in range(0, len(audio_bytes), 8192):
                        await state.ws.send(audio_bytes[idx : idx + 8192])
                        await asyncio.sleep(0)
                    await state.ws.send(json.dumps({"type": "Finalize"}))
                    finalize_sent.set()
                # Consume results outside the lock — recv() does not conflict
                # with concurrent sends on a different asyncio task.
                await consume_results()
            except websockets.ConnectionClosed as exc:
                await self.end_session(session_id)
                if retry_count >= MAX_RETRIES:
                    raise RuntimeError("deepgram_connection_closed") from exc
                retry_count += 1
                await asyncio.sleep(min(0.5 * retry_count, 1.0))
                reopened_state = await self._open_session(session_id, payload)
                continue
            except Exception:
                await self.end_session(session_id)
                raise

            transcript = " ".join(final_segments).strip() or latest_partial or hint
            confidence = sum(confidences) / len(confidences) if confidences else (0.98 if transcript == hint and transcript else 0.0)
            logger.info(
                "deepgram_utterance_result",
                extra={
                    "session_id": session_id,
                    "final_segment_count": len(final_segments),
                    "transcript": transcript or "(empty)",
                    "confidence": confidence,
                    "finalize_sent": finalize_sent.is_set(),
                    "audio_bytes": len(audio_bytes),
                },
            )
            return SttTranscript(
                text=transcript,
                confidence=confidence,
                is_final=bool(final_segments) or bool(transcript),
                source=self.provider_name,
            )


class MockLlmClient(BaseLlmClient):
    provider_name = "mock_llm"

    async def stream_reply(self, *, rep_text: str, stage: str, system_prompt: str, max_tokens: int = 80) -> AsyncIterator[str]:
        starter = "I hear you. "
        if "price" in rep_text.lower():
            body = "That sounds expensive for us right now."
        elif "spouse" in rep_text.lower() or "partner" in rep_text.lower():
            body = "I need to discuss this with my spouse before deciding."
        elif "already" in rep_text.lower() or "provider" in rep_text.lower():
            body = "We already have someone handling this. Why switch?"
        elif stage == "close_attempt":
            body = "What would the next step look like if we did this today?"
        else:
            body = "Can you explain how this helps my home specifically?"
        for token in [starter, body]:
            await asyncio.sleep(0.01)
            yield token


class OpenAiLlmClient(_TaskConversationHistoryMixin, BaseLlmClient):
    provider_name = "openai"

    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str,
        timeout_seconds: float,
        *,
        temperature: float = 0.35,
    ) -> None:
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.temperature = float(temperature)
        self._fallback = MockLlmClient()

    async def warm_session(self, session_id: str) -> None:
        self.set_session(session_id)

    async def stream_reply(self, *, rep_text: str, stage: str, system_prompt: str, max_tokens: int = 80) -> AsyncIterator[str]:
        if not self.api_key:
            async for chunk in self._fallback.stream_reply(
                rep_text=rep_text,
                stage=stage,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
            ):
                yield chunk
            return

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "stream": True,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "stream_options": {"include_usage": True},
            "messages": [{"role": "system", "content": system_prompt}, *self._history_for_current_task(), {"role": "user", "content": rep_text}],
        }

        emitted = False
        emitted_parts: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for chunk in _iter_sse_json_payloads(response):
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {}) if isinstance(choices[0], dict) else {}
                        token = delta.get("content")
                        if isinstance(token, str) and token:
                            emitted = True
                            emitted_parts.append(token)
                            yield token
                            continue
                        if isinstance(token, list):
                            text_parts = [str(item.get("text", "")) for item in token if isinstance(item, dict)]
                            merged = "".join(text_parts).strip()
                            if merged:
                                emitted = True
                                emitted_parts.append(merged)
                                yield merged
        except Exception:
            emitted = False

        if emitted:
            self._remember_exchange(user_text=rep_text, assistant_text="".join(emitted_parts))

        if not emitted:
            async for chunk in self._fallback.stream_reply(
                rep_text=rep_text,
                stage=stage,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
            ):
                yield chunk


class AnthropicLlmClient(_TaskConversationHistoryMixin, BaseLlmClient):
    provider_name = "anthropic"

    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str,
        timeout_seconds: float,
        *,
        temperature: float = 0.35,
    ) -> None:
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.temperature = float(temperature)
        self._fallback = MockLlmClient()

    async def warm_session(self, session_id: str) -> None:
        self.set_session(session_id)

    async def stream_reply(self, *, rep_text: str, stage: str, system_prompt: str, max_tokens: int = 80) -> AsyncIterator[str]:
        if not self.api_key:
            async for chunk in self._fallback.stream_reply(
                rep_text=rep_text,
                stage=stage,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
            ):
                yield chunk
            return

        url = f"{self.base_url}/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "accept": "text/event-stream",
        }
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": self.temperature,
            "stream": True,
            "system": system_prompt,
            "messages": [*self._history_for_current_task(), {"role": "user", "content": rep_text}],
        }

        emitted = False
        emitted_parts: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for chunk in _iter_sse_json_payloads(response):
                        event_type = str(chunk.get("type", ""))
                        token = ""
                        if event_type == "content_block_delta":
                            delta = chunk.get("delta", {})
                            if isinstance(delta, dict) and delta.get("type") == "text_delta":
                                token = str(delta.get("text", ""))
                        elif event_type == "content_block_start":
                            content_block = chunk.get("content_block", {})
                            if isinstance(content_block, dict):
                                token = str(content_block.get("text", ""))

                        token = token.strip()
                        if token:
                            emitted = True
                            emitted_parts.append(token + " ")
                            yield token + " "
        except Exception:
            emitted = False

        if emitted:
            self._remember_exchange(user_text=rep_text, assistant_text="".join(emitted_parts).strip())

        if not emitted:
            async for chunk in self._fallback.stream_reply(
                rep_text=rep_text,
                stage=stage,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
            ):
                yield chunk


class MockTtsClient(BaseTtsClient):
    provider_name = "mock_tts"

    async def stream_audio(self, text: str) -> AsyncIterator[dict]:
        if not text:
            return
        await asyncio.sleep(0.005)
        yield {
            "codec": "pcm16",
            "payload": "UklGRiQAAABXQVZFZm10",
            "duration_ms": max(120, min(1200, len(text) * 18)),
            "provider": self.provider_name,
        }


class ElevenLabsTtsClient(BaseTtsClient):
    provider_name = "elevenlabs"

    def __init__(
        self,
        api_key: str | None,
        voice_id: str | None,
        model_id: str,
        base_url: str,
        timeout_seconds: float,
        *,
        voice_stability: float = 0.42,
        voice_similarity_boost: float = 0.82,
        streaming_latency_mode: int = 3,
    ) -> None:
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.voice_stability = float(voice_stability)
        self.voice_similarity_boost = float(voice_similarity_boost)
        self.streaming_latency_mode = int(streaming_latency_mode)
        self._fallback = MockTtsClient()

    async def stream_audio(self, text: str) -> AsyncIterator[dict]:
        if not text:
            return

        voice_id, cleaned_text = self._resolve_voice(text)

        if not self.api_key or not voice_id:
            async for chunk in self._fallback.stream_audio(cleaned_text):
                out = dict(chunk)
                out["provider"] = self.provider_name
                out["voice_id"] = voice_id
                yield out
            return

        url = f"{self.base_url}/v1/text-to-speech/{voice_id}/stream"
        headers = {
            "xi-api-key": self.api_key,
            "accept": "audio/mpeg",
            "content-type": "application/json",
        }
        payload = {
            "text": cleaned_text,
            "model_id": self.model_id,
            "optimize_streaming_latency": self.streaming_latency_mode,
            "voice_settings": {
                "stability": self.voice_stability,
                "similarity_boost": self.voice_similarity_boost,
            },
        }

        emitted = False
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for raw_chunk in response.aiter_bytes():
                        if not raw_chunk:
                            continue
                        emitted = True
                        duration_ms = max(40, int(len(raw_chunk) / 32))
                        yield {
                            "codec": "mp3",
                            "payload": base64.b64encode(raw_chunk).decode("utf-8"),
                            "duration_ms": duration_ms,
                            "provider": self.provider_name,
                            "voice_id": voice_id,
                        }
        except Exception:
            emitted = False

        if not emitted:
            async for chunk in self._fallback.stream_audio(cleaned_text):
                out = dict(chunk)
                out["provider"] = self.provider_name
                out["voice_id"] = voice_id
                yield out

    def _resolve_voice(self, text: str) -> tuple[str | None, str]:
        if text.startswith("[[voice:") and "]]" in text:
            directive, remainder = text.split("]]", 1)
            voice_id = directive.removeprefix("[[voice:").strip()
            return (voice_id or self.voice_id), remainder.lstrip()
        return self.voice_id, text


@dataclass
class ProviderSuite:
    stt: BaseSttClient
    llm: BaseLlmClient
    tts: BaseTtsClient

    @classmethod
    def from_settings(cls, settings) -> ProviderSuite:
        stt_provider = (settings.stt_provider or "mock").lower()
        llm_provider = (settings.llm_provider or "mock").lower()
        tts_provider = (settings.tts_provider or "mock").lower()

        stt = (
            DeepgramSttClient(
                settings.deepgram_api_key,
                base_url=settings.deepgram_base_url,
                model=settings.deepgram_model,
                timeout_seconds=settings.provider_timeout_seconds,
            )
            if stt_provider == "deepgram"
            else MockSttClient()
        )

        llm = (
            AnthropicLlmClient(
                settings.anthropic_api_key,
                model=settings.anthropic_model,
                base_url=settings.anthropic_base_url,
                timeout_seconds=settings.provider_timeout_seconds,
                temperature=settings.homeowner_llm_temperature,
            )
            if llm_provider == "anthropic"
            else (
                OpenAiLlmClient(
                    settings.openai_api_key,
                    model=settings.openai_model,
                    base_url=settings.openai_base_url,
                    timeout_seconds=settings.provider_timeout_seconds,
                    temperature=settings.homeowner_llm_temperature,
                )
                if llm_provider == "openai"
                else MockLlmClient()
            )
        )

        tts = (
            ElevenLabsTtsClient(
                settings.elevenlabs_api_key,
                settings.elevenlabs_voice_id,
                model_id=settings.elevenlabs_model_id,
                base_url=settings.elevenlabs_base_url,
                timeout_seconds=settings.provider_timeout_seconds,
                voice_stability=settings.elevenlabs_voice_stability,
                voice_similarity_boost=settings.elevenlabs_voice_similarity_boost,
                streaming_latency_mode=settings.elevenlabs_streaming_latency_mode,
            )
            if tts_provider == "elevenlabs"
            else MockTtsClient()
        )

        return cls(stt=stt, llm=llm, tts=tts)
