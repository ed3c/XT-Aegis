# Local profile: Darwin arm64 developer laptop

These are raw artifacts from one developer machine. They are **not** a product performance claim, and
nothing in `PROJECT_EVIDENCE.json` is promoted because of them. `performance-and-token-savings` stays
`unverified`.

## Profile

| Field | Value |
|---|---|
| Source commit | `6b366d1ab4c0aa0858d38ebbf044f2bcb4949af0`, clean worktree |
| Operating system | Darwin 25.4.0, arm64 |
| Python | CPython 3.14.6 |
| Storage | local APFS on an internal SSD |
| Host state | shared interactive laptop; other processes were running |
| Workload | 4096-byte files, seed 0, 1 warmup, 5 measured trials per case |

The exact reproduction command is recorded inside each report as `reproduction_command`, together with the
dependency digest that makes a cross-pin comparison detectable.

## Contents

| Path | Workspace size |
|---|---|
| `workspace-32-files/benchmark-report.json` | 32 files (128 KiB) |
| `workspace-256-files/benchmark-report.json` | 256 files (1 MiB) |

## What the two sizes show

Median milliseconds on this profile, 5 trials each, 0 failures and 0 deadline overruns:

| Case | 32 files | 256 files |
|---|---|---|
| `tree-hash` | 1.412 | 13.222 |
| `snapshot` | 11.045 | 94.727 |
| `rollback` | 24.743 | 190.895 |
| `checkpoint-write` | 1.281 | 1.134 |
| `policy-evaluate` | 0.063 | 0.074 |

Tree hashing, snapshot creation, and rollback scale with workspace content on this profile, which is the
expected shape for full-tree copy and hash operations. Checkpoint writes and policy evaluation do not
depend on workspace size, and their difference across the two runs is within the noise of a shared laptop.

Five trials per case describe this machine at this moment. They are too few to characterize a tail, so
`p95_ms` and `p99_ms` in these artifacts are the nearest-rank values of a five-sample set and should not be
read as tail latency. Any comparison against a different revision, dependency digest, host, or workload is
invalid; the fields required to detect that are recorded in each report.
