# Git Town Worker Scripts

These Bash-only scripts manage repository stacks. They are repository operations tools, not XT-Aegis
product runtime tools.

## Commands

| Script | Purpose |
|---|---|
| `verify-release-artifact.sh` | verify the pinned Linux amd64 DEB hash, version, and architecture before worker-image installation |
| `verify-license.sh` | verify exact Git Town version, installed-binary checksum, release identity, and copied MIT license |
| `bootstrap.sh` | print or write explicit local parent metadata from `stack.tsv` without rebasing or switching branches |
| `verify-stack.sh` | validate config checksum, origin/repository identity, refs, upstreams, parent metadata, open PR lineage, local-branch allowlist, and no-push dry run |
| `sync-stack.sh` | foreground non-interactive all-stack sync with deadline, bounded evidence, and current-run-only recovery |
| `sync-background.sh` | `nohup` wrapper with PID, launch metadata, wrapper log, child log, and status |
| `common.sh` | shared preflight, hashing, exact-origin, lock, state snapshot, timeout, log, and atomic-status helpers |
| `test-fixture.sh` | disposable no-network success and failure contract evals with fake Git Town/GitHub CLIs |

## Required environment

```bash
export GIT_TOWN_BINARY_SHA256="<approved SHA-256 of the installed git-town binary>"
```

The worker image provides credentials and the platform-specific checksum. It must pin Bash 4+, Git,
GitHub CLI, GNU `timeout`, ShellCheck, and Git Town `24.0.0`.

Optional worker-controlled limits:

```bash
export XT_AEGIS_GIT_TOWN_TIMEOUT_SECONDS=1800
export XT_AEGIS_GIT_TOWN_MAX_LOG_BYTES=1048576
export XT_AEGIS_GIT_TOWN_STATE_DIR=/secure/worker-state/xt-aegis-git-town
```

Timeout must be `1..7200` seconds. Log capacity must be `65536..8388608` bytes. Without an override,
private runtime artifacts are written under `.git/xt-aegis/git-town/`.

## Dedicated checkout contract

Every local branch must appear as a branch or parent in `stack.tsv`; otherwise `sync --all` fails before
mutation. Every manifest branch must:

- exist locally and as `origin/<branch>`;
- track its same-name origin branch;
- share Git history with its parent;
- have local Git Town parent metadata matching the manifest;
- name an open GitHub PR whose head and base match the branch and parent.

A parent is allowed to advance beyond its children before synchronization. Requiring the parent to remain
an ancestor of every child would reject the exact state that rebase is meant to repair.

## Usage

```bash
scripts/git-town/verify-release-artifact.sh /secure/input/git-town_linux_intel_64.deb
scripts/git-town/verify-license.sh
scripts/git-town/bootstrap.sh
scripts/git-town/bootstrap.sh --apply
scripts/git-town/verify-stack.sh
scripts/git-town/sync-stack.sh --dry-run
scripts/git-town/sync-stack.sh
scripts/git-town/sync-background.sh --dry-run
scripts/git-town/sync-background.sh
scripts/git-town/test-fixture.sh
```

`bootstrap.sh --apply` updates repository-local Git config only. Review its printed plan first.

## Failure semantics

Preflight failures never call `git town undo`. Once mutating sync begins, undo is attempted only when the
current invocation changed Git Town's runlog or Git reports a suspended operation. Recovery compares the
complete pre/post state: all local and `origin/*` tracking refs, current branch, HEAD, parent metadata,
operation state, and worktree cleanliness.

Terminal phases include:

- `preflight_*` — no mutating sync started;
- `failed_restored` — complete pre-sync state was proven restored;
- `failed_recoverable` — state differs or restoration cannot be proven;
- `post_sync_unverified_*` — sync returned success but later observation failed; no automatic undo;
- `dry_run_complete` and `sync_complete` — terminal success.

A non-zero result is a blocker. Do not continue a semantic conflict or `failed_recoverable` state without
an explicit owner.

## Evidence levels

`test-fixture.sh` validates the repository-side Bash contract without network access. The exact binary,
release package, ShellCheck, real conflict, safe-force, remote-race, and secret-canary acceptance matrix
is tracked by #44. Merging these scripts does not authorize unattended deployment before #44 passes.
