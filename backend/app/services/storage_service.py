from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class StorageService:
    """S3/R2 presigning with fallback URL generation."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._s3_client = self._build_s3_client()

    def _build_s3_client(self):
        if not self.settings.object_storage_access_key or not self.settings.object_storage_secret_key:
            return None
        try:
            import boto3
        except Exception:
            logger.warning("boto3 unavailable; using storage URL fallback")
            return None

        client_kwargs = {
            "service_name": "s3",
            "region_name": self.settings.object_storage_region,
            "aws_access_key_id": self.settings.object_storage_access_key,
            "aws_secret_access_key": self.settings.object_storage_secret_key,
        }
        if self.settings.object_storage_endpoint:
            client_kwargs["endpoint_url"] = self.settings.object_storage_endpoint
        if self.settings.object_storage_force_path_style:
            client_kwargs["config"] = boto3.session.Config(s3={"addressing_style": "path"})

        try:
            return boto3.client(**client_kwargs)
        except Exception:
            logger.exception("Failed to initialize object storage client")
            return None

    def get_presigned_url(self, storage_key: str, ttl_seconds: int = 3600) -> str:
        ttl = ttl_seconds or self.settings.default_presign_ttl_seconds
        if self._s3_client is not None:
            try:
                return self._s3_client.generate_presigned_url(
                    ClientMethod="get_object",
                    Params={"Bucket": self.settings.storage_bucket, "Key": storage_key},
                    ExpiresIn=ttl,
                )
            except Exception:
                logger.exception("Failed to generate presigned URL", extra={"storage_key": storage_key})

        if self.settings.object_storage_public_base_url:
            base = self.settings.object_storage_public_base_url.rstrip("/")
            return f"{base}/{quote(storage_key)}"

        expires = int((datetime.now(timezone.utc) + timedelta(seconds=ttl)).timestamp())
        return f"https://storage.local/{storage_key}?expires={expires}"
