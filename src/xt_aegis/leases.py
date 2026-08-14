"""Per-resource leases with monotonic fencing tokens.

A lease alone does not make a mutation safe. A worker whose lease expired while it was blocked will resume
believing it still holds the resource, and no amount of expiry checking on that worker's side can fix it.
The defence is the token: every takeover mints a strictly greater one, so the resource can reject an
operation carried by a superseded token no matter what the stale holder believes.

Expiry is always computed by the database. A caller's clock is never trusted, because the caller is exactly
the party whose clock may have drifted or been suspended.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class LeaseError(RuntimeError):
    """Base error for lease operations."""


class StaleFencingToken(LeaseError):
    """Raised when the caller's lease has been superseded by a later holder."""


@dataclass(frozen=True, slots=True)
class Lease:
    """A grant of one resource to one owner until a database-computed instant."""

    resource: str
    owner: str
    fencing_token: int
    expires_at_epoch: float

    def supersedes(self, other: Lease) -> bool:
        return self.resource == other.resource and self.fencing_token > other.fencing_token


class LeaseStore(Protocol):
    """Backend-agnostic lease operations; every implementation must behave identically."""

    def acquire(self, resource: str, owner: str, *, ttl_seconds: float) -> Lease | None:
        """Grant the resource, or return ``None`` when a live lease is held by someone else."""

    def renew(self, lease: Lease, *, ttl_seconds: float) -> Lease | None:
        """Extend an owned, unexpired lease without changing its token, or return ``None``."""

    def release(self, lease: Lease) -> bool:
        """Release a lease this exact token still holds."""

    def read(self, resource: str) -> Lease | None:
        """Return the current lease for a resource, expired or not."""

    def guard(self, lease: Lease) -> None:
        """Raise :class:`StaleFencingToken` when this lease is no longer the current one."""


def _guard(store: LeaseStore, lease: Lease) -> None:
    current = store.read(lease.resource)
    if current is None:
        raise StaleFencingToken(f"no lease exists for {lease.resource!r}; this one was released or expired")
    if current.fencing_token != lease.fencing_token or current.owner != lease.owner:
        raise StaleFencingToken(
            f"lease for {lease.resource!r} is held by {current.owner!r} with token "
            f"{current.fencing_token}; this caller carries token {lease.fencing_token}"
        )


class SqliteLeaseStore:
    """Single-node lease store. The database clock is this process's clock, which is stated, not hidden."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        # Autocommit plus an explicit BEGIN IMMEDIATE. Python's sqlite3 starts a transaction only before
        # DML, so a read-then-write acquire would otherwise run its SELECT outside the write lock and let
        # several callers each conclude the resource was free.
        connection = sqlite3.connect(self.database_path, timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
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
                CREATE TABLE IF NOT EXISTS resource_leases (
                    resource TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    expires_at_epoch REAL NOT NULL
                );
                """
            )

    @staticmethod
    def _row_to_lease(row: sqlite3.Row) -> Lease:
        return Lease(
            resource=row["resource"],
            owner=row["owner"],
            fencing_token=int(row["fencing_token"]),
            expires_at_epoch=float(row["expires_at_epoch"]),
        )

    def acquire(self, resource: str, owner: str, *, ttl_seconds: float) -> Lease | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT resource, owner, fencing_token, expires_at_epoch FROM resource_leases "
                "WHERE resource = ?",
                (resource,),
            ).fetchone()
            now = float(connection.execute("SELECT strftime('%s','now') + 0.0").fetchone()[0])
            if row is not None and float(row["expires_at_epoch"]) > now and row["owner"] != owner:
                return None
            token = int(row["fencing_token"]) + 1 if row is not None else 1
            expires = now + ttl_seconds
            connection.execute(
                """
                INSERT INTO resource_leases(resource, owner, fencing_token, expires_at_epoch)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(resource) DO UPDATE SET
                    owner = excluded.owner,
                    fencing_token = excluded.fencing_token,
                    expires_at_epoch = excluded.expires_at_epoch
                """,
                (resource, owner, token, expires),
            )
            return Lease(resource=resource, owner=owner, fencing_token=token, expires_at_epoch=expires)

    def renew(self, lease: Lease, *, ttl_seconds: float) -> Lease | None:
        with self._connection() as connection:
            now = float(connection.execute("SELECT strftime('%s','now') + 0.0").fetchone()[0])
            expires = now + ttl_seconds
            cursor = connection.execute(
                """
                UPDATE resource_leases
                SET expires_at_epoch = ?
                WHERE resource = ? AND owner = ? AND fencing_token = ? AND expires_at_epoch > ?
                """,
                (expires, lease.resource, lease.owner, lease.fencing_token, now),
            )
            if cursor.rowcount != 1:
                return None
            return Lease(
                resource=lease.resource,
                owner=lease.owner,
                fencing_token=lease.fencing_token,
                expires_at_epoch=expires,
            )

    def release(self, lease: Lease) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM resource_leases WHERE resource = ? AND owner = ? AND fencing_token = ?",
                (lease.resource, lease.owner, lease.fencing_token),
            )
            return cursor.rowcount == 1

    def read(self, resource: str) -> Lease | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT resource, owner, fencing_token, expires_at_epoch FROM resource_leases "
                "WHERE resource = ?",
                (resource,),
            ).fetchone()
        return None if row is None else self._row_to_lease(row)

    def guard(self, lease: Lease) -> None:
        _guard(self, lease)


class PostgresLeaseStore:
    """Multi-connection lease store using the server clock and row locks.

    ``psycopg`` is an optional extra. Importing this class does not require it; constructing one does.
    """

    def __init__(self, dsn: str) -> None:
        import psycopg  # local import: the driver is an optional extra

        self._psycopg = psycopg
        self.dsn = dsn
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        with self._psycopg.connect(self.dsn) as connection:
            yield connection

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS resource_leases (
                    resource TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    fencing_token BIGINT NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL
                )
                """
            )

    def acquire(self, resource: str, owner: str, *, ttl_seconds: float) -> Lease | None:
        with self._connection() as connection:
            # The insert is the lock: two concurrent acquirers serialize on the primary key, and the
            # DO UPDATE clause decides the winner with the server's own clock.
            row = connection.execute(
                """
                INSERT INTO resource_leases(resource, owner, fencing_token, expires_at)
                VALUES (%s, %s, 1, now() + make_interval(secs => %s))
                ON CONFLICT (resource) DO UPDATE SET
                    owner = EXCLUDED.owner,
                    fencing_token = resource_leases.fencing_token + 1,
                    expires_at = EXCLUDED.expires_at
                WHERE resource_leases.expires_at <= now() OR resource_leases.owner = EXCLUDED.owner
                RETURNING resource, owner, fencing_token, extract(epoch from expires_at)
                """,
                (resource, owner, ttl_seconds),
            ).fetchone()
            if row is None:
                return None
            return Lease(
                resource=row[0], owner=row[1], fencing_token=int(row[2]), expires_at_epoch=float(row[3])
            )

    def renew(self, lease: Lease, *, ttl_seconds: float) -> Lease | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                UPDATE resource_leases
                SET expires_at = now() + make_interval(secs => %s)
                WHERE resource = %s AND owner = %s AND fencing_token = %s AND expires_at > now()
                RETURNING resource, owner, fencing_token, extract(epoch from expires_at)
                """,
                (ttl_seconds, lease.resource, lease.owner, lease.fencing_token),
            ).fetchone()
            if row is None:
                return None
            return Lease(
                resource=row[0], owner=row[1], fencing_token=int(row[2]), expires_at_epoch=float(row[3])
            )

    def release(self, lease: Lease) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM resource_leases WHERE resource = %s AND owner = %s AND fencing_token = %s",
                (lease.resource, lease.owner, lease.fencing_token),
            )
            return bool(cursor.rowcount == 1)

    def read(self, resource: str) -> Lease | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT resource, owner, fencing_token, extract(epoch from expires_at) "
                "FROM resource_leases WHERE resource = %s",
                (resource,),
            ).fetchone()
        if row is None:
            return None
        return Lease(resource=row[0], owner=row[1], fencing_token=int(row[2]), expires_at_epoch=float(row[3]))

    def guard(self, lease: Lease) -> None:
        _guard(self, lease)
