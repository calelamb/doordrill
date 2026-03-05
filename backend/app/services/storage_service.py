from __future__ import annotations

from datetime import datetime, timedelta, timezone


class StorageService:
    """Presigned URL placeholder; wire to S3/R2 SDK in production."""

    def get_presigned_url(self, storage_key: str, ttl_seconds: int = 3600) -> str:
        expires = int((datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).timestamp())
        return f"https://storage.local/{storage_key}?expires={expires}"
