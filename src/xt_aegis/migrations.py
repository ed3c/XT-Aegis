"""Ordered, recorded schema migrations shared by every checkpoint backend.

A single `schema_version` string answers "which shape is this database in" but not "how did it get there",
and it cannot express *partial*: a process that dies between two `ALTER TABLE`s leaves a database that
claims one version and has another. An append-only ledger answers both, and makes the second run of a
migration a no-op by construction rather than by the DDL happening to be idempotent.

Migrations are forward-only. A down-migration is code that is written once, never exercised, and run for
the first time during an incident; the rollback path here is a verified restore (see `docs/BACKUP.md`).
A database stamped past the last known version is refused rather than opened, because the alternative is a
new column silently ignored by old code that then writes rows missing it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from xt_aegis.errors import CheckpointSchemaError

Dialect = Literal["sqlite", "postgres"]


@dataclass(frozen=True)
class Migration:
    """One numbered schema change, expressed per dialect because DDL is not portable."""

    version: int
    description: str
    sqlite: tuple[str, ...]
    postgres: tuple[str, ...]

    def statements(self, dialect: Dialect) -> tuple[str, ...]:
        return self.sqlite if dialect == "sqlite" else self.postgres


_BASELINE_SQLITE = (
    """
    CREATE TABLE IF NOT EXISTS metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runs (
        thread_id TEXT PRIMARY KEY,
        skill_name TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS steps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT NOT NULL,
        action_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL UNIQUE,
        step_number INTEGER NOT NULL,
        status TEXT NOT NULL,
        request_json TEXT NOT NULL,
        request_digest_version TEXT NOT NULL,
        request_digest TEXT NOT NULL,
        policy_digest TEXT NOT NULL,
        result_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(thread_id, step_number),
        FOREIGN KEY(thread_id) REFERENCES runs(thread_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS approvals (
        approval_id TEXT PRIMARY KEY,
        thread_id TEXT NOT NULL,
        action_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        actor_id TEXT,
        request_digest_version TEXT NOT NULL,
        request_digest TEXT NOT NULL,
        policy_digest TEXT NOT NULL,
        decision TEXT NOT NULL,
        reviewer TEXT,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        decided_at TEXT,
        consumed_at TEXT,
        UNIQUE(thread_id, action_id, idempotency_key),
        FOREIGN KEY(thread_id) REFERENCES runs(thread_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trace_id TEXT NOT NULL,
        thread_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_steps_thread ON steps(thread_id, step_number)",
    "CREATE INDEX IF NOT EXISTS idx_events_thread ON events(thread_id, id)",
)

_BASELINE_POSTGRES = (
    """
    CREATE TABLE IF NOT EXISTS metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runs (
        thread_id TEXT PRIMARY KEY,
        skill_name TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS steps (
        idempotency_key TEXT PRIMARY KEY,
        thread_id TEXT NOT NULL,
        action_id TEXT NOT NULL,
        step_number INTEGER NOT NULL,
        status TEXT NOT NULL,
        request_json TEXT NOT NULL,
        request_digest_version TEXT,
        request_digest TEXT,
        policy_digest TEXT,
        result_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS approvals (
        approval_id TEXT PRIMARY KEY,
        thread_id TEXT NOT NULL,
        action_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        actor_id TEXT,
        request_digest_version TEXT,
        request_digest TEXT,
        policy_digest TEXT,
        decision TEXT NOT NULL,
        reviewer TEXT,
        created_at TEXT NOT NULL,
        expires_at TEXT,
        decided_at TEXT,
        consumed_at TEXT,
        UNIQUE (thread_id, action_id, idempotency_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id BIGSERIAL PRIMARY KEY,
        trace_id TEXT NOT NULL,
        thread_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_steps_thread ON steps(thread_id, step_number)",
    "CREATE INDEX IF NOT EXISTS idx_events_thread ON events(thread_id, id)",
)

# `IF NOT EXISTS` on ADD COLUMN is PostgreSQL-only; SQLite gets its safety from the ledger, which is the
# point of having one. Existing rows default to 0 so an upgraded database and a fresh one are identical.
_STATE_VERSION_COLUMNS = tuple(
    f"ALTER TABLE {table} ADD COLUMN state_version INTEGER NOT NULL DEFAULT 0" for table in ("runs", "steps")
)

MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        description="baseline runs, steps, approvals, events",
        sqlite=_BASELINE_SQLITE,
        postgres=_BASELINE_POSTGRES,
    ),
    Migration(
        version=2,
        description="monotonic state_version on runs and steps",
        sqlite=_STATE_VERSION_COLUMNS,
        postgres=tuple(
            statement.replace("ADD COLUMN", "ADD COLUMN IF NOT EXISTS")
            for statement in _STATE_VERSION_COLUMNS
        ),
    ),
)

SCHEMA_VERSION = MIGRATIONS[-1].version

_LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
"""

_METADATA_DDL = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""


def _stamped_version(connection: Any) -> str | None:
    """The legacy single-row marker, which predates the ledger and is still written for old builds."""

    connection.execute(_METADATA_DDL)
    row = connection.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()
    return None if row is None else str(row[0])


def applied_versions(connection: Any) -> list[int]:
    """Every migration this database records as applied, in order."""

    connection.execute(_LEDGER_DDL)
    rows = connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    return [int(row[0]) for row in rows]


def migration_history(connection: Any) -> list[dict[str, Any]]:
    """The ledger as recorded, for operators answering "how did this database get here"."""

    connection.execute(_LEDGER_DDL)
    rows = connection.execute(
        "SELECT version, description, applied_at FROM schema_migrations ORDER BY version"
    ).fetchall()
    return [{"version": int(row[0]), "description": str(row[1]), "applied_at": str(row[2])} for row in rows]


def apply_migrations(connection: Any, *, dialect: Dialect) -> list[int]:
    """Bring one database up to `SCHEMA_VERSION`; return the versions applied by this call.

    Called on every open, so the common case is an empty return value.
    """

    placeholder = "?" if dialect == "sqlite" else "%s"

    # Two markers must both be checked. The ledger is the authority, but a database written before the
    # ledger existed only carries the single `metadata` row, and a database written by a *newer* build
    # carries both — refusing on either is what keeps an unknown schema from being written to.
    stamped = _stamped_version(connection)
    if stamped is not None and (not stamped.isdigit() or int(stamped) > SCHEMA_VERSION):
        raise CheckpointSchemaError(f"unsupported checkpoint schema version: {stamped}")

    already = set(applied_versions(connection))
    unknown = sorted(version for version in already if version > SCHEMA_VERSION)
    if unknown:
        raise CheckpointSchemaError(f"unsupported checkpoint schema version: {unknown[0]}")

    applied_now: list[int] = []
    for migration in MIGRATIONS:
        if migration.version in already:
            continue
        for statement in migration.statements(dialect):
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_migrations(version, description, applied_at) "
            f"VALUES ({placeholder}, {placeholder}, {placeholder})",
            (migration.version, migration.description, datetime.now(UTC).isoformat()),
        )
        applied_now.append(migration.version)

    # Kept in step so an older build, which reads only this row, refuses a database it cannot handle.
    connection.execute(
        f"INSERT INTO metadata(key, value) VALUES ('schema_version', {placeholder}) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    return applied_now
