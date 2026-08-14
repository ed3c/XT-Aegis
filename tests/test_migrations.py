from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from xt_aegis.checkpoint import CheckpointStore
from xt_aegis.errors import CheckpointSchemaError
from xt_aegis.migrations import (
    MIGRATIONS,
    SCHEMA_VERSION,
    applied_versions,
    apply_migrations,
    migration_history,
)


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}


def _legacy_database(path: Path) -> None:
    """A database as the pre-ledger build left it: baseline tables, one metadata row, no ledger."""

    with sqlite3.connect(path) as connection:
        for statement in MIGRATIONS[0].sqlite:
            connection.execute(statement)
        connection.execute("INSERT INTO metadata(key, value) VALUES ('schema_version', '2')")
        connection.execute(
            "INSERT INTO runs(thread_id, skill_name, status, created_at, updated_at) "
            "VALUES ('thread.legacy', 'safe_refactor', 'succeeded', 'then', 'then')"
        )


def test_a_fresh_database_records_every_migration_in_order(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path / "state" / "checkpoints.db")

    history = store.migration_history()

    assert [entry["version"] for entry in history] == [m.version for m in MIGRATIONS]
    assert [entry["description"] for entry in history] == [m.description for m in MIGRATIONS]
    assert all(entry["applied_at"] for entry in history)


def test_applying_twice_changes_nothing(tmp_path: Path) -> None:
    database_path = tmp_path / "twice.db"
    with sqlite3.connect(database_path) as connection:
        first = apply_migrations(connection, dialect="sqlite")
        second = apply_migrations(connection, dialect="sqlite")

        assert first == [m.version for m in MIGRATIONS]
        assert second == []
        assert applied_versions(connection) == first


def test_a_database_stamped_past_the_last_known_version_is_refused(tmp_path: Path) -> None:
    """Opening it would mean writing rows an unknown schema expects to look different."""

    database_path = tmp_path / "future.db"
    with sqlite3.connect(database_path) as connection:
        apply_migrations(connection, dialect="sqlite")
        connection.execute(
            "INSERT INTO schema_migrations(version, description, applied_at) VALUES (?, 'from the future', 'later')",
            (SCHEMA_VERSION + 1,),
        )
        connection.execute("UPDATE metadata SET value = ? WHERE key = 'schema_version'", ("1",))

    with pytest.raises(CheckpointSchemaError, match=str(SCHEMA_VERSION + 1)):
        CheckpointStore(database_path)


def test_a_legacy_database_is_adopted_rather_than_refused(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.db"
    _legacy_database(database_path)

    store = CheckpointStore(database_path)

    assert [entry["version"] for entry in store.migration_history()] == [m.version for m in MIGRATIONS]
    state = store.run_state("thread.legacy")
    assert state is not None
    assert state.status == "succeeded"
    assert state.state_version == 0


def test_an_upgraded_database_reaches_the_same_schema_as_a_fresh_one(tmp_path: Path) -> None:
    legacy_path = tmp_path / "legacy.db"
    _legacy_database(legacy_path)
    CheckpointStore(legacy_path)
    CheckpointStore(tmp_path / "fresh.db")

    with sqlite3.connect(legacy_path) as upgraded, sqlite3.connect(tmp_path / "fresh.db") as fresh:
        for table in ("runs", "steps", "approvals", "events", "schema_migrations", "metadata"):
            assert _columns(upgraded, table) == _columns(fresh, table), table
        assert "state_version" in _columns(upgraded, "runs")
        assert [entry["version"] for entry in migration_history(upgraded)] == [
            entry["version"] for entry in migration_history(fresh)
        ]


def test_the_metadata_marker_tracks_the_ledger(tmp_path: Path) -> None:
    """An older build reads only this row, so it has to stay current or that build will not fail closed."""

    database_path = tmp_path / "marker.db"
    CheckpointStore(database_path)

    with sqlite3.connect(database_path) as connection:
        row = connection.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()

    assert row is not None
    assert row[0] == str(SCHEMA_VERSION)
