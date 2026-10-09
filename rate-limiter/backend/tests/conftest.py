"""Shared pytest fixtures for backend tests."""
from __future__ import annotations

import asyncio
import os
import pytest
import pytest_asyncio
import redis.asyncio as aioredis

from app.config import settings

# ─── Redis URL for tests (can be overridden via env) ─────────────────────────
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/1")


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture(scope="function")
async def redis_client():
    """Async Redis client connected to DB 1 (isolated from dev DB 0)."""
    client = aioredis.from_url(
        TEST_REDIS_URL,
        encoding="utf-8",
        decode_responses=False,
        socket_timeout=2.0,
        socket_connect_timeout=2.0,
    )
    yield client
    # Clean up all test keys
    try:
        await client.flushdb()
    except Exception:
        pass
    await client.aclose()
