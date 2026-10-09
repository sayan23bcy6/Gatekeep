"""Environment-based settings for the rate limiter service."""
from __future__ import annotations

import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    redis_url: str = "redis://localhost:6379/0"
    fail_mode: str = "open"          # "open" or "closed"
    database_url: str = "sqlite:///./rate_limiter.db"
    cors_origins: str = "http://localhost:5173,http://localhost:8080"
    redis_socket_timeout: float = 0.05   # 50 ms
    redis_socket_connect_timeout: float = 0.05
    stats_ttl: int = 3600            # seconds to keep stats keys in Redis
    log_level: str = "INFO"


settings = Settings()
