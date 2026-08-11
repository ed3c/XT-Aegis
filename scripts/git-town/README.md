# Git Town Worker Scripts

These Bash-only scripts manage repository stacks. They are not XT-Aegis product runtime tools.

## Commands

| Script | Purpose |
|---|---|
| `verify-release-artifact.sh` | verify the pinned Linux amd64 release package before worker-image installation |
| `verify-license.sh` | verify exact Git Town version, copied MIT license, and installed-binary checksum |
| `verify-stack.sh` | validate manifest structure, branch ancestry, clean state, and config dry run |
| `bootstrap.sh` | print or apply explicit Git Town parent relationships from `stack.tsv` |
| `sync-stack.sh` | foreground non-interactive all-stack sync with recovery |
| `sync-background.sh` | detached wrapper with PID, log, and status locations |
| `common.sh` | shared preflight, lock, hashing, and status helpers |

## Required environment

```bash
export GIT_TOWN_BINARY_SHA256="<approved checksum for the installed binary>"
```

The worker image, not the repository, provides credentials and the platform-specific checksum. It must
provide Bash 4+, Git, GitHub CLI, and the exact pinned Git Town binary. The checkout is dedicated to one
manifest: every local branch must appear as a branch or parent in `stack.tsv`, otherwise `sync --all`
fails before mutation.

## Examples

```bash
scripts/git-town/verify-release-artifact.sh /secure/input/git-town_linux_intel_64.deb
scripts/git-town/verify-license.sh
scripts/git-town/verify-stack.sh
scripts/git-town/bootstrap.sh
scripts/git-town/bootstrap.sh --apply
scripts/git-town/sync-stack.sh --dry-run
scripts/git-town/sync-background.sh
```

A non-zero result is a blocker. Read the bounded log and status file beneath
`.xt-aegis/git-town/`; do not instruct an Agent to continue a real conflict without an explicit owner.
