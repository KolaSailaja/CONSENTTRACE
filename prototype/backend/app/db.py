from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

DATABASE_URL = settings.database_url
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name != "postgresql":
        return

    migration_id = "001_align_investigation_scopes"
    migration_path = Path(__file__).resolve().parents[1] / "sql" / "migrations" / f"{migration_id}.sql"
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS consenttrace_schema_migrations ("
            "migration_id VARCHAR(128) PRIMARY KEY, "
            "applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
        ))
        already_applied = connection.execute(
            text("SELECT 1 FROM consenttrace_schema_migrations WHERE migration_id = :migration_id"),
            {"migration_id": migration_id},
        ).first()
        if already_applied is None:
            connection.exec_driver_sql(migration_path.read_text(encoding="utf-8"))
            connection.execute(
                text("INSERT INTO consenttrace_schema_migrations (migration_id) VALUES (:migration_id)"),
                {"migration_id": migration_id},
            )


def database_is_reachable() -> tuple[bool, str | None]:
    try:
        with engine.connect() as conn:
            if DATABASE_URL.startswith("sqlite"):
                conn.execute(text("SELECT 1"))
            else:
                conn.execute(text("SELECT 1"))
        return True, None
    except Exception as exc:  # pragma: no cover - runtime dependency path
        return False, str(exc)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
