# Checkpoint Storage Backends

## The contract is written down first

`CheckpointBackend` is descriptive, not aspirational: it records exactly the operations the runner and
controller already call on the SQLite store. Without that written contract, "PostgreSQL support" would mean
whatever the second implementation happened to do.

| Operation | Meaning |
|---|---|
| `start_run`, `set_run_status` | thread lifecycle |
| `prepare_step` | reserve or reuse one step number for this exact canonical request |
| `get_cached_result` | the terminal result for this exact request, or nothing yet |
| `save_result` | persist a terminal result whose identity matches the reserved step |
| `get_or_create_approval`, `approval_state`, `approval_is_valid`, `claim_approval`, `decide_approval` | the approval state machine |
| `append_event`, `list_events` | trajectory events |
| `get_resume_position` | the next step after every terminal step |

## Equivalence is proven, not asserted

`tests/test_checkpoint_conformance.py` runs one suite against both backends. It covers step reservation,
identity conflicts on a substituted payload, terminal-result round trips, foreign and unbound identities,
resume position, the full approval state machine including expiry, reuse, mismatch, single-use claiming,
and decision validation, plus event ordering and thread isolation.

The PostgreSQL half skips with a stated reason when no server is reachable, so a default checkout still
runs the SQLite half.

## Schema migrations

The schema is owned by an ordered list in `src/xt_aegis/migrations.py` and recorded in a
`schema_migrations` ledger holding a version, a description, and when it was applied. Both backends run the
same list; only the DDL text differs, because DDL is not portable.

| Question | Answered by |
|---|---|
| Which shape is this database in? | the highest recorded version |
| How did it get there? | the whole ledger, in order |
| Is a rerun safe? | yes — a recorded version is skipped, so safety does not depend on the DDL happening to be idempotent |
| What about a database from a newer build? | refused with the version named, rather than opened and written to |

A database predating the ledger is adopted into it rather than refused: its baseline is recorded and the
outstanding migrations run, so an upgraded database and a fresh one end up with the same columns. The
single `metadata.schema_version` row is still written, because an older build reads only that row and must
keep failing closed.

Migrations are forward-only. A down-migration is code written once, never exercised, and run for the first
time during an incident; the rollback path is a verified restore ([`BACKUP.md`](BACKUP.md)).

## Compare-and-set on every transition

`runs` and `steps` each carry a monotonic `state_version` that every mutating transition increments.

| Transition | Guard | On a lost race |
|---|---|---|
| `set_run_status` | the run exists, and `state_version` matches when the caller supplies one | `StateVersionConflict` |
| `save_result` | the identity triple matches **and** the step is not already terminal | `IdempotencyConflictError` naming which of the two failed |
| `decide_approval` | the approval is pending and unexpired | `ApprovalError` |
| `claim_approval` | approved, unconsumed, unexpired, and identity-matched | returns `False` |

The step guard is the one that changed behaviour: two workers that both reserve the same step and both
finish used to last-write-win, and the second one now learns it lost. `run_state` and `step_state` return
the current status together with the version a caller must present, which is what makes an explicit
compare-and-set possible from outside the store.

Approvals are guarded on their state rather than on a version. They already have a state machine that
admits exactly one transition out of `pending`, so a version column would add a second, weaker guard over
the same invariant.

## Deliberate design choices

**Timestamps are ISO-8601 strings on both backends.** A `timestamptz` column would be the natural
PostgreSQL choice, and it would also make expiry comparisons differ subtly from SQLite's lexicographic
string comparison. A backend that is *nearly* identical is worse than one that is deliberately identical,
because the difference would surface only under an expiry race — the worst possible moment to discover it.

**The clock is the application's, on both backends.** The existing SQLite store computes `utc_now()` in the
process, and the PostgreSQL backend matches it rather than using `now()`. That is different from
[`LEASES.md`](LEASES.md), where the database clock is the whole point: a lease arbitrates between competing
workers, while a checkpoint records what one worker did. Unifying the two is follow-up work in #14, not an
accident.

## Running the PostgreSQL half

```bash
pip install "xt-aegis[postgres]"
docker run -d --name xt-aegis-pg -e POSTGRES_PASSWORD=xtaegis -e POSTGRES_DB=xtaegis -p 55432:5432 postgres:14
XT_AEGIS_TEST_POSTGRES_DSN=postgresql://postgres:xtaegis@127.0.0.1:55432/xtaegis \
  pytest tests/test_checkpoint_conformance.py -q
```

## Still open in #14

- Runner wiring and backend selection; nothing chooses PostgreSQL at runtime yet, and no caller passes an
  `expected_version` — the guard exists and is tested, but the runner does not yet use it.
- Partition, failover, and acknowledgement-ambiguity scenarios, which need a controllable network.
- No multi-worker production claim is made. The dependency policy in #8 keeps that behind v0.3.
