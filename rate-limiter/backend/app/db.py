"""SQLAlchemy models and seed script for per-client plan tier storage."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},  # SQLite only
    echo=False,
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


class ClientRecord(Base):
    __tablename__ = "clients"

    api_key: str = Column(String, primary_key=True, index=True)
    plan: str = Column(String, default="free", nullable=False)
    name: str = Column(String, default="", nullable=False)
    created_at: datetime = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_client_plan(db: Session, api_key: str) -> str:
    """Return the plan tier for *api_key*; defaults to 'free' if unknown."""
    record = db.query(ClientRecord).filter(ClientRecord.api_key == api_key).first()
    return record.plan if record else "free"


# ─── Seed ─────────────────────────────────────────────────────────────────────

_SEED_CLIENTS = [
    {"api_key": "free-key-001", "plan": "free",       "name": "Free Demo Client"},
    {"api_key": "pro-key-001",  "plan": "pro",        "name": "Pro Demo Client"},
    {"api_key": "ent-key-001",  "plan": "enterprise", "name": "Enterprise Demo Client"},
]


def seed_db(db: Session) -> None:
    """Insert demo clients if they don't already exist."""
    for data in _SEED_CLIENTS:
        exists = db.query(ClientRecord).filter(ClientRecord.api_key == data["api_key"]).first()
        if not exists:
            db.add(ClientRecord(**data))
    db.commit()
    logger.info("Database seeded with %d demo clients", len(_SEED_CLIENTS))
