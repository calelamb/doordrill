from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict, deque
from collections.abc import Callable
from functools import wraps
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


def get_rate_limit_key(request: Request) -> str:
    if os.getenv("PYTEST_CURRENT_TEST"):
        test_client = request.headers.get("X-Test-Client")
        if test_client:
            return test_client
    if request.client and request.client.host:
        return request.client.host
    return "anonymous"


try:  # pragma: no cover - exercised when slowapi is installed
    from slowapi import Limiter, _rate_limit_exceeded_handler as rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    limiter = Limiter(key_func=get_rate_limit_key)
except ImportError:  # pragma: no cover - covered by local tests via fallback path
    class RateLimitExceeded(Exception):
        def __init__(self, detail: str = "Rate limit exceeded") -> None:
            super().__init__(detail)
            self.detail = detail


    def _parse_limit(value: str) -> tuple[int, float]:
        count_text, window_text = value.split("/", 1)
        count = int(count_text.strip())
        unit = window_text.strip().lower()
        windows = {
            "second": 1.0,
            "sec": 1.0,
            "minute": 60.0,
            "min": 60.0,
            "hour": 3600.0,
        }
        if unit.endswith("s"):
            unit = unit[:-1]
        window = windows.get(unit)
        if window is None:
            raise ValueError(f"Unsupported rate limit window: {window_text}")
        return count, window


    class Limiter:
        def __init__(self, *, key_func: Callable[[Request], str]) -> None:
            self._key_func = key_func
            self._events: dict[str, deque[float]] = defaultdict(deque)

        def reset(self) -> None:
            self._events.clear()

        def _enforce(self, *, request: Request, bucket: str, count: int, window: float) -> None:
            now = time.monotonic()
            timestamps = self._events[bucket]
            while timestamps and timestamps[0] <= now - window:
                timestamps.popleft()
            if len(timestamps) >= count:
                raise RateLimitExceeded()
            timestamps.append(now)

        def limit(self, value: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
            count, window = _parse_limit(value)

            def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
                is_async = asyncio.iscoroutinefunction(func)

                def resolve_request(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Request:
                    request = kwargs.get("request")
                    if isinstance(request, Request):
                        return request
                    for arg in args:
                        if isinstance(arg, Request):
                            return arg
                    raise RuntimeError("Rate-limited endpoint must accept a Request argument")

                if is_async:

                    @wraps(func)
                    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                        request = resolve_request(args, kwargs)
                        key = f"{func.__module__}.{func.__name__}:{self._key_func(request)}:{value}"
                        self._enforce(request=request, bucket=key, count=count, window=window)
                        return await func(*args, **kwargs)

                    return async_wrapper

                @wraps(func)
                def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                    request = resolve_request(args, kwargs)
                    key = f"{func.__module__}.{func.__name__}:{self._key_func(request)}:{value}"
                    self._enforce(request=request, bucket=key, count=count, window=window)
                    return func(*args, **kwargs)

                return sync_wrapper

            return decorator


    limiter = Limiter(key_func=get_rate_limit_key)

    async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=429)
