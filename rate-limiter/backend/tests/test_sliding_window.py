"""Unit tests for the pure-Python sliding window log limiter."""
from __future__ import annotations

import pytest
from app.algorithms.sliding_window import SlidingWindowLimiter


class FakeClock:
    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


# ─── Basic allow / deny ───────────────────────────────────────────────────────

def test_first_request_allowed():
    clock = FakeClock(0.0)
    lim = SlidingWindowLimiter(limit=5, window_seconds=60.0, clock=clock)
    d = lim.is_allowed("c", "/r")
    assert d.allowed is True
    assert d.remaining == 4
    assert d.limit == 5


def test_at_limit_blocks():
    clock = FakeClock(0.0)
    lim = SlidingWindowLimiter(limit=3, window_seconds=60.0, clock=clock)
    for _ in range(3):
        lim.is_allowed("c", "/r")
    d = lim.is_allowed("c", "/r")
    assert d.allowed is False
    assert d.remaining == 0


def test_remaining_decreases():
    clock = FakeClock(0.0)
    lim = SlidingWindowLimiter(limit=5, window_seconds=60.0, clock=clock)
    remainders = [lim.is_allowed("c", "/r").remaining for _ in range(5)]
    assert remainders == [4, 3, 2, 1, 0]


# ─── Window expiry ────────────────────────────────────────────────────────────

def test_entries_expire_after_window():
    clock = FakeClock(0.0)
    lim = SlidingWindowLimiter(limit=3, window_seconds=10.0, clock=clock)
    # Fill the window
    for _ in range(3):
        lim.is_allowed("c", "/r")
    # One more should be blocked
    assert lim.is_allowed("c", "/r").allowed is False
    # Advance beyond the window → entries expire
    clock.advance(10.1)
    d = lim.is_allowed("c", "/r")
    assert d.allowed is True


def test_partial_expiry():
    """Requests made at different times expire at different times."""
    clock = FakeClock(0.0)
    lim = SlidingWindowLimiter(limit=2, window_seconds=10.0, clock=clock)
    lim.is_allowed("c", "/r")          # at t=0
    clock.advance(5.0)
    lim.is_allowed("c", "/r")          # at t=5 – window full (2 requests)
    assert lim.is_allowed("c", "/r").allowed is False  # blocked

    clock.advance(5.1)                 # t=10.1 – first entry (t=0) now expired
    d = lim.is_allowed("c", "/r")
    assert d.allowed is True           # room for one more


# ─── retry_after correctness ──────────────────────────────────────────────────

def test_retry_after_when_blocked():
    clock = FakeClock(0.0)
    lim = SlidingWindowLimiter(limit=1, window_seconds=10.0, clock=clock)
    lim.is_allowed("c", "/r")
    d = lim.is_allowed("c", "/r")
    assert d.allowed is False
    # Entry at t=0, window=10s → retry_after ≈ 10s
    assert 9.9 < d.retry_after_seconds <= 10.0


def test_retry_after_zero_when_allowed():
    clock = FakeClock(0.0)
    lim = SlidingWindowLimiter(limit=5, window_seconds=10.0, clock=clock)
    d = lim.is_allowed("c", "/r")
    assert d.retry_after_seconds == 0.0


# ─── Isolation ───────────────────────────────────────────────────────────────

def test_clients_isolated():
    clock = FakeClock(0.0)
    lim = SlidingWindowLimiter(limit=1, window_seconds=60.0, clock=clock)
    d1 = lim.is_allowed("alice", "/r")
    d2 = lim.is_allowed("bob",   "/r")
    assert d1.allowed and d2.allowed


def test_routes_isolated():
    clock = FakeClock(0.0)
    lim = SlidingWindowLimiter(limit=1, window_seconds=60.0, clock=clock)
    d1 = lim.is_allowed("c", "/products")
    d2 = lim.is_allowed("c", "/orders")
    assert d1.allowed and d2.allowed
