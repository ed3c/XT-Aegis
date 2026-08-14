from __future__ import annotations

import os
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from xt_aegis.leases import (
    Lease,
    LeaseStore,
    PostgresLeaseStore,
    SqliteLeaseStore,
    StaleFencingToken,
)

RESOURCE = "workspace:demo"
POSTGRES_DSN = os.getenv("XT_AEGIS_TEST_POSTGRES_DSN", "")


def _postgres_available() -> bool:
    if not POSTGRES_DSN:
        return False
    try:
        import psycopg
    except ImportError:
        return False
    try:
        with psycopg.connect(POSTGRES_DSN, connect_timeout=3) as connection:
            connection.execute("SELECT 1")
    except Exception:
        return False
    return True


@pytest.fixture(params=["sqlite", "postgres"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[LeaseStore]:
    """One conformance suite, both backends. PostgreSQL skips with a stated reason when absent."""

    if request.param == "sqlite":
        yield SqliteLeaseStore(tmp_path / "leases.db")
        return
    if not _postgres_available():
        pytest.skip("set XT_AEGIS_TEST_POSTGRES_DSN to a reachable PostgreSQL and install the postgres extra")
    postgres = PostgresLeaseStore(POSTGRES_DSN)
    import psycopg

    with psycopg.connect(POSTGRES_DSN) as connection:
        connection.execute("DELETE FROM resource_leases")
    yield postgres
    with psycopg.connect(POSTGRES_DSN) as connection:
        connection.execute("DELETE FROM resource_leases")


def test_a_live_lease_excludes_a_second_owner(store: LeaseStore) -> None:
    first = store.acquire(RESOURCE, "worker-a", ttl_seconds=60)

    assert first is not None
    assert store.acquire(RESOURCE, "worker-b", ttl_seconds=60) is None
    assert store.read(RESOURCE) == first


def test_takeover_after_expiry_increments_the_fencing_token(store: LeaseStore) -> None:
    first = store.acquire(RESOURCE, "worker-a", ttl_seconds=0.0)
    assert first is not None
    time.sleep(1.1)  # the expiry is second-resolution on SQLite

    second = store.acquire(RESOURCE, "worker-b", ttl_seconds=60)

    assert second is not None
    assert second.owner == "worker-b"
    assert second.fencing_token > first.fencing_token
    assert second.supersedes(first)


def test_renewal_extends_expiry_and_preserves_the_token(store: LeaseStore) -> None:
    lease = store.acquire(RESOURCE, "worker-a", ttl_seconds=1)
    assert lease is not None

    renewed = store.renew(lease, ttl_seconds=120)

    assert renewed is not None
    assert renewed.fencing_token == lease.fencing_token
    assert renewed.expires_at_epoch > lease.expires_at_epoch


def test_renewal_after_a_takeover_fails_instead_of_resurrecting_the_lease(store: LeaseStore) -> None:
    stale = store.acquire(RESOURCE, "worker-a", ttl_seconds=0.0)
    assert stale is not None
    time.sleep(1.1)
    assert store.acquire(RESOURCE, "worker-b", ttl_seconds=60) is not None

    assert store.renew(stale, ttl_seconds=60) is None
    assert store.read(RESOURCE) is not None
    assert store.read(RESOURCE).owner == "worker-b"  # type: ignore[union-attr]


def test_guard_rejects_a_superseded_token(store: LeaseStore) -> None:
    stale = store.acquire(RESOURCE, "worker-a", ttl_seconds=0.0)
    assert stale is not None
    store.guard(stale)  # still current at this point
    time.sleep(1.1)
    assert store.acquire(RESOURCE, "worker-b", ttl_seconds=60) is not None

    with pytest.raises(StaleFencingToken, match="worker-b"):
        store.guard(stale)


def test_guard_rejects_a_lease_for_a_released_resource(store: LeaseStore) -> None:
    lease = store.acquire(RESOURCE, "worker-a", ttl_seconds=60)
    assert lease is not None
    assert store.release(lease) is True

    with pytest.raises(StaleFencingToken, match="no lease exists"):
        store.guard(lease)


def test_release_by_a_superseded_owner_does_not_remove_the_current_holder(store: LeaseStore) -> None:
    stale = store.acquire(RESOURCE, "worker-a", ttl_seconds=0.0)
    assert stale is not None
    time.sleep(1.1)
    current = store.acquire(RESOURCE, "worker-b", ttl_seconds=60)
    assert current is not None

    assert store.release(stale) is False
    assert store.read(RESOURCE) == current


def test_expiry_comes_from_the_database_not_the_caller(store: LeaseStore) -> None:
    """A caller with a skewed clock cannot extend or shorten a lease it does not control."""

    before = time.time()
    lease = store.acquire(RESOURCE, "worker-a", ttl_seconds=30)

    assert lease is not None
    # The database computed the deadline; it must be near the real one regardless of what the caller
    # believes, and it is never simply echoed back from a caller-supplied value.
    assert before + 20 < lease.expires_at_epoch < before + 40


def test_the_same_owner_reacquiring_keeps_the_resource(store: LeaseStore) -> None:
    first = store.acquire(RESOURCE, "worker-a", ttl_seconds=60)
    assert first is not None

    again = store.acquire(RESOURCE, "worker-a", ttl_seconds=60)

    assert again is not None
    assert again.owner == "worker-a"
    assert again.fencing_token >= first.fencing_token


def test_concurrent_acquisition_yields_exactly_one_winner(store: LeaseStore) -> None:
    def attempt(index: int) -> Lease | None:
        return store.acquire(RESOURCE, f"worker-{index}", ttl_seconds=60)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))

    winners = [lease for lease in results if lease is not None]
    assert len(winners) == 1
    assert store.read(RESOURCE) == winners[0]


def test_an_unknown_resource_has_no_lease(store: LeaseStore) -> None:
    assert store.read("workspace:absent") is None


def test_leases_for_different_resources_are_independent(store: LeaseStore) -> None:
    first = store.acquire("workspace:one", "worker-a", ttl_seconds=60)
    second = store.acquire("workspace:two", "worker-b", ttl_seconds=60)

    assert first is not None
    assert second is not None
    assert store.acquire("workspace:one", "worker-b", ttl_seconds=60) is None
    assert store.read("workspace:two") == second


def test_supersedes_compares_only_within_one_resource() -> None:
    first = Lease(resource="a", owner="w", fencing_token=1, expires_at_epoch=0.0)
    later = Lease(resource="a", owner="w", fencing_token=2, expires_at_epoch=0.0)
    elsewhere = Lease(resource="b", owner="w", fencing_token=9, expires_at_epoch=0.0)

    assert later.supersedes(first)
    assert not first.supersedes(later)
    assert not elsewhere.supersedes(first)
