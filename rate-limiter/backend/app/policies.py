"""Plan tier → limit parameter mappings.

Each tier defines:
- token_bucket:    capacity (burst) and refill_rate (tokens/sec)
- sliding_window:  limit (requests) and window_seconds (per-minute quota)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TierPolicy:
    # Token bucket parameters (per-second rate limiting)
    capacity: int          # burst size
    refill_rate: float     # tokens per second

    # Sliding window parameters (per-minute quota)
    sw_limit: int          # max requests per window
    sw_window_seconds: float = 60.0


POLICIES: dict[str, TierPolicy] = {
    "free": TierPolicy(
        capacity=10,
        refill_rate=1.0,
        sw_limit=30,
        sw_window_seconds=60.0,
    ),
    "pro": TierPolicy(
        capacity=100,
        refill_rate=20.0,
        sw_limit=500,
        sw_window_seconds=60.0,
    ),
    "enterprise": TierPolicy(
        capacity=1000,
        refill_rate=200.0,
        sw_limit=5000,
        sw_window_seconds=60.0,
    ),
}

DEFAULT_POLICY = POLICIES["free"]


def get_policy(tier: str) -> TierPolicy:
    return POLICIES.get(tier, DEFAULT_POLICY)
