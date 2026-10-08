from __future__ import annotations

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

metadata = MetaData()
J = JSON().with_variant(JSONB(), "postgresql")

projects = Table(
    "projects",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("name", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    # Active schema (matches the live index) and a pending one awaiting reindex.
    Column("schema", J),
    Column("pending_schema", J),
    Column("schema_version", Integer, nullable=False, server_default="0"),
    Column("index_version", Integer, nullable=False, server_default="0"),
    # Bumped whenever searchable data changes; part of the search cache key.
    Column("data_version", Integer, nullable=False, server_default="0"),
    # Browser origins allowed to use the search key, e.g. ["https://shop.example.com", "https://*.example.com"].
    Column("allowed_origins", J, nullable=False, server_default="[]"),
)

api_keys = Table(
    "api_keys",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("project_id", String(40), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("kind", String(16), nullable=False),  # admin | search
    Column("key_hash", String(64), nullable=False, unique=True),
    Column("key_prefix", String(24), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

jobs = Table(
    "jobs",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("project_id", String(40), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("kind", String(16), nullable=False),  # upsert | import | delete | reindex
    Column("status", String(32), nullable=False, server_default="queued", index=True),
    Column("params", J),
    Column("total", Integer),
    Column("processed", Integer, nullable=False, server_default="0"),
    Column("succeeded", Integer, nullable=False, server_default="0"),
    Column("failed", Integer, nullable=False, server_default="0"),
    Column("errors", J),
    Column("message", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
)

job_payloads = Table(
    "job_payloads",
    metadata,
    Column("job_id", String(40), ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True),
    Column("format", String(16), nullable=False),  # json | jsonl | csv
    Column("data", LargeBinary, nullable=False),
)


# Per-project value dictionary for query understanding (zlib-compressed JSON), rebuilt after ingest.
project_dicts = Table(
    "project_dicts",
    metadata,
    Column("project_id", String(40), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("data_version", Integer, nullable=False),
    Column("built_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("payload", LargeBinary, nullable=False),
)


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_size=10, max_overflow=10, pool_pre_ping=True)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        # Serialise concurrent create_all calls from multiple uvicorn workers.
        await conn.exec_driver_sql("SELECT pg_advisory_xact_lock(4242)")
        await conn.run_sync(metadata.create_all)
        # Columns added after a table first existed (create_all doesn't alter tables).
        await conn.exec_driver_sql(
            "ALTER TABLE projects ADD COLUMN IF NOT EXISTS allowed_origins JSONB NOT NULL DEFAULT '[]'::jsonb")
