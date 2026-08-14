"""Durable controller state so a restart resumes a run or refuses it, never silently restarts it.

The store holds one record per run identifier. A resume compares the declared conditions of the new run
against the persisted ones; anything that differs makes the accumulated totals meaningless, so the run is
refused rather than continued under a budget that no longer describes the same work.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

STATE_SCHEMA_VERSION = "1.0"


class ControllerStateError(RuntimeError):
    """Raised when a persisted controller state cannot be read under the supported contract."""


class ControllerStateRecord(BaseModel):
    """What a restart is allowed to resume, and everything it must match to be allowed to."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(min_length=1, max_length=160)
    conditions_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    next_attempt_number: int = Field(ge=1)
    total_prompt_tokens: int = Field(ge=0)
    total_completion_tokens: int = Field(ge=0)
    usage_reported: bool = True
    repair_task: str | None = Field(default=None, max_length=131_072)
    in_flight_attempt: int | None = Field(default=None, ge=1)
    cycle_counts: dict[str, int] = Field(default_factory=dict)
    terminal_stop_reason: str | None = Field(default=None, max_length=64)


def conditions_digest(
    *,
    task: str,
    context: BaseModel,
    budgets: BaseModel,
    admission: BaseModel | None,
) -> str:
    """Digest everything a resumed run must still match.

    The task, the source and backend identity, the budgets, and the declared provider profile are all in
    scope: a change to any of them means the persisted totals describe different work.
    """

    payload = {
        "schema_version": STATE_SCHEMA_VERSION,
        "task": task,
        "context": context.model_dump(mode="json"),
        "budgets": budgets.model_dump(mode="json"),
        "admission": admission.model_dump(mode="json") if admission is not None else None,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class ControllerStateStore:
    """One SQLite table beside the existing checkpoint store; no existing table is changed."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS controller_runs (
                    run_id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    record_json TEXT NOT NULL
                );
                """
            )

    def load(self, run_id: str) -> ControllerStateRecord | None:
        """Return the persisted record, or ``None`` when this run has never been seen."""

        with self._connection() as connection:
            row = connection.execute(
                "SELECT schema_version, record_json FROM controller_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        if row["schema_version"] != STATE_SCHEMA_VERSION:
            raise ControllerStateError(
                f"persisted controller state schema {row['schema_version']} is not supported by "
                f"{STATE_SCHEMA_VERSION}"
            )
        try:
            return ControllerStateRecord.model_validate_json(row["record_json"])
        except ValueError as exc:
            raise ControllerStateError(f"persisted controller state is unreadable: {exc}") from exc

    def save(self, record: ControllerStateRecord) -> None:
        """Write the record for this run identifier, replacing any earlier one."""

        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO controller_runs(run_id, schema_version, record_json)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    schema_version = excluded.schema_version,
                    record_json = excluded.record_json
                """,
                (record.run_id, record.schema_version, record.model_dump_json()),
            )
