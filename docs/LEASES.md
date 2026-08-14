# Resource Leases and Fencing Tokens

## Why a lease is not enough

A worker that is paused, swapped out, or blocked on I/O for longer than its lease will resume believing it
still holds the resource. No amount of expiry checking *on that worker* fixes this, because the worker's
own view is the thing that is stale.

The defence is the token. Every takeover mints a strictly greater fencing token, so the resource can reject
an operation carried by a superseded token regardless of what the stale holder believes. A renewal never
changes the token; only a takeover does.

## Contract

```python
from xt_aegis.leases import SqliteLeaseStore, StaleFencingToken

store = SqliteLeaseStore(".xt-aegis/state/leases.db")
lease = store.acquire("workspace:demo", "worker-a", ttl_seconds=60)
if lease is None:
    ...  # someone else holds it

store.guard(lease)  # raises StaleFencingToken when this lease has been superseded
store.renew(lease, ttl_seconds=60)
store.release(lease)
```

| Operation | Semantics |
|---|---|
| `acquire` | grants a free or expired resource, returning a lease whose token is greater than any previous one for that resource; returns `None` when a live lease is held by someone else |
| `renew` | extends an owned, unexpired lease; the token is unchanged; returns `None` when the lease was taken over or expired |
| `release` | removes the lease only when the resource, owner, and token all still match |
| `read` | the current lease, expired or not |
| `guard` | raises `StaleFencingToken` when the caller's lease is no longer the current one |

## The clock

Expiry is computed by the database, never by the caller. PostgreSQL uses `now()` in the same statement that
writes the row. SQLite uses `strftime('%s','now')`, which is the clock of the process holding the database
— that is a single-node property and is stated here rather than implied away.

A caller cannot extend or shorten a lease by having a skewed clock, because no caller-supplied timestamp is
ever stored.

## Concurrency

PostgreSQL serializes concurrent acquisition on the primary key: the `INSERT ... ON CONFLICT DO UPDATE`
decides the winner inside one statement using the server clock.

SQLite needs an explicit `BEGIN IMMEDIATE`. Python's `sqlite3` starts a transaction only before DML, so a
read-then-write acquire would otherwise run its `SELECT` outside the write lock and let several callers
each conclude the resource was free. The conformance suite caught exactly that: eight concurrent acquirers
produced five winners before the fix, and one after it.

## What this does not provide

- It is not a distributed consensus system. A PostgreSQL failover, a partition, or a clock jump on the
  server is outside what a lease table can decide.
- Nothing in the runner yet requires a fencing token. `guard` is the seam that makes that a small later
  change; until then, holding a lease is advisory.
- No claim is made that XT-Aegis supports multi-worker production use. The dependency policy in #8 keeps
  that behind v0.3, and the rest of #14 — the storage-backend interface, the PostgreSQL checkpoint
  implementation, migrations, and optimistic concurrency on every transition — is still open.

## Running the PostgreSQL half of the suite

`psycopg` is an optional extra, never a runtime dependency of the core:

```bash
pip install "xt-aegis[postgres]"
docker run -d --name xt-aegis-pg -e POSTGRES_PASSWORD=xtaegis -e POSTGRES_DB=xtaegis -p 55432:5432 postgres:14
XT_AEGIS_TEST_POSTGRES_DSN=postgresql://postgres:xtaegis@127.0.0.1:55432/xtaegis pytest tests/test_leases.py -q
```

Without that variable the PostgreSQL half skips with a stated reason; the SQLite half always runs.
