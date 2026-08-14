# Backup and Restore

## What is protected

One SQLite database holds every durable record: runs, steps, approvals, events, and the terminal results
bound to request digests that make a replay idempotent. Losing it does not just lose history — it loses the
records that stop a repeated request from executing twice.

## Consistency

Copying the file while a writer is active can capture a torn state, because WAL content lives outside the
main file. `create_backup` therefore uses SQLite's online backup API, which produces a consistent copy
while another connection is writing. A test asserts this by backing up while a thread appends events
continuously and then running `PRAGMA integrity_check` on the copy.

## Manifest

Each backup carries `backup-manifest.json`:

| Field | Purpose |
|---|---|
| `state_schema_version` | the checkpoint schema the backup was taken from |
| `database_sha256` | integrity of the copied file |
| `database_bytes` | a cheap first mismatch signal |
| `row_counts` | per-table counts for runs, steps, approvals, and events |

Row counts are recorded so an operator can see at a glance whether a restore landed the expected data,
without opening the database.

## Restore verifies before it writes

```python
from xt_aegis.backup import create_backup, restore_backup, verify_backup

create_backup(".xt-aegis/state/checkpoints.db", "backups/2026-08-14")
verify_backup("backups/2026-08-14")
restore_backup("backups/2026-08-14", ".xt-aegis/state/checkpoints.db")
```

Nothing is written until the manifest parses, the digest matches, and the schema version is one this build
supports. A restore that half-succeeds is worse than one that never starts, because the operator would then
be recovering from a state nobody can describe.

Restore refuses to overwrite an existing database unless `overwrite=True`, and it removes stale `-wal` and
`-shm` siblings of the previous database. Leaving those behind would let SQLite interpret them against the
restored file and reintroduce records the backup does not contain.

## What this does not do

- No point-in-time recovery, no incremental backups, no off-host replication.
- No encryption. The backup contains everything the database contains, so its storage confidentiality is
  the operator's responsibility.
- No schema migration. A backup from an unsupported schema version is refused, not upgraded.
- This is one acceptance criterion of #17. Signed releases, SBOM and provenance, the supported deployment
  profile, incident response, and independent assessment remain open.
