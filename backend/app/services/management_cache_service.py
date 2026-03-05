from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from hashlib import sha256
from typing import Any

try:
    import redis
except Exception:  # pragma: no cover - optional dependency import fallback
    redis = None


class InMemoryManagementCache:
    def __init__(self, *, max_entries: int = 512) -> None:
        self.max_entries = max_entries
        self._values: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._writes = 0

    def get_json(self, key: str) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            row = self._values.get(key)
            if row is None:
                self._misses += 1
                return None
            expires_at, payload = row
            if expires_at <= now:
                self._values.pop(key, None)
                self._misses += 1
                return None
            self._values.move_to_end(key)
            self._hits += 1
            return json.loads(payload)

    def set_json(self, key: str, payload: dict[str, Any], *, ttl_seconds: int) -> None:
        encoded = json.dumps(payload, sort_keys=True, default=str)
        with self._lock:
            self._values[key] = (time.time() + ttl_seconds, encoded)
            self._values.move_to_end(key)
            self._writes += 1
            while len(self._values) > self.max_entries:
                self._values.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "backend": "memory",
                "entries": len(self._values),
                "hits": self._hits,
                "misses": self._misses,
                "writes": self._writes,
                "max_entries": self.max_entries,
            }


class RedisManagementCache:
    def __init__(self, redis_url: str) -> None:
        if redis is None:
            raise RuntimeError("redis package unavailable")
        self.client = redis.Redis.from_url(redis_url, decode_responses=True)

    def get_json(self, key: str) -> dict[str, Any] | None:
        payload = self.client.get(key)
        if not payload:
            return None
        return json.loads(payload)

    def set_json(self, key: str, payload: dict[str, Any], *, ttl_seconds: int) -> None:
        self.client.setex(key, ttl_seconds, json.dumps(payload, sort_keys=True, default=str))

    def clear(self) -> None:
        pass

    def stats(self) -> dict[str, Any]:
        return {"backend": "redis"}


class ManagementCacheService:
    def __init__(
        self,
        *,
        redis_url: str | None,
        ttl_seconds: int,
        max_entries: int,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.backend = self._build_backend(redis_url=redis_url, max_entries=max_entries)

    def _build_backend(self, *, redis_url: str | None, max_entries: int):
        if redis_url:
            try:
                return RedisManagementCache(redis_url)
            except Exception:
                pass
        return InMemoryManagementCache(max_entries=max_entries)

    def make_key(self, namespace: str, payload: dict[str, Any]) -> str:
        digest = sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        return f"doordrill:{namespace}:{digest}"

    def get_json(self, key: str) -> dict[str, Any] | None:
        return self.backend.get_json(key)

    def set_json(self, key: str, payload: dict[str, Any]) -> None:
        self.backend.set_json(key, payload, ttl_seconds=self.ttl_seconds)

    def clear(self) -> None:
        self.backend.clear()

    def stats(self) -> dict[str, Any]:
        data = self.backend.stats()
        data["ttl_seconds"] = self.ttl_seconds
        return data
