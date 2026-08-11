# Git Town Repository-Side Eval Results

Date: 2026-08-11
Scope: PR #41 repository configuration, Bash orchestration, documentation, and third-party notice only.
Live worker deployment gate: #44.

## Commands executed

```bash
bash -n scripts/git-town/*.sh
XT_AEGIS_FIXTURE_SOURCE_ROOT=/path/to/proposed-tree scripts/git-town/test-fixture.sh
```

Additional local checks parsed `.git-town.toml` with Python `tomllib`, verified the pinned config and
license SHA-256 values, rejected trailing whitespace/non-UTF-8 text, and scanned scripts for destructive
`git reset --hard`, forced push, `git clean -f`, credential assignments, and `curl | sh` patterns.

## Results

| Eval | Result | Evidence / limitation |
|---|---|---|
| `EVAL-GIT-01` Bash syntax | passed | `bash -n` passed for every `scripts/git-town/*.sh` file |
| `EVAL-GIT-02` strict, lock, credential, deadline, and log safety | passed | strict mode, quoting, private state, exact origin, exclusive Git-dir lock, atomic status, GNU timeout, bounded log, and safety-pattern scan |
| `EVAL-GIT-03` version/license provenance | passed for repository metadata | tag, release commit, MIT text/blob, copied-license SHA, checksums asset SHA, package SHA, and config SHA are pinned; upstream metadata was independently checked |
| `EVAL-GIT-04` checksum gate | passed negative paths; live positive path not run | missing/malformed/wrong binary hash, changed config, changed license, and wrong package are rejected; exact official DEB was unavailable in this execution environment |
| `EVAL-GIT-05` real v24 dry run | not run | exact Git Town v24.0.0 binary could not be downloaded or built because the execution environment had no external DNS/network access; tracked by #44 |
| `EVAL-GIT-06` conflict-free fixture | passed | dedicated bare origin, parent advanced after children, explicit parent metadata, foreground dry run/sync, and background dry run passed with behavior-compatible CLIs |
| `EVAL-GIT-07` fail-closed cases | passed for repository fixture | wrong repo/base/parent, missing/unknown branch, dirty/suspended state, checksum/config mismatch, lock contention, timeout, and semantic failure are terminal |
| `EVAL-GIT-08` recovery | passed for repository fixture | preflight does not call undo; current-run failure does; complete local/tracking ref and parent snapshots distinguish restored from recoverable sibling mutation |
| `EVAL-GIT-09` manifest/PR lineage | passed for repository fixture | branch, parent, issue, PR, upstream, open state, and duplicate ownership checks passed |
| `EVAL-GIT-10` no Python/workflow changes | passed | this slice changes no `*.py` or `.github/workflows/**` file |
| ShellCheck | not run | ShellCheck was unavailable; exact tool-version evidence remains required by #44 |

## Fixture scenarios

The passing fixture covers:

- parent advanced after child creation;
- explicit parent bootstrap without rebase or branch switching;
- exact config identity and repository/origin identity;
- open PR head/base lineage;
- missing, unknown, and wrongly configured branches;
- dirty and suspended repositories;
- binary, version, license, config, and package mismatch;
- preflight failure without undo;
- current-run-only undo behavior;
- semantic failure and full-state restoration proof;
- a sibling ref mutation that remains `failed_recoverable`;
- wall-clock timeout and bounded excessive output;
- foreground and background observable completion.

## Claim boundary

These results validate repository-side orchestration using a behavior-compatible fake Git Town/GitHub
fixture. They do not prove behavior of the exact v24.0.0 binary, official release package, real GitHub
authentication, remote races, safe force-push protection, or ShellCheck. #44 must preserve and review that
live evidence before an unattended worker is enabled.
