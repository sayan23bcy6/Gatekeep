"""Tests for the rate-limit middleware: 429 status, Retry-After, headers, body shape."""
from __future__ import annotations

import asyncio
import os
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient

# Patch Redis before importing the app
import redis.asyncio as aioredis
from redis.exceptions import RedisError


# ─── Helpers to build a minimal app with mocked Redis ─────────────────────────

def _make_mock_redis(fail: bool = False, fail_mode: str = "open"):
    """Return a mock Redis that simulates allow/deny or failure."""
    mock = AsyncMock()

    if fail:
        mock.evalsha.side_effect = RedisError("mocked Redis down")
        mock.script_load.side_effect = RedisError("mocked Redis down")
    else:
        # Simulate token bucket allowing the first N calls, blocking rest
        call_count = {"n": 0}

        async def mock_evalsha(sha, num_keys, *args):
            call_count["n"] += 1
            allowed = 1
            remaining = max(0, 10 - call_count["n"])
            return [allowed, remaining, 0, 1000]

        mock.evalsha.side_effect = mock_evalsha
        mock.script_load.return_value = "faksha"

    mock.pipeline.return_value.__aenter__ = AsyncMock(return_value=mock)
    mock.pipeline.return_value.__aexit__ = AsyncMock(return_value=False)
    pipe = AsyncMock()
    pipe.hincrby = AsyncMock()
    pipe.hset = AsyncMock()
    pipe.expire = AsyncMock()
    pipe.execute = AsyncMock(return_value=[1, 1, 1, 1, 1])
    mock.pipeline.return_value = pipe
    return mock


# ─── App fixture ──────────────────────────────────────────────────────────────

@pytest.fixture
def app_client():
    """TestClient with a fully seeded app and mocked limiters that always allow."""
    import os
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test_mw.db")
    os.environ.setdefault("FAIL_MODE", "open")

    from app.main import app
    from app.redis_limiter import TokenBucketRedisLimiter, SlidingWindowRedisLimiter
    from app.algorithms.base import Decision

    # Always-allow mock decision
    allow_decision = Decision(allowed=True, remaining=9, limit=10,
                              retry_after_seconds=0.0, reset_after_seconds=5.0)
    block_decision = Decision(allowed=False, remaining=0, limit=10,
                              retry_after_seconds=2.0, reset_after_seconds=2.0)

    # Patch lifespan to avoid real Redis
    original_lifespan = app.router.lifespan_context

    from app.db import create_tables, seed_db, SessionLocal
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def patched_lifespan(app):
        create_tables()
        db = SessionLocal()
        try:
            seed_db(db)
        finally:
            db.close()

        mock_redis = AsyncMock()
        pipe = MagicMock()
        pipe.execute = AsyncMock(return_value=[1, 1, 1, 1, 1])
        mock_redis.pipeline = MagicMock(return_value=pipe)

        tb = AsyncMock(spec=TokenBucketRedisLimiter)
        sw = AsyncMock(spec=SlidingWindowRedisLimiter)
        tb.is_allowed.return_value = allow_decision
        sw.is_allowed.return_value = allow_decision

        app.state.redis = mock_redis
        app.state.tb_limiter = tb
        app.state.sw_limiter = sw
        yield

    app.router.lifespan_context = patched_lifespan
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, app
    app.router.lifespan_context = original_lifespan


@pytest.fixture
def blocking_app_client():
    """TestClient where the TB limiter always blocks."""
    import os
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test_mw.db")

    from app.main import app
    from app.redis_limiter import TokenBucketRedisLimiter, SlidingWindowRedisLimiter
    from app.algorithms.base import Decision
    from app.db import create_tables, seed_db, SessionLocal
    from contextlib import asynccontextmanager

    block_decision = Decision(allowed=False, remaining=0, limit=10,
                              retry_after_seconds=2.5, reset_after_seconds=2.5)

    @asynccontextmanager
    async def patched_lifespan(app):
        create_tables()
        db = SessionLocal()
        try:
            seed_db(db)
        finally:
            db.close()

        mock_redis = AsyncMock()
        pipe = MagicMock()
        pipe.execute = AsyncMock(return_value=[1, 1, 1, 1, 1])
        mock_redis.pipeline = MagicMock(return_value=pipe)

        tb = AsyncMock(spec=TokenBucketRedisLimiter)
        sw = AsyncMock(spec=SlidingWindowRedisLimiter)
        tb.is_allowed.return_value = block_decision
        sw.is_allowed.return_value = block_decision

        app.state.redis = mock_redis
        app.state.tb_limiter = tb
        app.state.sw_limiter = sw
        yield

    original = app.router.lifespan_context
    app.router.lifespan_context = patched_lifespan
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client
    app.router.lifespan_context = original


# ─── Tests ───────────────────────────────────────────────────────────────────

def test_allowed_request_returns_200(app_client):
    client, _ = app_client
    r = client.get("/api/products", headers={"X-API-Key": "free-key-001"})
    assert r.status_code == 200


def test_allowed_request_has_ratelimit_headers(app_client):
    client, _ = app_client
    r = client.get("/api/products", headers={"X-API-Key": "free-key-001"})
    assert "X-RateLimit-Limit" in r.headers
    assert "X-RateLimit-Remaining" in r.headers
    assert "X-RateLimit-Reset" in r.headers


def test_blocked_request_returns_429(blocking_app_client):
    r = blocking_app_client.get("/api/products", headers={"X-API-Key": "free-key-001"})
    assert r.status_code == 429


def test_blocked_request_has_retry_after(blocking_app_client):
    r = blocking_app_client.get("/api/products", headers={"X-API-Key": "free-key-001"})
    assert "Retry-After" in r.headers
    assert int(r.headers["Retry-After"]) >= 1


def test_blocked_request_json_body_shape(blocking_app_client):
    r = blocking_app_client.get("/api/products", headers={"X-API-Key": "free-key-001"})
    body = r.json()
    assert "error" in body
    assert body["error"] == "rate_limited"
    assert "retry_after" in body


def test_blocked_request_has_ratelimit_headers(blocking_app_client):
    r = blocking_app_client.get("/api/products", headers={"X-API-Key": "free-key-001"})
    assert "X-RateLimit-Limit" in r.headers
    assert "X-RateLimit-Remaining" in r.headers


def test_health_endpoint_is_exempt(blocking_app_client):
    """Health endpoint should bypass rate limiting."""
    r = blocking_app_client.get("/health")
    assert r.status_code == 200


def test_unknown_api_key_gets_free_tier(app_client):
    """Unknown API keys should still work (using free tier defaults)."""
    client, _ = app_client
    r = client.get("/api/products", headers={"X-API-Key": "totally-unknown-key-xyz"})
    assert r.status_code == 200


def test_ip_fallback_when_no_api_key(app_client):
    """Requests without X-API-Key should use IP as client ID."""
    client, _ = app_client
    r = client.get("/api/products")   # no API key header
    assert r.status_code == 200
