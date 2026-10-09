"""Redis concurrency + failure-mode tests for the distributed limiters.

Requires a running Redis at TEST_REDIS_URL (default: redis://localhost:6379/1).
Tests are skipped automatically when Redis is unreachable.
"""
from __future__ import annotations

import asyncio
import os
import pytest
import pytest_asyncio

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.redis_limiter import TokenBucketRedisLimiter, SlidingWindowRedisLimiter

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/1")


async def _check_redis(url: str) -> bool:
    try:
        client = aioredis.from_url(url, socket_timeout=1.0, socket_connect_timeout=1.0)
        await client.ping()
        await client.aclose()
        return True
    except Exception:
        return False


def requires_redis():
    return pytest.mark.skipif(
        not asyncio.get_event_loop().run_until_complete(_check_redis(TEST_REDIS_URL))
        if not asyncio.get_event_loop().is_running()
        else False,
        reason="Redis not available",
    )


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def redis_client():
    client = aioredis.from_url(
        TEST_REDIS_URL,
        socket_timeout=2.0,
        socket_connect_timeout=2.0,
        decode_responses=False,
    )
    try:
        await client.ping()
    except Exception:
        pytest.skip("Redis not available")
    yield client
    await client.flushdb()
    await client.aclose()


@pytest_asyncio.fixture
async def tb_limiter(redis_client):
    from pathlib import Path
    lua = (Path(__file__).parents[1] / "app" / "lua" / "token_bucket.lua").read_text()
    return TokenBucketRedisLimiter(redis_client, lua_script=lua, fail_mode="closed")


@pytest_asyncio.fixture
async def sw_limiter(redis_client):
    from pathlib import Path
    lua = (Path(__file__).parents[1] / "app" / "lua" / "sliding_window.lua").read_text()
    return SlidingWindowRedisLimiter(redis_client, lua_script=lua, fail_mode="closed")


# ─── Concurrency tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_token_bucket_concurrency_200_requests_limit_50(tb_limiter):
    """200 concurrent requests with capacity=50 must allow exactly 50."""
    CONCURRENT = 200
    LIMIT = 50

    async def one_request():
        return await tb_limiter.is_allowed(
            "concurrent-tb", "/test",
            capacity=LIMIT,
            refill_rate=0.0,   # no refill during test
        )

    decisions = await asyncio.gather(*[one_request() for _ in range(CONCURRENT)])
    allowed = sum(1 for d in decisions if d.allowed)
    blocked = sum(1 for d in decisions if not d.allowed)

    assert allowed == LIMIT, f"Expected {LIMIT} allowed, got {allowed}"
    assert blocked == CONCURRENT - LIMIT


@pytest.mark.asyncio
async def test_sliding_window_concurrency_200_requests_limit_50(sw_limiter):
    """200 concurrent requests with limit=50 must allow exactly 50."""
    CONCURRENT = 200
    LIMIT = 50

    async def one_request():
        return await sw_limiter.is_allowed(
            "concurrent-sw", "/test",
            limit=LIMIT,
            window_seconds=3600.0,   # huge window so nothing expires
        )

    decisions = await asyncio.gather(*[one_request() for _ in range(CONCURRENT)])
    allowed = sum(1 for d in decisions if d.allowed)
    blocked = sum(1 for d in decisions if not d.allowed)

    assert allowed == LIMIT, f"Expected {LIMIT} allowed, got {allowed}"
    assert blocked == CONCURRENT - LIMIT


# ─── Failure mode tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fail_closed_returns_denied_on_bad_redis():
    """When Redis is unreachable, fail-closed limiter must block requests."""
    from pathlib import Path
    lua = (Path(__file__).parents[1] / "app" / "lua" / "token_bucket.lua").read_text()

    bad_client = aioredis.from_url(
        "redis://127.0.0.1:19999",    # nothing listening here
        socket_timeout=0.05,
        socket_connect_timeout=0.05,
        decode_responses=False,
    )
    limiter = TokenBucketRedisLimiter(bad_client, lua_script=lua, fail_mode="closed")
    d = await limiter.is_allowed("c", "/r", capacity=10, refill_rate=1.0)
    assert d.allowed is False
    await bad_client.aclose()


@pytest.mark.asyncio
async def test_fail_open_returns_allowed_on_bad_redis():
    """When Redis is unreachable, fail-open limiter must allow requests."""
    from pathlib import Path
    lua = (Path(__file__).parents[1] / "app" / "lua" / "token_bucket.lua").read_text()

    bad_client = aioredis.from_url(
        "redis://127.0.0.1:19999",
        socket_timeout=0.05,
        socket_connect_timeout=0.05,
        decode_responses=False,
    )
    limiter = TokenBucketRedisLimiter(bad_client, lua_script=lua, fail_mode="open")
    d = await limiter.is_allowed("c", "/r", capacity=10, refill_rate=1.0)
    assert d.allowed is True
    await bad_client.aclose()


@pytest.mark.asyncio
async def test_fail_closed_sliding_window():
    from pathlib import Path
    lua = (Path(__file__).parents[1] / "app" / "lua" / "sliding_window.lua").read_text()

    bad_client = aioredis.from_url(
        "redis://127.0.0.1:19999",
        socket_timeout=0.05,
        socket_connect_timeout=0.05,
        decode_responses=False,
    )
    limiter = SlidingWindowRedisLimiter(bad_client, lua_script=lua, fail_mode="closed")
    d = await limiter.is_allowed("c", "/r", limit=10, window_seconds=60.0)
    assert d.allowed is False
    await bad_client.aclose()
