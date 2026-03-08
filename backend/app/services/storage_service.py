from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
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
            from botocore.client import Config
            from botocore.session import get_session
        except Exception:
            logger.warning("botocore unavailable; using storage URL fallback")
            return None

        client_kwargs = {
            "service_name": "s3",
            "region_name": self.settings.object_storage_region,
            "aws_access_key_id": self.settings.object_storage_access_key,
            "aws_secret_access_key": self.settings.object_storage_secret_key,
            "config": Config(signature_version="s3v4"),
        }
        if self.settings.object_storage_endpoint:
            client_kwargs["endpoint_url"] = self.settings.object_storage_endpoint
        if self.settings.object_storage_force_path_style:
            client_kwargs["config"] = Config(signature_version="s3v4", s3={"addressing_style": "path"})

        try:
            return get_session().create_client(**client_kwargs)
        except Exception:
            logger.exception("Failed to initialize object storage client")
            return None

    def _local_object_path(self, storage_key: str) -> Path:
        return Path("uploads") / "storage" / storage_key

    def upload_audio(self, storage_key: str, ttl_seconds: int = 3600, content_type: str = "audio/ogg") -> dict[str, Any]:
        ttl = ttl_seconds or self.settings.default_presign_ttl_seconds
        headers = {"Content-Type": content_type}

        if self._s3_client is not None:
            try:
                url = self._s3_client.generate_presigned_url(
                    ClientMethod="put_object",
                    Params={
                        "Bucket": self.settings.storage_bucket,
                        "Key": storage_key,
                        "ContentType": content_type,
                    },
                    ExpiresIn=ttl,
                )
                return {
                    "method": "PUT",
                    "url": url,
                    "headers": headers,
                    "storage_key": storage_key,
                    "expires_in": ttl,
                }
            except Exception:
                logger.exception("Failed to generate upload presigned URL", extra={"storage_key": storage_key})

        if self.settings.object_storage_public_base_url:
            base = self.settings.object_storage_public_base_url.rstrip("/")
            return {
                "method": "PUT",
                "url": f"{base}/{quote(storage_key)}",
                "headers": headers,
                "storage_key": storage_key,
                "expires_in": ttl,
            }

        expires = int((datetime.now(timezone.utc) + timedelta(seconds=ttl)).timestamp())
        return {
            "method": "PUT",
            "url": f"https://storage.local/{storage_key}?expires={expires}",
            "headers": headers,
            "storage_key": storage_key,
            "expires_in": ttl,
        }

    def upload_bytes(self, storage_key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        if self._s3_client is not None:
            self._s3_client.put_object(
                Bucket=self.settings.storage_bucket,
                Key=storage_key,
                Body=data,
                ContentType=content_type,
            )
            return storage_key

        object_path = self._local_object_path(storage_key)
        object_path.parent.mkdir(parents=True, exist_ok=True)
        object_path.write_bytes(data)
        return storage_key

    def download_bytes(self, storage_key: str) -> bytes:
        if self._s3_client is not None:
            response = self._s3_client.get_object(Bucket=self.settings.storage_bucket, Key=storage_key)
            body = response.get("Body")
            if body is None:
                raise FileNotFoundError(f"storage object missing body: {storage_key}")
            return body.read()

        object_path = self._local_object_path(storage_key)
        if not object_path.exists():
            raise FileNotFoundError(f"storage object not found: {storage_key}")
        return object_path.read_bytes()

    def delete_object(self, storage_key: str) -> None:
        if self._s3_client is not None:
            self._s3_client.delete_object(Bucket=self.settings.storage_bucket, Key=storage_key)
            return

        object_path = self._local_object_path(storage_key)
        if object_path.exists():
            object_path.unlink()

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
