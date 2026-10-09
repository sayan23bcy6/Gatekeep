"""FastAPI application – startup, shutdown, and route wiring."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import create_tables, seed_db, SessionLocal
from .middleware import rate_limit_middleware
from .redis_limiter import TokenBucketRedisLimiter, SlidingWindowRedisLimiter
from .routes.api import router as api_router
from .routes.admin import router as admin_router
from .routes.stream import router as stream_router

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_LUA_DIR = Path(__file__).parent / "lua"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────
    logger.info("Starting up – connecting to Redis at %s", settings.redis_url)
    redis_client = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=False,
        socket_timeout=settings.redis_socket_timeout,
        socket_connect_timeout=settings.redis_socket_connect_timeout,
    )
    app.state.redis = redis_client
    app.state.tb_limiter = TokenBucketRedisLimiter(
        redis_client,
        lua_script=(_LUA_DIR / "token_bucket.lua").read_text(encoding="utf-8"),
        fail_mode=settings.fail_mode,
    )
    app.state.sw_limiter = SlidingWindowRedisLimiter(
        redis_client,
        lua_script=(_LUA_DIR / "sliding_window.lua").read_text(encoding="utf-8"),
        fail_mode=settings.fail_mode,
    )

    # Pre-load Lua scripts into Redis
    try:
        await app.state.tb_limiter._ensure_sha()
        await app.state.sw_limiter._ensure_sha()
        logger.info("Lua scripts loaded into Redis")
    except Exception as exc:
        logger.warning("Could not pre-load Lua scripts (Redis may be unavailable): %s", exc)

    # ── Database ─────────────────────────────────────────────────────────
    create_tables()
    db = SessionLocal()
    try:
        seed_db(db)
    finally:
        db.close()

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────
    logger.info("Shutting down – closing Redis connection")
    await redis_client.aclose()


app = FastAPI(
    title="Distributed Rate Limiter",
    version="1.0.0",
    description="Multi-instance rate limiter backed by Redis with live dashboard.",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset", "Retry-After"],
)

# ── Rate-limit middleware ────────────────────────────────────────────────────
app.middleware("http")(rate_limit_middleware)

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(api_router)
app.include_router(admin_router)
app.include_router(stream_router)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
