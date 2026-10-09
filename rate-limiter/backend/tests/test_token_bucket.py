"""Unit tests for the pure-Python token bucket limiter."""
from __future__ import annotations

import pytest
from app.algorithms.token_bucket import TokenBucketLimiter


class FakeClock:
    """Injectable monotonic clock."""
    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


# ─── Basic allow / deny ───────────────────────────────────────────────────────

def test_initial_request_allowed():
    clock = FakeClock(0.0)
    limiter = TokenBucketLimiter(capacity=5, refill_rate=1.0, clock=clock)
    d = limiter.is_allowed("client1", "/test")
    assert d.allowed is True
    assert d.remaining == 4
    assert d.limit == 5


def test_burst_limit_respected():
    clock = FakeClock(0.0)
    limiter = TokenBucketLimiter(capacity=3, refill_rate=1.0, clock=clock)
    results = [limiter.is_allowed("c", "/r") for _ in range(5)]
    allowed = [r.allowed for r in results]
    assert allowed == [True, True, True, False, False]


def test_last_allowed_remaining_is_zero():
    clock = FakeClock(0.0)
    limiter = TokenBucketLimiter(capacity=2, refill_rate=1.0, clock=clock)
    limiter.is_allowed("c", "/r")
    d = limiter.is_allowed("c", "/r")
    assert d.allowed is True
    assert d.remaining == 0


# ─── Refill math ──────────────────────────────────────────────────────────────

def test_refill_after_time():
    clock = FakeClock(0.0)
    limiter = TokenBucketLimiter(capacity=5, refill_rate=2.0, clock=clock)
    # Drain all 5 tokens
    for _ in range(5):
        limiter.is_allowed("c", "/r")
    # Next request immediately should be blocked
    d = limiter.is_allowed("c", "/r")
    assert d.allowed is False

    # Advance 1 second → 2 tokens refilled
    clock.advance(1.0)
    d = limiter.is_allowed("c", "/r")
    assert d.allowed is True


def test_refill_capped_at_capacity():
    clock = FakeClock(0.0)
    limiter = TokenBucketLimiter(capacity=5, refill_rate=2.0, clock=clock)
    # Drain all
    for _ in range(5):
        limiter.is_allowed("c", "/r")
    # Advance 100 seconds – tokens should cap at 5
    clock.advance(100.0)
    d = limiter.is_allowed("c", "/r")
    assert d.remaining == 4   # was 5, minus 1


# ─── retry_after correctness ──────────────────────────────────────────────────

def test_retry_after_when_blocked():
    clock = FakeClock(0.0)
    limiter = TokenBucketLimiter(capacity=1, refill_rate=2.0, clock=clock)
    limiter.is_allowed("c", "/r")   # drain
    d = limiter.is_allowed("c", "/r")
    assert d.allowed is False
    # With rate=2 tok/s and 1 token deficit, retry_after ≈ 0.5s
    assert 0.4 < d.retry_after_seconds < 0.6


def test_retry_after_zero_when_allowed():
    clock = FakeClock(0.0)
    limiter = TokenBucketLimiter(capacity=5, refill_rate=1.0, clock=clock)
    d = limiter.is_allowed("c", "/r")
    assert d.retry_after_seconds == 0.0


# ─── Isolation between clients / routes ───────────────────────────────────────

def test_different_clients_are_isolated():
    clock = FakeClock(0.0)
    limiter = TokenBucketLimiter(capacity=1, refill_rate=1.0, clock=clock)
    d1 = limiter.is_allowed("alice", "/r")
    d2 = limiter.is_allowed("bob",   "/r")
    assert d1.allowed is True
    assert d2.allowed is True


def test_different_routes_are_isolated():
    clock = FakeClock(0.0)
    limiter = TokenBucketLimiter(capacity=1, refill_rate=1.0, clock=clock)
    d1 = limiter.is_allowed("c", "/products")
    d2 = limiter.is_allowed("c", "/orders")
    assert d1.allowed is True
    assert d2.allowed is True


# ─── reset_after_seconds ─────────────────────────────────────────────────────

def test_reset_after_seconds_present_when_allowed():
    clock = FakeClock(0.0)
    limiter = TokenBucketLimiter(capacity=5, refill_rate=1.0, clock=clock)
    d = limiter.is_allowed("c", "/r")
    assert d.reset_after_seconds > 0


def test_reset_after_seconds_present_when_blocked():
    clock = FakeClock(0.0)
    limiter = TokenBucketLimiter(capacity=1, refill_rate=1.0, clock=clock)
    limiter.is_allowed("c", "/r")
    d = limiter.is_allowed("c", "/r")
    assert d.allowed is False
    assert d.reset_after_seconds > 0
