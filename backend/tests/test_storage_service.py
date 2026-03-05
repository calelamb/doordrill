from app.core.config import Settings
from app.services.storage_service import StorageService


def test_storage_service_falls_back_to_placeholder_url():
    settings = Settings(
        OBJECT_STORAGE_ACCESS_KEY=None,
        OBJECT_STORAGE_SECRET_KEY=None,
        OBJECT_STORAGE_PUBLIC_BASE_URL=None,
    )
    service = StorageService(settings=settings)
    url = service.get_presigned_url("sessions/abc/canonical_transcript.json", ttl_seconds=90)
    assert url.startswith("https://storage.local/sessions/abc/canonical_transcript.json?expires=")


def test_storage_service_uses_public_base_url_when_configured():
    settings = Settings(
        OBJECT_STORAGE_ACCESS_KEY=None,
        OBJECT_STORAGE_SECRET_KEY=None,
        OBJECT_STORAGE_PUBLIC_BASE_URL="https://cdn.example.com/doordrill",
    )
    service = StorageService(settings=settings)
    url = service.get_presigned_url("sessions/abc/audio clip.opus")
    assert url == "https://cdn.example.com/doordrill/sessions/abc/audio%20clip.opus"
