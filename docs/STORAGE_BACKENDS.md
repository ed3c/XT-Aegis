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

- Schema migrations across versions, and rollback/forward recovery.
- Monotonic state versions with compare-and-set on every mutating transition. Today `save_result` compares
  and sets on the identity triple, which stops a foreign writer but does not stop two identical writers.
- Runner wiring and backend selection; nothing chooses PostgreSQL at runtime yet.
- Partition, failover, and acknowledgement-ambiguity scenarios, which need a controllable network.
- No multi-worker production claim is made. The dependency policy in #8 keeps that behind v0.3.
