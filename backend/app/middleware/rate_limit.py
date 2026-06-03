"""Per-IP sliding-window rate limiter backed by Redis.

Configuration is read from ``app.config.settings``; the middleware falls
through gracefully when Redis is unreachable.

Rate limit headers set on every response:
    X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset
"""

import json
import logging
import time
from typing import Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config import settings

logger = logging.getLogger(__name__)

# Sorted-set key prefix in Redis
_REDIS_KEY_PREFIX = "ratelimit:"

# Paths that are never rate-limited
_SKIP_PATHS = frozenset({
    "/api/v1/system/health",
    "/docs",
    "/openapi.json",
    "/redoc",
})


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter per client IP.

    Requires a ``redis.asyncio.Redis`` client.  If *redis* is ``None``
    or the Redis call fails, the request is passed through without
    rate-limiting (fail-open).
    """

    def __init__(
        self,
        app: ASGIApp,
        redis: Optional["Redis"] = None,  # type: ignore[name-defined]
        limit: int = 60,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(app)
        self.redis = redis
        self.limit = limit
        self.window = window_seconds

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip paths that should never be rate-limited
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        # Bail early when Redis is not available
        if self.redis is None:
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        key = f"{_REDIS_KEY_PREFIX}{client_ip}"
        now = time.time()
        window_start = now - self.window

        try:
            # Clean expired entries, count remaining, add current
            pipe = self.redis.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zcard(key)
            await pipe.execute()

            # The pipeline above uses implicit MULTI — now read the count
            # Actually: redis-py pipelines are buffered; let's do it stepwise.
            await self.redis.zremrangebyscore(key, 0, window_start)
            count = await self.redis.zcard(key)

            if count >= self.limit:
                remaining_ttl = await self.redis.ttl(key)
                if remaining_ttl < 0:
                    remaining_ttl = self.window
                return Response(
                    status_code=429,
                    content=json.dumps({
                        "error": {
                            "code": "RATE_LIMITED",
                            "message": "Too many requests. Please try again later.",
                        }
                    }),
                    media_type="application/json",
                    headers={
                        "X-RateLimit-Limit": str(self.limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(int(now + remaining_ttl)),
                        "Retry-After": str(int(remaining_ttl)),
                    },
                )

            # Record this request
            await self.redis.zadd(key, {str(time.time()): now})
            await self.redis.expire(key, self.window)

            remaining = max(0, self.limit - count - 1)
            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(self.limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(int(now + self.window))
            return response

        except Exception as exc:
            logger.warning(
                "Rate limiter error for %s (falling through): %s", client_ip, exc
            )
            return await call_next(request)

    @staticmethod
    def _get_client_ip(request: Request) -> str:
        """Extract client IP from request, preferring X-Forwarded-For."""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"
