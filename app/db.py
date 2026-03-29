from __future__ import annotations

from collections.abc import Generator
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


def _build_connect_args(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}

    parsed = urlparse(database_url)
    is_supabase_transaction_pooler = parsed.port == 6543
    if is_supabase_transaction_pooler:
        # Supabase documents that transaction mode does not support prepared statements.
        # For psycopg, disable them with prepare_threshold=None.
        return {"prepare_threshold": None}

    return {}


connect_args = _build_connect_args(settings.database_url)
engine = create_engine(
    settings.database_url,
    future=True,
    echo=False,
    connect_args=connect_args,
    pool_pre_ping=not settings.database_url.startswith("sqlite"),
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
