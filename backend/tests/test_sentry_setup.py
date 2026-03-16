from app.core.config import Settings
from app.main import _init_sentry, _scrub_sentry_event


def test_init_sentry_is_noop_without_dsn(monkeypatch):
    called = False

    def fake_init(**_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("app.main.sentry_sdk.init", fake_init)

    settings = Settings(SENTRY_DSN=None)

    _init_sentry(settings)

    assert called is False


def test_init_sentry_registers_expected_integrations(monkeypatch):
    captured = {}

    def fake_init(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("app.main.sentry_sdk.init", fake_init)

    settings = Settings(
        SENTRY_DSN="https://public@example.ingest.sentry.io/1",
        environment="staging",
        SENTRY_TRACES_SAMPLE_RATE=0.25,
    )

    _init_sentry(settings)

    assert captured["dsn"] == "https://public@example.ingest.sentry.io/1"
    assert captured["environment"] == "staging"
    assert captured["traces_sample_rate"] == 0.25
    assert any(type(integration).__name__ == "FastApiIntegration" for integration in captured["integrations"])
    assert any(type(integration).__name__ == "SqlalchemyIntegration" for integration in captured["integrations"])
    assert any(type(integration).__name__ == "LoggingIntegration" for integration in captured["integrations"])


def test_scrub_sentry_event_filters_sensitive_request_fields():
    event = {
        "request": {
            "headers": {
                "authorization": "Bearer abc",
                "cookie": "session=123",
            },
            "data": {
                "password": "secret",
                "password_hash": "hash",
                "token": "token",
                "refresh_token": "refresh",
                "access_token": "access",
                "safe": "value",
            },
        }
    }

    scrubbed = _scrub_sentry_event(event, {})

    assert scrubbed["request"]["headers"]["authorization"] == "[Filtered]"
    assert scrubbed["request"]["headers"]["cookie"] == "[Filtered]"
    assert scrubbed["request"]["data"]["password"] == "[Filtered]"
    assert scrubbed["request"]["data"]["password_hash"] == "[Filtered]"
    assert scrubbed["request"]["data"]["token"] == "[Filtered]"
    assert scrubbed["request"]["data"]["refresh_token"] == "[Filtered]"
    assert scrubbed["request"]["data"]["access_token"] == "[Filtered]"
    assert scrubbed["request"]["data"]["safe"] == "value"
