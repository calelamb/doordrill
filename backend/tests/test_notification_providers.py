import pytest

from app.core.config import Settings
from app.services.notification_providers import FcmPushProvider, SesEmailProvider, SendGridEmailProvider


@pytest.mark.asyncio
async def test_fcm_provider_falls_back_to_log_without_server_key():
    settings = Settings(fcm_server_key=None)
    provider = FcmPushProvider(settings)
    result = await provider.send(
        push_token="ExponentPushToken[test]",
        title="DoorDrill",
        body="Session complete",
        data={"session_id": "abc"},
    )
    assert result.ok is True
    assert result.response["provider"] == "log"


@pytest.mark.asyncio
async def test_ses_provider_falls_back_to_log_without_smtp_credentials():
    settings = Settings(
        ses_smtp_username=None,
        ses_smtp_password=None,
        ses_from_email=None,
    )
    provider = SesEmailProvider(settings)
    result = await provider.send(to_email="manager@example.com", subject="DoorDrill", body="Session completed")
    assert result.ok is True
    assert result.response["provider"] == "log"


@pytest.mark.asyncio
async def test_sendgrid_provider_falls_back_to_log_without_api_key():
    settings = Settings(sendgrid_api_key=None, sendgrid_from_email=None)
    provider = SendGridEmailProvider(settings)
    result = await provider.send(to_email="manager@example.com", subject="DoorDrill", body="Session completed")
    assert result.ok is True
    assert result.response["provider"] == "log"
