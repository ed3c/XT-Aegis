# Supported Deployment Profile

## What this document is

`production reference profile` may name only the configuration that has actually been tested. This file is
that list. Everything absent from it is unsupported — not "probably fine".

XT-Aegis is an alpha reference implementation. Nothing here says it is production ready; #17 remains open.

## Tested configurations

| Dimension | Tested | Evidence |
|---|---|---|
| Python | CPython 3.11 and 3.12 | every CI run on both versions |
| Operating system (CI) | Ubuntu (GitHub-hosted runner) | every CI run |
| Operating system (developer) | Darwin arm64 | local runs recorded in `benchmarks/local-darwin-arm64/` |
| Checkpoint storage | SQLite (WAL) | the full suite; it is the default |
| Checkpoint storage | PostgreSQL 14.22 | the shared conformance suite in [`STORAGE_BACKENDS.md`](STORAGE_BACKENDS.md), developer host only |
| Action isolation | Docker 29.4.0 with `python:3.12-slim` | the live evidence in [`ACTION_ISOLATION.md`](ACTION_ISOLATION.md), developer host only |
| Verification backend | `unsafe-local` | CI claim verification |
| Git Town worker toolchain | v24.0.0 on Debian 12 amd64 | the partial acceptance evidence under `docs/evidence/git-town-worker/v24.0.0/` |

## Explicitly not supported

| Configuration | Why |
|---|---|
| OpenShell sandbox | the conformance gateway cannot currently create a sandbox; see issue #12 |
| Rootless Podman | the adapter probes for it, but no live evidence exists anywhere in this repository |
| Windows | never tested; the runtime uses POSIX process groups and `os.setsid` |
| Multi-worker or multi-host operation | the checkpoint store has no compare-and-set on every transition; leases exist but nothing requires a fencing token yet |
| Remote or authenticated MCP mutation | no mutating tool is registered; only the admission decision exists |
| Any deployment relying on egress enforcement | the egress plane decides, it does not enforce at the socket |

## Required settings for the tested isolation profile

```text
--user <host uid>:<gid>   --network none   --read-only   --cap-drop ALL
--security-opt no-new-privileges   --pids-limit 128   --memory 1g   --cpus 1
--mount type=bind,src=<owned workspace>,dst=/workspace   --tmpfs /tmp:rw,noexec,nosuid   --rm
```

A contract that must not run without this profile sets `requires_isolation: true`, which fails closed when
the backend is weak or unready.

## State and recovery

- One SQLite database holds runs, steps, approvals, events, and terminal idempotency records.
- Back it up with the verified backup in [`BACKUP.md`](BACKUP.md). A restore refuses anything it cannot
  verify.
- The recovery table for an interrupted run is in [`RECOVERY.md`](RECOVERY.md).

## Software inventory

```bash
xt-aegis sbom --output sbom.json
```

The output is CycloneDX 1.5, generated from installed distribution metadata using only the standard
library, sorted, and free of timestamps — two runs in the same environment produce identical bytes, so two
builds can be compared. An inventory is not an assessment: it lists what is present, not whether any of it
is vulnerable.

The release workflow generates this document from a clean install of the built wheel — not from the
build environment, which carries the dev extras. The difference is not cosmetic: the same generator
reports 52 components in a development checkout and 7 in a fresh install of the wheel. The result is
attested with `actions/attest-sbom` alongside the existing build provenance and attached to the release.

Two things it is still not: signed independently of GitHub's attestation, and assessed against an advisory
database. Both remain open in #17.

## Reproducing this profile

```bash
python -m pip install -e ".[dev]"      # add ",mcp", ",otel", or ",postgres" for those extras
make check                              # format, lint, types, tests, coverage
xt-aegis demo --output-dir ./demo-out   # deterministic end-to-end run
xt-aegis doctor --format json           # backend readiness, per component
xt-aegis sbom --output sbom.json
```

No step reads hidden local state. Every optional capability is behind a named extra, and every extra that
is absent degrades to a stated refusal rather than a silent fallback.
