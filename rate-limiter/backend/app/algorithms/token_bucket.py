"""Pure-Python token bucket implementation (reference / unit-test target).

The clock is injectable so tests can control time deterministically.
"""
from __future__ import annotations

import math
import threading
import time
from typing import Callable, Dict, Tuple

from .base import BaseLimiter, Decision


class _BucketState:
    __slots__ = ("tokens", "ts")

    def __init__(self, tokens: float, ts: float) -> None:
        self.tokens = tokens
        self.ts = ts


class TokenBucketLimiter(BaseLimiter):
    """In-process token bucket.  Not suitable for multi-instance deployments;
    use RedisLimiter in production.

    Args:
        capacity:     Maximum burst size (max tokens held at once).
        refill_rate:  Tokens added per second.
        clock:        Callable returning current time (seconds).  Defaults to
                      ``time.monotonic``.
    """

    def __init__(
        self,
        capacity: int,
        refill_rate: float,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._buckets: Dict[str, _BucketState] = {}

    # ------------------------------------------------------------------
    # BaseLimiter interface
    # ------------------------------------------------------------------
    def is_allowed(
        self,
        client_id: str,
        route: str,
        *,
        limit: int | None = None,
        window_seconds: float | None = None,
        **kwargs,
    ) -> Decision:
        """Check one request.  ``limit`` and ``window_seconds`` are ignored here;
        capacity/refill_rate are set at construction time.
        """
        key = f"{client_id}:{route}"
        now = self._clock()

        with self._lock:
            state = self._buckets.get(key)
            if state is None:
                state = _BucketState(float(self.capacity), now)
                self._buckets[key] = state

            # Refill tokens based on elapsed time
            elapsed = now - state.ts
            state.tokens = min(
                float(self.capacity),
                state.tokens + elapsed * self.refill_rate,
            )
            state.ts = now

            if state.tokens >= 1.0:
                state.tokens -= 1.0
                remaining = math.floor(state.tokens)
                # Time until bucket would be full again
                missing = self.capacity - state.tokens
                reset_after = missing / self.refill_rate if self.refill_rate > 0 else 0.0
                return Decision(
                    allowed=True,
                    remaining=remaining,
                    limit=self.capacity,
                    retry_after_seconds=0.0,
                    reset_after_seconds=reset_after,
                )
            else:
                # Time until at least 1 token is available
                deficit = 1.0 - state.tokens
                retry_after = deficit / self.refill_rate if self.refill_rate > 0 else float("inf")
                reset_after = (self.capacity - state.tokens) / self.refill_rate if self.refill_rate > 0 else 0.0
                return Decision(
                    allowed=False,
                    remaining=0,
                    limit=self.capacity,
                    retry_after_seconds=retry_after,
                    reset_after_seconds=reset_after,
                )
