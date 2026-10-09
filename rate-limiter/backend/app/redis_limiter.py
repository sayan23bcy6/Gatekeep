"""Distributed rate limiter implementations backed by Redis Lua scripts.

Both TokenBucketRedisLimiter and SlidingWindowRedisLimiter:
- Load their Lua scripts once on startup (SCRIPT LOAD → SHA) and execute
  with EVALSHA, falling back to EVAL on NOSCRIPT errors.
- Use Redis server TIME inside the Lua script for clock correctness.
- Respect FAIL_MODE (open/closed) when Redis is unreachable.
"""
from __future__ import annotations

import logging
import math
import os
from pathlib import Path
from typing import Optional

import redis.asyncio as aioredis
from redis.exceptions import NoScriptError, RedisError

from .algorithms.base import Decision
from .config import settings

logger = logging.getLogger(__name__)

_LUA_DIR = Path(__file__).parent / "lua"

# ─── TTL for rate-limit keys in Redis ────────────────────────────────────────
_KEY_TTL = 3600  # 1 hour idle expiry


def _load_lua(filename: str) -> str:
    return (_LUA_DIR / filename).read_text(encoding="utf-8")


_TB_SCRIPT = _load_lua("token_bucket.lua")
_SW_SCRIPT = _load_lua("sliding_window.lua")


def _fail_decision(fail_mode: str) -> Decision:
    """Return a Decision according to fail-open / fail-closed policy."""
    if fail_mode == "closed":
        return Decision(
            allowed=False,
            remaining=0,
            limit=0,
            retry_after_seconds=1.0,
            reset_after_seconds=1.0,
        )
    # fail-open
    return Decision(allowed=True, remaining=-1, limit=-1)


class RedisLimiterBase:
    """Shared logic for loading / executing Lua scripts."""

    def __init__(
        self,
        redis_client: aioredis.Redis,
        lua_script: str,
        fail_mode: str = "open",
    ) -> None:
        self._redis = redis_client
        self._script = lua_script
        self._fail_mode = fail_mode
        self._sha: Optional[str] = None

    async def _ensure_sha(self) -> str:
        if self._sha is None:
            self._sha = await self._redis.script_load(self._script)
        return self._sha

    async def _evalsha(self, keys: list, args: list) -> list:
        """Run the Lua script; reload on NOSCRIPT and retry once."""
        sha = await self._ensure_sha()
        try:
            return await self._redis.evalsha(sha, len(keys), *keys, *args)
        except NoScriptError:
            logger.warning("NOSCRIPT – reloading Lua SHA")
            self._sha = await self._redis.script_load(self._script)
            return await self._redis.evalsha(self._sha, len(keys), *keys, *args)


class TokenBucketRedisLimiter(RedisLimiterBase):
    """Distributed token bucket using a Redis Lua script."""

    async def is_allowed(
        self,
        client_id: str,
        route: str,
        *,
        capacity: int,
        refill_rate: float,
    ) -> Decision:
        key = f"rl:{client_id}:{route}"
        try:
            result = await self._evalsha(
                keys=[key],
                args=[capacity, refill_rate, _KEY_TTL],
            )
            allowed, remaining, retry_ms, reset_ms = (int(x) for x in result)
            return Decision(
                allowed=bool(allowed),
                remaining=remaining,
                limit=capacity,
                retry_after_seconds=retry_ms / 1000.0,
                reset_after_seconds=reset_ms / 1000.0,
            )
        except RedisError as exc:
            logger.error("Redis error in token bucket: %s – fail_mode=%s", exc, self._fail_mode)
            return _fail_decision(self._fail_mode)


class SlidingWindowRedisLimiter(RedisLimiterBase):
    """Distributed sliding window log using a Redis Lua script."""

    async def is_allowed(
        self,
        client_id: str,
        route: str,
        *,
        limit: int,
        window_seconds: float,
    ) -> Decision:
        key = f"rl:{client_id}:{route}:sw"
        try:
            result = await self._evalsha(
                keys=[key],
                args=[limit, window_seconds, _KEY_TTL],
            )
            allowed, remaining, retry_ms, reset_ms = (int(x) for x in result)
            return Decision(
                allowed=bool(allowed),
                remaining=remaining,
                limit=limit,
                retry_after_seconds=retry_ms / 1000.0,
                reset_after_seconds=reset_ms / 1000.0,
            )
        except RedisError as exc:
            logger.error("Redis error in sliding window: %s – fail_mode=%s", exc, self._fail_mode)
            return _fail_decision(self._fail_mode)
