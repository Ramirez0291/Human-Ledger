"""数据库会话。

SQLite 需要两处显式设置，否则行为不符合预期：
- foreign_keys=ON：SQLite 默认不强制外键约束
- journal_mode=WAL：允许读写并发，避免导入截图时阻塞界面
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

_is_sqlite = settings.resolved_database_url.startswith("sqlite")

engine = create_engine(
    settings.resolved_database_url,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)


if _is_sqlite:

    @event.listens_for(Engine, "connect")
    def _sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ANN001, ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
