"""Verifiable backup and restore of the durable XT-Aegis state.

Copying the database file while a writer is active can capture a torn state, so the backup goes through
SQLite's online backup API, which is consistent under WAL and concurrent writers.

Restore verifies before it writes. A backup whose digest does not match, or whose schema version this build
does not support, is refused with nothing touched — a restore that half-succeeds is worse than one that
does not start, because the operator would then be recovering from an unknown state.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MANIFEST_NAME = "backup-manifest.json"
DATABASE_NAME = "checkpoints.db"
SUPPORTED_STATE_SCHEMA_VERSIONS: frozenset[str] = frozenset({"2"})

_COUNTED_TABLES = ("runs", "steps", "approvals", "events")


class BackupError(RuntimeError):
    """Raised when a backup cannot be created, verified, or restored."""


class BackupManifest(BaseModel):
    """Integrity and provenance of one backup. Restore reads this before it writes anything."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    state_schema_version: str = Field(min_length=1, max_length=16)
    database_name: str = Field(min_length=1, max_length=128)
    database_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    database_bytes: int = Field(ge=0)
    row_counts: dict[str, int] = Field(default_factory=dict)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_state_schema_version(connection: sqlite3.Connection) -> str:
    row = connection.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()
    if row is None:
        raise BackupError("the database records no state schema version")
    return str(row[0])


def _row_counts(connection: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in _COUNTED_TABLES:
        try:
            counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        except sqlite3.OperationalError:  # a table this build does not know about is simply not counted
            continue
    return counts


def create_backup(database_path: str | Path, destination: str | Path) -> BackupManifest:
    """Write a consistent copy of the database and its manifest into ``destination``.

    Uses the online backup API, so a writer holding the database open does not produce a torn copy.
    """

    source = Path(database_path).expanduser().resolve()
    if not source.is_file():
        raise BackupError(f"database not found: {source}")
    target_directory = Path(destination).expanduser().resolve()
    target_directory.mkdir(parents=True, exist_ok=True)
    target = target_directory / DATABASE_NAME

    live = sqlite3.connect(source, timeout=30.0)
    copy = sqlite3.connect(target)
    try:
        state_schema_version = _read_state_schema_version(live)
        live.backup(copy)
        copy.commit()
        counts = _row_counts(copy)
    finally:
        copy.close()
        live.close()

    manifest = BackupManifest(
        state_schema_version=state_schema_version,
        database_name=DATABASE_NAME,
        database_sha256=_sha256_file(target),
        database_bytes=target.stat().st_size,
        row_counts=counts,
    )
    (target_directory / MANIFEST_NAME).write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def read_manifest(backup_directory: str | Path) -> BackupManifest:
    """Load and validate a backup manifest."""

    path = Path(backup_directory).expanduser().resolve() / MANIFEST_NAME
    if not path.is_file():
        raise BackupError(f"backup manifest not found: {path}")
    try:
        return BackupManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise BackupError(f"backup manifest is unreadable: {exc}") from exc


def verify_backup(backup_directory: str | Path) -> BackupManifest:
    """Check the manifest, the digest, and the schema version. Raises rather than returning a verdict."""

    directory = Path(backup_directory).expanduser().resolve()
    manifest = read_manifest(directory)
    database = directory / manifest.database_name
    if not database.is_file():
        raise BackupError(f"backup database not found: {database}")
    observed = _sha256_file(database)
    if observed != manifest.database_sha256:
        raise BackupError(
            "backup digest mismatch: the file does not match its manifest and will not be restored"
        )
    if manifest.state_schema_version not in SUPPORTED_STATE_SCHEMA_VERSIONS:
        raise BackupError(
            f"backup state schema {manifest.state_schema_version} is not supported by this build "
            f"({', '.join(sorted(SUPPORTED_STATE_SCHEMA_VERSIONS))})"
        )
    return manifest


def restore_backup(
    backup_directory: str | Path,
    database_path: str | Path,
    *,
    overwrite: bool = False,
) -> BackupManifest:
    """Verify a backup completely, then place it. Nothing is written until every check has passed."""

    directory = Path(backup_directory).expanduser().resolve()
    manifest = verify_backup(directory)
    target = Path(database_path).expanduser().resolve()
    if target.exists() and not overwrite:
        raise BackupError(
            f"refusing to overwrite an existing database at {target}; pass overwrite=True to replace it"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(directory / manifest.database_name, target)
    # WAL and shared-memory siblings of the previous database would otherwise be interpreted against the
    # restored file and reintroduce state the backup does not contain.
    for suffix in ("-wal", "-shm"):
        sibling = target.with_name(target.name + suffix)
        if sibling.exists():
            sibling.unlink()
    return manifest
