"""Abstract base for all rate limiter implementations."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Decision:
    """Result returned by every limiter implementation."""
    allowed: bool
    remaining: int
    limit: int
    retry_after_seconds: float = 0.0    # 0 when allowed
    reset_after_seconds: float = 0.0


class BaseLimiter(ABC):
    """Common interface that both pure-Python and Redis implementations satisfy."""

    @abstractmethod
    def is_allowed(
        self,
        client_id: str,
        route: str,
        *,
        limit: int,
        window_seconds: float,
        **kwargs,
    ) -> Decision:
        ...
