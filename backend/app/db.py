from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


def _build_db_url() -> str:
    user = settings.db_user
    password = settings.db_password
    host = settings.db_host
    port = settings.db_port
    name = settings.db_name
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4"


def _as_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


engine = create_engine(
    _build_db_url(),
    pool_pre_ping=True,
    pool_size=max(1, _as_int(settings.db_pool_size, 20)),
    max_overflow=max(0, _as_int(settings.db_pool_max_overflow, 40)),
    pool_timeout=max(1, _as_int(settings.db_pool_timeout_seconds, 15)),
    pool_recycle=max(30, _as_int(settings.db_pool_recycle_seconds, 1800)),
)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
