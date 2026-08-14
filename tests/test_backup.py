from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

import pytest

from xt_aegis.backup import (
    DATABASE_NAME,
    MANIFEST_NAME,
    BackupError,
    create_backup,
    read_manifest,
    restore_backup,
    verify_backup,
)
from xt_aegis.checkpoint import CheckpointStore
from xt_aegis.errors import IdempotencyConflictError
from xt_aegis.events import EventRecorder
from xt_aegis.identity import RequestIdentity
from xt_aegis.models import ActionRequest, FileWriteAction, Provenance


def _request(*, key: str = "backup-key-0001", content: str = "VALUE = 1\n") -> ActionRequest:
    return ActionRequest(
        thread_id="thread.backup.001",
        action_id="backup.action",
        idempotency_key=key,
        actor_id="user:test",
        provenance=Provenance.AGENT_PROPOSAL,
        action=FileWriteAction(relative_path="app.py", content=content),
    )


def _populate(store: CheckpointStore, compiled_skill: object) -> tuple[ActionRequest, RequestIdentity]:
    request = _request()
    identity = RequestIdentity.from_request(request, skill=compiled_skill)  # type: ignore[arg-type]
    store.start_run(request.thread_id, "safe_refactor")
    store.prepare_step(request, identity)
    EventRecorder(store).emit(
        trace_id="trace-1",
        thread_id=request.thread_id,
        event_type="action_received",
        payload={"action_id": request.action_id},
    )
    return request, identity


@pytest.fixture
def populated(tmp_path: Path, compiled_skill) -> tuple[Path, ActionRequest, RequestIdentity]:  # type: ignore[no-untyped-def]
    database = tmp_path / "state" / "checkpoints.db"
    store = CheckpointStore(database)
    request, identity = _populate(store, compiled_skill)
    return database, request, identity


def test_a_backup_records_a_manifest_with_digest_and_row_counts(
    populated: tuple[Path, ActionRequest, RequestIdentity], tmp_path: Path
) -> None:
    database, _, _ = populated

    manifest = create_backup(database, tmp_path / "backup")

    assert manifest.state_schema_version == "2"
    assert manifest.database_bytes > 0
    assert manifest.row_counts["runs"] == 1
    assert manifest.row_counts["steps"] == 1
    assert manifest.row_counts["events"] == 1
    assert (tmp_path / "backup" / MANIFEST_NAME).is_file()
    assert (tmp_path / "backup" / DATABASE_NAME).is_file()


def test_a_backup_taken_while_a_writer_is_active_is_readable_and_complete(
    tmp_path: Path, compiled_skill
) -> None:  # type: ignore[no-untyped-def]
    database = tmp_path / "state" / "checkpoints.db"
    store = CheckpointStore(database)
    _populate(store, compiled_skill)
    recorder = EventRecorder(store)
    stop = threading.Event()

    def keep_writing() -> None:
        index = 0
        while not stop.is_set():
            recorder.emit(
                trace_id="trace-writer",
                thread_id="thread.backup.001",
                event_type="benchmark.noise",
                payload={"index": index},
            )
            index += 1

    writer = threading.Thread(target=keep_writing, daemon=True)
    writer.start()
    try:
        manifest = create_backup(database, tmp_path / "backup")
    finally:
        stop.set()
        writer.join(timeout=10)

    verify_backup(tmp_path / "backup")
    with sqlite3.connect(tmp_path / "backup" / DATABASE_NAME) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == manifest.row_counts["events"]
        )


def test_restore_reproduces_every_table(
    populated: tuple[Path, ActionRequest, RequestIdentity], tmp_path: Path
) -> None:
    database, _, _ = populated
    manifest = create_backup(database, tmp_path / "backup")

    restored_path = tmp_path / "restored" / "checkpoints.db"
    restore_backup(tmp_path / "backup", restored_path)

    with sqlite3.connect(restored_path) as connection:
        for table, expected in manifest.row_counts.items():
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == expected


def test_idempotency_semantics_survive_the_round_trip(
    populated: tuple[Path, ActionRequest, RequestIdentity], tmp_path: Path, compiled_skill
) -> None:  # type: ignore[no-untyped-def]
    """A restored database must still refuse a changed payload under a used idempotency key."""

    database, request, _ = populated
    create_backup(database, tmp_path / "backup")
    restored_path = tmp_path / "restored" / "checkpoints.db"
    restore_backup(tmp_path / "backup", restored_path)

    restored = CheckpointStore(restored_path)
    substituted = request.model_copy(
        update={"action": FileWriteAction(relative_path="app.py", content="VALUE = 999\n")}
    )
    substituted_identity = RequestIdentity.from_request(substituted, skill=compiled_skill)

    with pytest.raises(IdempotencyConflictError):
        restored.prepare_step(substituted, substituted_identity)


def test_a_tampered_backup_is_refused_before_anything_is_written(
    populated: tuple[Path, ActionRequest, RequestIdentity], tmp_path: Path
) -> None:
    database, _, _ = populated
    create_backup(database, tmp_path / "backup")
    with (tmp_path / "backup" / DATABASE_NAME).open("ab") as handle:
        handle.write(b"tampered")
    restored_path = tmp_path / "restored" / "checkpoints.db"

    with pytest.raises(BackupError, match="digest mismatch"):
        restore_backup(tmp_path / "backup", restored_path)

    assert not restored_path.exists()


def test_an_unsupported_state_schema_version_is_refused(
    populated: tuple[Path, ActionRequest, RequestIdentity], tmp_path: Path
) -> None:
    database, _, _ = populated
    create_backup(database, tmp_path / "backup")
    manifest_path = tmp_path / "backup" / MANIFEST_NAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["state_schema_version"] = "99"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BackupError, match="is not supported by this build"):
        verify_backup(tmp_path / "backup")


def test_restore_does_not_clobber_an_existing_database_by_default(
    populated: tuple[Path, ActionRequest, RequestIdentity], tmp_path: Path
) -> None:
    database, _, _ = populated
    create_backup(database, tmp_path / "backup")
    occupied = tmp_path / "restored" / "checkpoints.db"
    occupied.parent.mkdir(parents=True)
    occupied.write_bytes(b"existing state")

    with pytest.raises(BackupError, match="refusing to overwrite"):
        restore_backup(tmp_path / "backup", occupied)
    assert occupied.read_bytes() == b"existing state"

    restore_backup(tmp_path / "backup", occupied, overwrite=True)
    assert occupied.read_bytes() != b"existing state"


def test_restore_removes_stale_wal_siblings(
    populated: tuple[Path, ActionRequest, RequestIdentity], tmp_path: Path
) -> None:
    """A leftover WAL would be interpreted against the restored file and reintroduce absent state."""

    database, _, _ = populated
    create_backup(database, tmp_path / "backup")
    restored_path = tmp_path / "restored" / "checkpoints.db"
    restored_path.parent.mkdir(parents=True)
    restored_path.write_bytes(b"old")
    stale = restored_path.with_name(restored_path.name + "-wal")
    stale.write_bytes(b"stale wal")

    restore_backup(tmp_path / "backup", restored_path, overwrite=True)

    assert not stale.exists()


def test_a_missing_manifest_or_database_is_refused(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(BackupError, match="manifest not found"):
        read_manifest(empty)

    (tmp_path / "partial").mkdir()
    (tmp_path / "partial" / MANIFEST_NAME).write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "state_schema_version": "2",
                "database_name": DATABASE_NAME,
                "database_sha256": "a" * 64,
                "database_bytes": 1,
                "row_counts": {},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(BackupError, match="database not found"):
        verify_backup(tmp_path / "partial")


def test_backing_up_a_missing_database_is_refused(tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="database not found"):
        create_backup(tmp_path / "absent.db", tmp_path / "backup")


def test_an_unreadable_manifest_is_refused(tmp_path: Path) -> None:
    directory = tmp_path / "broken"
    directory.mkdir()
    (directory / MANIFEST_NAME).write_text("{not json}", encoding="utf-8")

    with pytest.raises(BackupError, match="unreadable"):
        read_manifest(directory)
