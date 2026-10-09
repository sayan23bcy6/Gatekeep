"""Per-client and aggregate statistics stored in Redis.

Counters are Redis HASHes with fields:
  rl:stats:{client_id}  →  { allowed, blocked, last_seen }
  rl:stats:__totals__   →  { allowed, blocked, redis_errors }

The SSE endpoint reads these atomically and emits JSON snapshots.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Dict

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from .config import settings

logger = logging.getLogger(__name__)

_STATS_PREFIX = "rl:stats:"
_TOTALS_KEY = "rl:stats:__totals__"
_CLIENT_KEY_PREFIX = "rl:stats:"


async def record_allowed(redis_client: aioredis.Redis, client_id: str) -> None:
    try:
        pipe = redis_client.pipeline()
        pipe.hincrby(f"{_CLIENT_KEY_PREFIX}{client_id}", "allowed", 1)
        pipe.hset(f"{_CLIENT_KEY_PREFIX}{client_id}", "last_seen", int(time.time()))
        pipe.hincrby(_TOTALS_KEY, "allowed", 1)
        pipe.expire(f"{_CLIENT_KEY_PREFIX}{client_id}", settings.stats_ttl)
        pipe.expire(_TOTALS_KEY, settings.stats_ttl)
        await pipe.execute()
    except RedisError as exc:
        logger.warning("Stats record_allowed failed: %s", exc)


async def record_blocked(redis_client: aioredis.Redis, client_id: str) -> None:
    try:
        pipe = redis_client.pipeline()
        pipe.hincrby(f"{_CLIENT_KEY_PREFIX}{client_id}", "blocked", 1)
        pipe.hset(f"{_CLIENT_KEY_PREFIX}{client_id}", "last_seen", int(time.time()))
        pipe.hincrby(_TOTALS_KEY, "blocked", 1)
        pipe.expire(f"{_CLIENT_KEY_PREFIX}{client_id}", settings.stats_ttl)
        pipe.expire(_TOTALS_KEY, settings.stats_ttl)
        await pipe.execute()
    except RedisError as exc:
        logger.warning("Stats record_blocked failed: %s", exc)


async def record_redis_error(redis_client: aioredis.Redis) -> None:
    """Best-effort; may itself fail if Redis is down."""
    try:
        await redis_client.hincrby(_TOTALS_KEY, "redis_errors", 1)
    except RedisError:
        pass


async def get_snapshot(redis_client: aioredis.Redis) -> Dict[str, Any]:
    """Return a dict suitable for JSON serialisation."""
    try:
        # Scan for all client stat keys
        client_keys = []
        async for key in redis_client.scan_iter(f"{_CLIENT_KEY_PREFIX}*"):
            key_str = key.decode() if isinstance(key, bytes) else key
            if key_str == _TOTALS_KEY:
                continue
            client_keys.append(key_str)

        pipe = redis_client.pipeline()
        pipe.hgetall(_TOTALS_KEY)
        for ck in client_keys:
            pipe.hgetall(ck)
        results = await pipe.execute()

        totals_raw = results[0] or {}
        totals = {
            k.decode() if isinstance(k, bytes) else k: int(v)
            for k, v in totals_raw.items()
        }

        clients = []
        for i, ck in enumerate(client_keys):
            raw = results[i + 1] or {}
            decoded = {
                k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
                for k, v in raw.items()
            }
            client_id = ck.replace(_CLIENT_KEY_PREFIX, "", 1)
            clients.append({
                "client_id": client_id,
                "allowed": int(decoded.get("allowed", 0)),
                "blocked": int(decoded.get("blocked", 0)),
                "last_seen": int(decoded.get("last_seen", 0)),
            })

        total_requests = totals.get("allowed", 0) + totals.get("blocked", 0)
        block_rate = (
            round(totals.get("blocked", 0) / total_requests * 100, 1)
            if total_requests > 0
            else 0.0
        )

        return {
            "totals": {
                "requests": total_requests,
                "allowed": totals.get("allowed", 0),
                "blocked": totals.get("blocked", 0),
                "redis_errors": totals.get("redis_errors", 0),
                "block_rate": block_rate,
            },
            "clients": clients,
            "ts": int(time.time()),
        }
    except RedisError as exc:
        logger.warning("Stats snapshot failed: %s", exc)
        return {"error": str(exc), "ts": int(time.time())}


async def stats_event_generator(
    redis_client: aioredis.Redis,
    interval: float = 1.0,
) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted strings with a JSON snapshot every *interval* seconds."""
    while True:
        snapshot = await get_snapshot(redis_client)
        data = json.dumps(snapshot)
        yield f"data: {data}\n\n"
        await asyncio.sleep(interval)
