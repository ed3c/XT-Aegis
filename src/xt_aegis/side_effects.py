"""Protected external side effects: dispatch once, and never retry what might already have happened.

Local idempotency stops XT-Aegis from executing a request twice. It says nothing about the service on the
other side of a call. When an acknowledgement is lost to a timeout, a crash, or a failover, the caller
cannot tell "it did not happen" from "it happened and I did not hear" — and retrying is safe only in the
first case.

So ambiguity is a state here, not an error to swallow. `unknown` is reconciled when the adapter can look
the operation up, and stays `unknown` when it cannot, because a weaker guarantee stated plainly is worth
more than a stronger one implied.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, Field

from xt_aegis.redaction import redact_text

BoundedReceipt = Annotated[str, Field(max_length=4_096)]
BoundedReason = Annotated[str, Field(max_length=512)]

RECEIPT_LIMIT = 4_096


class EffectState(StrEnum):
    """Terminal-ish states of one protected operation."""

    PENDING = "pending"
    COMMITTED = "committed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class EffectIdentity(BaseModel):
    """Everything that makes one protected operation distinct from another."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: str = Field(min_length=1, max_length=160)
    tool: str = Field(min_length=1, max_length=64)
    resource: str = Field(min_length=1, max_length=512)
    policy_version: str = Field(min_length=1, max_length=32)
    logical_operation_id: str = Field(min_length=1, max_length=160)
    argument_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    def idempotency_key(self) -> str:
        """Deterministic key. Changing any component makes this a different operation, by construction."""

        payload = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(payload.encode()).hexdigest()


def argument_digest(arguments: object) -> str:
    """Canonical digest of the call arguments an operation is bound to."""

    payload = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


class EffectOutcome(BaseModel):
    """What an adapter reports about one dispatch or reconciliation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: EffectState
    provider_reference: str | None = Field(default=None, max_length=256)
    receipt: BoundedReceipt = ""
    reason: BoundedReason = ""


class EffectRecord(BaseModel):
    """The durable record. Intent is written before dispatch, so a crash is recoverable, not invisible."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    identity: EffectIdentity
    state: EffectState
    attempts: int = Field(ge=0)
    provider_reference: str | None = Field(default=None, max_length=256)
    receipt: BoundedReceipt = ""
    reason: BoundedReason = ""
    created_at_epoch: float
    updated_at_epoch: float

    @property
    def needs_reconciliation(self) -> bool:
        return self.state in {EffectState.UNKNOWN, EffectState.PENDING}


class AmbiguousEffect(RuntimeError):
    """Raised when an operation may or may not have happened and cannot be resolved."""

    def __init__(self, record: EffectRecord) -> None:
        super().__init__(
            f"operation {record.identity.logical_operation_id!r} on {record.identity.resource!r} is "
            f"{record.state.value}: {record.reason or 'no adapter reconciliation is available'}"
        )
        self.record = record


class EffectAdapter(Protocol):
    """A provider-neutral protected call.

    `supports_idempotency_key` and `supports_reconciliation` are declared rather than probed, because an
    adapter that guesses about its provider's guarantees is worse than one that admits it has none.
    """

    supports_idempotency_key: bool
    supports_reconciliation: bool

    def dispatch(self, identity: EffectIdentity, *, idempotency_key: str | None) -> EffectOutcome:
        """Perform the external call once."""

    def reconcile(self, identity: EffectIdentity, *, idempotency_key: str) -> EffectOutcome | None:
        """Look up whether the operation already happened, or return ``None`` when it cannot be known."""


def _bounded_receipt(value: str) -> str:
    return redact_text(value, limit=RECEIPT_LIMIT)[:RECEIPT_LIMIT]


class EffectStore:
    """One SQLite table recording protected operations; it shares nothing with the checkpoint store."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        else:
            connection.execute("COMMIT")
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS protected_effects (
                    idempotency_key TEXT PRIMARY KEY,
                    record_json TEXT NOT NULL
                );
                """
            )

    def read(self, idempotency_key: str) -> EffectRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT record_json FROM protected_effects WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return None if row is None else EffectRecord.model_validate_json(row["record_json"])

    def write(self, record: EffectRecord) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO protected_effects(idempotency_key, record_json)
                VALUES (?, ?)
                ON CONFLICT(idempotency_key) DO UPDATE SET record_json = excluded.record_json
                """,
                (record.idempotency_key, record.model_dump_json()),
            )


class ProtectedEffectRunner:
    """Dispatch a protected operation at most once, and represent ambiguity instead of retrying it."""

    def __init__(self, store: EffectStore, *, clock: TimeSource | None = None) -> None:
        self.store = store
        self._clock = clock or time.time

    def execute(self, identity: EffectIdentity, adapter: EffectAdapter) -> EffectRecord:
        """Return the record for this operation, dispatching only when that is provably safe."""

        key = identity.idempotency_key()
        existing = self.store.read(key)

        if existing is not None and existing.state is EffectState.COMMITTED:
            return existing
        if existing is not None and existing.needs_reconciliation:
            resolved = self._reconcile(existing, adapter)
            if resolved.state is EffectState.UNKNOWN:
                raise AmbiguousEffect(resolved)
            if resolved.state is EffectState.COMMITTED:
                return resolved
            existing = resolved

        now = self._clock()
        attempts = existing.attempts if existing is not None else 0
        pending = EffectRecord(
            idempotency_key=key,
            identity=identity,
            state=EffectState.PENDING,
            attempts=attempts + 1,
            created_at_epoch=existing.created_at_epoch if existing is not None else now,
            updated_at_epoch=now,
            reason="intent persisted before dispatch",
        )
        # Written before the call, so a crash here leaves an ambiguous record rather than no record.
        self.store.write(pending)

        try:
            outcome = adapter.dispatch(
                identity, idempotency_key=key if adapter.supports_idempotency_key else None
            )
        except TimeoutError as exc:
            return self._store_outcome(
                pending,
                EffectOutcome(
                    state=EffectState.UNKNOWN,
                    reason=f"dispatch timed out; the provider may have committed: {exc}",
                ),
            )
        except Exception as exc:  # an adapter fault is ambiguous unless the adapter says otherwise
            return self._store_outcome(
                pending,
                EffectOutcome(
                    state=EffectState.UNKNOWN,
                    reason=f"dispatch raised {type(exc).__name__}; the outcome is unknown",
                ),
            )
        return self._store_outcome(pending, outcome)

    def reconcile(self, identity: EffectIdentity, adapter: EffectAdapter) -> EffectRecord | None:
        """Resolve a stored ambiguous record without dispatching anything."""

        record = self.store.read(identity.idempotency_key())
        if record is None:
            return None
        if not record.needs_reconciliation:
            return record
        return self._reconcile(record, adapter)

    def _reconcile(self, record: EffectRecord, adapter: EffectAdapter) -> EffectRecord:
        if not adapter.supports_reconciliation:
            resolved = record.model_copy(
                update={
                    "state": EffectState.UNKNOWN,
                    "reason": "the adapter cannot look this operation up; it is neither safe to retry "
                    "nor known to have happened",
                    "updated_at_epoch": self._clock(),
                }
            )
            self.store.write(resolved)
            return resolved
        outcome = adapter.reconcile(record.identity, idempotency_key=record.idempotency_key)
        if outcome is None:
            resolved = record.model_copy(
                update={
                    "state": EffectState.UNKNOWN,
                    "reason": "reconciliation could not determine whether the operation happened",
                    "updated_at_epoch": self._clock(),
                }
            )
            self.store.write(resolved)
            return resolved
        return self._store_outcome(record, outcome)

    def _store_outcome(self, record: EffectRecord, outcome: EffectOutcome) -> EffectRecord:
        updated = record.model_copy(
            update={
                "state": outcome.state,
                "provider_reference": outcome.provider_reference,
                "receipt": _bounded_receipt(outcome.receipt),
                "reason": outcome.reason[:512],
                "updated_at_epoch": self._clock(),
            }
        )
        self.store.write(updated)
        return updated


class TimeSource(Protocol):
    def __call__(self) -> float: ...
