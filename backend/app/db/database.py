"""SQLite engine and session factory."""

from __future__ import annotations

import threading
from collections.abc import Iterator

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import get_settings

_engine = None
_engine_lock = threading.Lock()
_id_lock = threading.Lock()


def get_engine():
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is None:
            settings = get_settings()
            settings.ensure_dirs()
            connect_args = {}
            if settings.database_url.startswith("sqlite"):
                connect_args["check_same_thread"] = False
            _engine = create_engine(settings.database_url, connect_args=connect_args)
        return _engine


def reset_engine() -> None:
    """Test helper. Drops the cached engine so a temp database can be used."""
    global _engine
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None


def init_db() -> None:
    from app import models  # noqa: F401

    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    _ensure_sqlite_columns(engine)


def _ensure_sqlite_columns(engine) -> None:
    """Add newly introduced columns on existing SQLite databases."""
    url = str(engine.url)
    if not url.startswith("sqlite"):
        return
    statements = (
        ("tests", "selected_finger", "ALTER TABLE tests ADD COLUMN selected_finger VARCHAR DEFAULT 'ring'"),
    )
    with engine.begin() as connection:
        for table, column, ddl in statements:
            rows = connection.execute(text(f"PRAGMA table_info({table})")).fetchall()
            existing = {str(row[1]) for row in rows}
            if column not in existing:
                connection.execute(text(ddl))


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def session_scope() -> Session:
    return Session(get_engine())


def allocate_id(session: Session, prefix: str, model: type[SQLModel]) -> str:
    with _id_lock:
        rows = session.exec(select(model.id)).all()  # type: ignore[attr-defined]
        highest = 0
        token = f"{prefix}-"
        for raw in rows:
            if isinstance(raw, tuple):
                raw = raw[0]
            if isinstance(raw, str) and raw.startswith(token):
                suffix = raw[len(token) :]
                if suffix.isdigit():
                    highest = max(highest, int(suffix))
        return f"{prefix}-{highest + 1:03d}"


def ping_database() -> bool:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
