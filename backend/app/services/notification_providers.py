from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class ProviderSendResult:
    ok: bool
    status: str
    response: dict[str, Any]
    error: str | None = None


class EmailProvider:
    async def send(self, *, to_email: str, subject: str, body: str) -> ProviderSendResult:
        raise NotImplementedError


class PushProvider:
    async def send(self, *, push_token: str, title: str, body: str, data: dict[str, Any]) -> ProviderSendResult:
        raise NotImplementedError


class LogEmailProvider(EmailProvider):
    async def send(self, *, to_email: str, subject: str, body: str) -> ProviderSendResult:
        logger.info("email_notification_log", extra={"to_email": to_email, "subject": subject, "body": body})
        return ProviderSendResult(ok=True, status="sent", response={"provider": "log"})


class SendGridEmailProvider(EmailProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._fallback = LogEmailProvider()

    async def send(self, *, to_email: str, subject: str, body: str) -> ProviderSendResult:
        if not self.settings.sendgrid_api_key or not self.settings.sendgrid_from_email:
            return await self._fallback.send(to_email=to_email, subject=subject, body=body)

        payload = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": self.settings.sendgrid_from_email},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body}],
        }
        headers = {
            "Authorization": f"Bearer {self.settings.sendgrid_api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post("https://api.sendgrid.com/v3/mail/send", json=payload, headers=headers)
            if 200 <= response.status_code < 300:
                return ProviderSendResult(ok=True, status="sent", response={"provider": "sendgrid", "code": response.status_code})
            return ProviderSendResult(
                ok=False,
                status="failed",
                response={"provider": "sendgrid", "code": response.status_code, "body": response.text[:300]},
                error="sendgrid_non_2xx",
            )
        except Exception as exc:  # pragma: no cover - network/provider dependent
            return ProviderSendResult(
                ok=False,
                status="failed",
                response={"provider": "sendgrid"},
                error=f"sendgrid_exception:{exc}",
            )


class LogPushProvider(PushProvider):
    async def send(self, *, push_token: str, title: str, body: str, data: dict[str, Any]) -> ProviderSendResult:
        logger.info(
            "push_notification_log",
            extra={"push_token": push_token, "title": title, "body": body, "data": data},
        )
        return ProviderSendResult(ok=True, status="sent", response={"provider": "log"})


class ExpoPushProvider(PushProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._fallback = LogPushProvider()

    async def send(self, *, push_token: str, title: str, body: str, data: dict[str, Any]) -> ProviderSendResult:
        if not self.settings.expo_push_access_token:
            return await self._fallback.send(push_token=push_token, title=title, body=body, data=data)

        payload = {
            "to": push_token,
            "title": title,
            "body": body,
            "data": data,
            "priority": "high",
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.settings.expo_push_access_token}",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(self.settings.expo_push_base_url, json=payload, headers=headers)
            if 200 <= response.status_code < 300:
                parsed = response.json() if response.text else {}
                ticket_status = parsed.get("data", {}).get("status") if isinstance(parsed, dict) else None
                if ticket_status and ticket_status != "ok":
                    return ProviderSendResult(
                        ok=False,
                        status="failed",
                        response={"provider": "expo", "body": parsed},
                        error="expo_ticket_failed",
                    )
                return ProviderSendResult(ok=True, status="sent", response={"provider": "expo", "body": parsed})
            return ProviderSendResult(
                ok=False,
                status="failed",
                response={"provider": "expo", "code": response.status_code, "body": response.text[:300]},
                error="expo_non_2xx",
            )
        except Exception as exc:  # pragma: no cover - network/provider dependent
            return ProviderSendResult(
                ok=False,
                status="failed",
                response={"provider": "expo"},
                error=f"expo_exception:{exc}",
            )
