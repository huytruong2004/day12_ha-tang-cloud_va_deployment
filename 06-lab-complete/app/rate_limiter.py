"""Rate limiter — Redis-backed when REDIS_URL is set, in-memory fallback otherwise.

Stateless design: production deployments share state across replicas via Redis.
"""
import time
from collections import defaultdict, deque

from fastapi import HTTPException

from app.config import settings

try:
    import redis as _redis
    _client = _redis.from_url(settings.redis_url, decode_responses=True) if settings.redis_url else None
    if _client:
        _client.ping()
except Exception:
    _client = None

_local_windows: dict[str, deque] = defaultdict(deque)


def check_rate_limit(key: str) -> None:
    """Raise 429 if `key` has used more than `rate_limit_per_minute` in the last 60s."""
    limit = settings.rate_limit_per_minute

    if _client is not None:
        bucket = int(time.time() // 60)
        redis_key = f"ratelimit:{key}:{bucket}"
        count = _client.incr(redis_key)
        if count == 1:
            _client.expire(redis_key, 60)
        if count > limit:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {limit} req/min",
                headers={"Retry-After": "60"},
            )
        return

    now = time.time()
    window = _local_windows[key]
    while window and window[0] < now - 60:
        window.popleft()
    if len(window) >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {limit} req/min",
            headers={"Retry-After": "60"},
        )
    window.append(now)


def backend() -> str:
    return "redis" if _client is not None else "memory"
