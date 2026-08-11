# Git Town License and Supply-Chain Gate

## Selected upstream

| Field | Value |
|---|---|
| Project | Git Town |
| Repository | `git-town/git-town` |
| Tag | `v24.0.0` |
| Release commit | `0f3e55f5a6bae5b319dd713a0606263d0551af66` |
| Release state | immutable GitHub release; signed release commit |
| License | MIT |
| Upstream LICENSE Git blob SHA | `4bcd5ec1942737f7976b8bac8534a8ab642ec0e0` |
| Local LICENSE SHA-256 | `eec8a092b92231375231488d27b959e2fa2be80559c97db60c1b0458d3298791` |
| `checksums.txt` asset SHA-256 | `7532377166cb59dc01c74f86e3a71c54ba9567a461313a5d203a1ea99c571b24` |
| Reference Linux amd64 package | `git-town_linux_intel_64.deb` |
| Reference package SHA-256 | `1535999a402e08c721538473808429eeb71beb929ef51a1438ba007434951dd7` |
| Local notice | `third_party/git-town/` |

The MIT terms permit use, copying, modification, distribution, sublicensing, and sale subject to retaining
the copyright and license notice. The upstream text is copied unchanged into this repository.

## Risk statement

This selection removes dependency on a proprietary stacked-PR SaaS license and provides permissive
commercial-use terms. It cannot prove absolute absence of:

- patent or trademark disputes;
- compromised release artifacts or build systems;
- transitive/toolchain vulnerabilities;
- incompatible organizational policy;
- future upstream relicensing;
- operational damage from incorrect Git use.

The repository therefore describes the requirement as **license-verified and supply-chain pinned**, not as
a legal guarantee. Organizations still apply their own legal and security review.

## Worker image gate

A Worker Agent may run Git Town only when:

1. the downloaded Linux amd64 package passes `verify-release-artifact.sh`, or another platform artifact is pinned by an approved worker-image manifest;
2. `git town --version` exactly reports `24.0.0`;
3. the local third-party license SHA-256 matches the lock;
4. the worker supplies `GIT_TOWN_BINARY_SHA256`;
5. the installed `git-town` binary SHA-256 equals that value;
6. the checksum value came from an approved immutable worker-image manifest or independently verified
   release artifact;
7. Bash 4+, Git, and GitHub CLI versions are also pinned by the worker image;
8. the worker checkout contains only manifest-declared local branches;
9. no install step uses an unpinned `latest`, package-channel head, or `curl | sh`.

Repository scripts reject missing, `UNSET`, malformed, or mismatched checksums.

## Update process

A Git Town upgrade uses its own issue and PR:

- review the new upstream license and tag identity;
- update the copied license only when its exact text changes;
- update version and license hashes;
- record platform artifact checksums in the worker-image manifest;
- run Bash syntax, config parse, dry-run, clean sync, conflict, recovery, and remote-race evals;
- review changed Git Town defaults and migration notes;
- update this runbook and `stack.tsv`;
- do not combine the upgrade with product implementation.

## Installation policy

Build or install Git Town in a controlled worker image. A repository checkout does not download or install
the binary. Secrets remain in the worker credential mechanism, never in `.git-town.toml`, scripts,
arguments, or logs.
