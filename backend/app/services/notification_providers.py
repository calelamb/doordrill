from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from email.message import EmailMessage
import smtplib
import ssl
from typing import Any

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


def _network_calls_disabled_for_tests() -> bool:
    return bool(os.getenv("PYTEST_CURRENT_TEST"))


@dataclass
class ProviderSendResult:
    ok: bool
    status: str
    response: dict[str, Any]
    error: str | None = None
    permanent_failure: bool = False
    invalid_token: bool = False


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
        if _network_calls_disabled_for_tests() or not self.settings.sendgrid_api_key or not self.settings.sendgrid_from_email:
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
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.post("https://api.sendgrid.com/v3/mail/send", json=payload, headers=headers)
            if 200 <= response.status_code < 300:
                return ProviderSendResult(
                    ok=True,
                    status="sent",
                    response={"provider": "sendgrid", "code": response.status_code},
                )
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


class SesEmailProvider(EmailProvider):
    """Amazon SES delivery via SMTP credentials."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._fallback = LogEmailProvider()

    async def send(self, *, to_email: str, subject: str, body: str) -> ProviderSendResult:
        if _network_calls_disabled_for_tests() or (
            not self.settings.ses_smtp_username
            or not self.settings.ses_smtp_password
            or not self.settings.ses_from_email
            or not self.settings.ses_smtp_host
        ):
            return await self._fallback.send(to_email=to_email, subject=subject, body=body)

        try:
            result = await asyncio.to_thread(self._send_sync, to_email=to_email, subject=subject, body=body)
            return ProviderSendResult(ok=True, status="sent", response={"provider": "ses", **result})
        except Exception as exc:  # pragma: no cover - network/provider dependent
            return ProviderSendResult(
                ok=False,
                status="failed",
                response={"provider": "ses"},
                error=f"ses_exception:{exc}",
            )

    def _send_sync(self, *, to_email: str, subject: str, body: str) -> dict[str, Any]:
        message = EmailMessage()
        message["From"] = self.settings.ses_from_email
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)

        context = ssl.create_default_context()
        with smtplib.SMTP(self.settings.ses_smtp_host, int(self.settings.ses_smtp_port), timeout=10) as server:
            server.starttls(context=context)
            server.login(self.settings.ses_smtp_username, self.settings.ses_smtp_password)
            failed = server.send_message(message)

        if failed:
            raise RuntimeError(f"ses_rejected_recipients:{failed}")

        return {
            "smtp_host": self.settings.ses_smtp_host,
            "smtp_port": int(self.settings.ses_smtp_port),
        }


class LogPushProvider(PushProvider):
    async def send(self, *, push_token: str, title: str, body: str, data: dict[str, Any]) -> ProviderSendResult:
        logger.info(
            "push_notification_log",
            extra={"push_token": push_token, "title": title, "body": body, "data": data},
        )
        return ProviderSendResult(ok=True, status="sent", response={"provider": "log"})


class FcmPushProvider(PushProvider):
    """Firebase Cloud Messaging using server-key HTTP endpoint."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._fallback = LogPushProvider()

    async def send(self, *, push_token: str, title: str, body: str, data: dict[str, Any]) -> ProviderSendResult:
        if _network_calls_disabled_for_tests() or not self.settings.fcm_server_key:
            return await self._fallback.send(push_token=push_token, title=title, body=body, data=data)

        payload = {
            "to": push_token,
            "priority": "high",
            "notification": {
                "title": title,
                "body": body,
            },
            "data": data,
        }
        headers = {
            "Authorization": f"key={self.settings.fcm_server_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.post(self.settings.fcm_base_url, json=payload, headers=headers)

            parsed: dict[str, Any] = {}
            if response.text:
                try:
                    parsed = response.json()
                except Exception:
                    parsed = {"raw": response.text[:400]}

            if 200 <= response.status_code < 300:
                success_count = int(parsed.get("success", 0) or 0)
                if success_count > 0:
                    return ProviderSendResult(ok=True, status="sent", response={"provider": "fcm", "body": parsed})
                results = parsed.get("results") if isinstance(parsed, dict) else None
                if isinstance(results, list) and results:
                    error_code = str((results[0] or {}).get("error") or "")
                    if error_code in {"InvalidRegistration", "NotRegistered", "MismatchSenderId"}:
                        return ProviderSendResult(
                            ok=False,
                            status="failed",
                            response={"provider": "fcm", "body": parsed},
                            error=f"fcm_token_invalid:{error_code}",
                            permanent_failure=True,
                            invalid_token=True,
                        )
                return ProviderSendResult(
                    ok=False,
                    status="failed",
                    response={"provider": "fcm", "body": parsed},
                    error="fcm_zero_success",
                )

            return ProviderSendResult(
                ok=False,
                status="failed",
                response={"provider": "fcm", "code": response.status_code, "body": parsed},
                error="fcm_non_2xx",
            )
        except Exception as exc:  # pragma: no cover - network/provider dependent
            return ProviderSendResult(
                ok=False,
                status="failed",
                response={"provider": "fcm"},
                error=f"fcm_exception:{exc}",
            )


class ExpoPushProvider(PushProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._fallback = LogPushProvider()

    async def send(self, *, push_token: str, title: str, body: str, data: dict[str, Any]) -> ProviderSendResult:
        if _network_calls_disabled_for_tests() or not self.settings.expo_push_access_token:
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
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.post(self.settings.expo_push_base_url, json=payload, headers=headers)

            parsed: dict[str, Any] = {}
            if response.text:
                try:
                    parsed = response.json()
                except Exception:
                    parsed = {"raw": response.text[:400]}

            if 200 <= response.status_code < 300:
                ticket = parsed.get("data") if isinstance(parsed, dict) else None
                if isinstance(ticket, dict):
                    ticket_status = ticket.get("status")
                    if ticket_status and ticket_status != "ok":
                        details = ticket.get("details", {}) if isinstance(ticket.get("details"), dict) else {}
                        invalid_token = details.get("error") == "DeviceNotRegistered"
                        return ProviderSendResult(
                            ok=False,
                            status="failed",
                            response={"provider": "expo", "body": parsed},
                            error=f"expo_ticket_failed:{ticket_status}",
                            permanent_failure=invalid_token,
                            invalid_token=invalid_token,
                        )
                return ProviderSendResult(ok=True, status="sent", response={"provider": "expo", "body": parsed})

            return ProviderSendResult(
                ok=False,
                status="failed",
                response={"provider": "expo", "code": response.status_code, "body": parsed},
                error="expo_non_2xx",
            )
        except Exception as exc:  # pragma: no cover - network/provider dependent
            return ProviderSendResult(
                ok=False,
                status="failed",
                response={"provider": "expo"},
                error=f"expo_exception:{exc}",
            )


def build_email_provider(settings: Settings | None = None) -> EmailProvider:
    resolved_settings = settings or get_settings()
    provider_name = (resolved_settings.notification_email_provider or "sendgrid").lower()
    if provider_name == "ses":
        return SesEmailProvider(resolved_settings)
    if provider_name == "sendgrid":
        return SendGridEmailProvider(resolved_settings)
    return LogEmailProvider()
