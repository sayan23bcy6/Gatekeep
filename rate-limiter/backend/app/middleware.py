"""FastAPI middleware: identity resolution, rate limiting, response headers.

Flow per request:
1. Resolve client_id (X-API-Key or remote IP).
2. Look up plan tier from SQLite.
3. Apply token bucket limit via Redis.
4. Apply per-minute sliding window limit via Redis.
5. If both pass → allow and set X-RateLimit-* headers.
6. If either blocks → 429 with Retry-After and JSON body.
7. Record allowed / blocked in stats.
"""
from __future__ import annotations

import logging
import math
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal, get_client_plan
from .policies import get_policy
from .redis_limiter import SlidingWindowRedisLimiter, TokenBucketRedisLimiter
from . import stats

logger = logging.getLogger(__name__)

# Routes that bypass rate limiting
_EXEMPT_PREFIXES = ("/health", "/stream", "/admin", "/docs", "/openapi", "/redoc")


def _resolve_client(request: Request) -> str:
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return api_key
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    client = request.client
    return client.host if client else "unknown"


async def rate_limit_middleware(request: Request, call_next: Callable) -> Response:
    path = request.url.path

    # Skip rate limiting for exempt paths
    if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
        return await call_next(request)

    redis_client = request.app.state.redis
    tb_limiter: TokenBucketRedisLimiter = request.app.state.tb_limiter
    sw_limiter: SlidingWindowRedisLimiter = request.app.state.sw_limiter

    client_id = _resolve_client(request)

    # Fetch plan from DB
    db: Session = SessionLocal()
    try:
        tier = get_client_plan(db, client_id)
    finally:
        db.close()

    policy = get_policy(tier)

    # --- Token bucket check (burst + per-second rate) ---
    tb_decision = await tb_limiter.is_allowed(
        client_id,
        path,
        capacity=policy.capacity,
        refill_rate=policy.refill_rate,
    )

    if not tb_decision.allowed:
        await stats.record_blocked(redis_client, client_id)
        retry_after = math.ceil(tb_decision.retry_after_seconds)
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limited", "retry_after": tb_decision.retry_after_seconds},
            headers={
                "Retry-After": str(max(1, retry_after)),
                "X-RateLimit-Limit": str(tb_decision.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(math.ceil(tb_decision.reset_after_seconds)),
            },
        )

    # --- Sliding window check (per-minute quota) ---
    sw_decision = await sw_limiter.is_allowed(
        client_id,
        path,
        limit=policy.sw_limit,
        window_seconds=policy.sw_window_seconds,
    )

    if not sw_decision.allowed:
        await stats.record_blocked(redis_client, client_id)
        retry_after = math.ceil(sw_decision.retry_after_seconds)
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limited", "retry_after": sw_decision.retry_after_seconds},
            headers={
                "Retry-After": str(max(1, retry_after)),
                "X-RateLimit-Limit": str(sw_decision.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(math.ceil(sw_decision.reset_after_seconds)),
            },
        )

    # --- Allowed ---
    await stats.record_allowed(redis_client, client_id)
    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(tb_decision.limit)
    response.headers["X-RateLimit-Remaining"] = str(tb_decision.remaining)
    response.headers["X-RateLimit-Reset"] = str(math.ceil(tb_decision.reset_after_seconds))
    return response
