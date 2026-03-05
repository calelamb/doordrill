from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

try:
    import redis.asyncio as redis
except Exception:  # pragma: no cover - optional dependency load fallback
    redis = None


class BaseEventBuffer:
    async def push(self, session_id: str, event: dict[str, Any]) -> None:
        raise NotImplementedError

    async def drain(self, session_id: str, max_n: int) -> list[dict[str, Any]]:
        raise NotImplementedError


class InMemoryEventBuffer(BaseEventBuffer):
    def __init__(self) -> None:
        self._events: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def push(self, session_id: str, event: dict[str, Any]) -> None:
        async with self._lock:
            event.setdefault("buffered_at", datetime.now(timezone.utc).isoformat())
            self._events[session_id].append(event)

    async def drain(self, session_id: str, max_n: int) -> list[dict[str, Any]]:
        async with self._lock:
            bucket = self._events.get(session_id, [])
            drained = bucket[:max_n]
            self._events[session_id] = bucket[max_n:]
            return drained


class RedisEventBuffer(BaseEventBuffer):
    def __init__(self, redis_url: str, ttl_seconds: int = 1200) -> None:
        if redis is None:
            raise RuntimeError("redis package unavailable")
        self.client = redis.from_url(redis_url, decode_responses=True)
        self.ttl_seconds = ttl_seconds

    def _key(self, session_id: str) -> str:
        return f"doordrill:session:{session_id}:events"

    async def push(self, session_id: str, event: dict[str, Any]) -> None:
        key = self._key(session_id)
        payload = json.dumps(event)
        async with self.client.pipeline() as p:
            await p.rpush(key, payload)
            await p.expire(key, self.ttl_seconds)
            await p.execute()

    async def drain(self, session_id: str, max_n: int) -> list[dict[str, Any]]:
        key = self._key(session_id)
        items = await self.client.lrange(key, 0, max_n - 1)
        if not items:
            return []
        await self.client.ltrim(key, max_n, -1)
        return [json.loads(item) for item in items]
