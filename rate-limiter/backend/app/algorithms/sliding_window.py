"""Pure-Python sliding window log implementation (reference / unit-test target).

The clock is injectable so tests can control time deterministically.
Keeps an in-process sorted list of accept timestamps per (client, route) key.
"""
from __future__ import annotations

import bisect
import threading
import time
from typing import Callable, Dict, List

from .base import BaseLimiter, Decision


class SlidingWindowLimiter(BaseLimiter):
    """In-process sliding window log.  Not suitable for multi-instance deployments;
    use RedisLimiter in production.

    Args:
        limit:          Maximum requests allowed per window.
        window_seconds: Length of the rolling window in seconds.
        clock:          Callable returning current time (seconds).
    """

    def __init__(
        self,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._logs: Dict[str, List[float]] = {}

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
        key = f"{client_id}:{route}"
        now = self._clock()
        cutoff = now - self.window_seconds

        with self._lock:
            log = self._logs.setdefault(key, [])

            # Evict timestamps outside the window
            idx = bisect.bisect_left(log, cutoff)
            if idx > 0:
                del log[:idx]

            count = len(log)

            if count < self.limit:
                bisect.insort(log, now)
                remaining = self.limit - count - 1
                # Window resets when the oldest accepted request falls out
                reset_after = (log[0] + self.window_seconds - now) if log else self.window_seconds
                return Decision(
                    allowed=True,
                    remaining=remaining,
                    limit=self.limit,
                    retry_after_seconds=0.0,
                    reset_after_seconds=max(0.0, reset_after),
                )
            else:
                # Retry after the oldest entry leaves the window
                oldest = log[0]
                retry_after = oldest + self.window_seconds - now
                return Decision(
                    allowed=False,
                    remaining=0,
                    limit=self.limit,
                    retry_after_seconds=max(0.0, retry_after),
                    reset_after_seconds=max(0.0, retry_after),
                )
