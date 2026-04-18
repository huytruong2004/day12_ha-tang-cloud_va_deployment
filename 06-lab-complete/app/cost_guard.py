"""Monthly cost guard — Redis-backed when REDIS_URL is set, in-memory fallback otherwise.

Stateless design: monthly spend persists across restarts and is shared across replicas.
"""
import time

from fastapi import HTTPException

from app.config import settings

INPUT_PRICE_PER_1K = 0.00015   # gpt-4o-mini input
OUTPUT_PRICE_PER_1K = 0.0006   # gpt-4o-mini output

try:
    import redis as _redis
    _client = _redis.from_url(settings.redis_url, decode_responses=True) if settings.redis_url else None
    if _client:
        _client.ping()
except Exception:
    _client = None

_local_cost = 0.0
_local_month = time.strftime("%Y-%m")


def _month_key() -> str:
    return f"cost:{time.strftime('%Y-%m')}"


def current_spend() -> float:
    if _client is not None:
        return float(_client.get(_month_key()) or 0.0)
    return _local_cost


def check_and_record_cost(input_tokens: int, output_tokens: int) -> None:
    """Raise 503 if the monthly budget is exhausted; otherwise add to running total."""
    global _local_cost, _local_month
    budget = settings.monthly_budget_usd
    cost = (input_tokens / 1000) * INPUT_PRICE_PER_1K + (output_tokens / 1000) * OUTPUT_PRICE_PER_1K

    if _client is not None:
        key = _month_key()
        current = float(_client.get(key) or 0.0)
        if current >= budget:
            raise HTTPException(503, "Monthly budget exhausted. Try next month.")
        new_total = _client.incrbyfloat(key, cost)
        if float(new_total) == cost:
            _client.expire(key, 32 * 24 * 3600)
        return

    this_month = time.strftime("%Y-%m")
    if this_month != _local_month:
        _local_cost = 0.0
        _local_month = this_month
    if _local_cost >= budget:
        raise HTTPException(503, "Monthly budget exhausted. Try next month.")
    _local_cost += cost


def backend() -> str:
    return "redis" if _client is not None else "memory"
