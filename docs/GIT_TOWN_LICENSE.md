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
| Linux amd64 package | `git-town_linux_intel_64.deb` |
| Package SHA-256 | `1535999a402e08c721538473808429eeb71beb929ef51a1438ba007434951dd7` |
| Repository config SHA-256 | `dac32bfc8557e9f9f86537a4e081f32eff90f2965233b48a7676bace687356db` |
| Local notice | `third_party/git-town/` |

Primary references are the upstream [v24.0.0 release](https://github.com/git-town/git-town/releases/tag/v24.0.0),
[MIT license](https://github.com/git-town/git-town/blob/v24.0.0/LICENSE), and the pinned
[configuration schema](https://github.com/git-town/git-town/blob/v24.0.0/docs/git-town.schema.json).
The copied MIT text remains unchanged.

The MIT terms permit use, copying, modification, distribution, sublicensing, and sale subject to retaining
the copyright and license notice.

## Risk statement

This choice removes a proprietary stacked-PR SaaS license dependency and provides permissive
commercial-use terms. It does not prove absolute absence of:

- patent or trademark disputes;
- compromised release artifacts, dependencies, or build systems;
- incompatible organizational policy;
- future upstream relicensing;
- defects in Git Town, Git, GitHub CLI, the operating system, or worker scripts;
- operational damage from an incorrect rebase or push.

The supported wording is **MIT-licensed, license-verified, and supply-chain pinned for the declared
profile**. It is not a promise of zero legal, security, supply-chain, or operational risk. Organizations
retain their own legal and security review.

## Repository-side gate

PR #41 provides a non-installing repository contract:

- the exact version, release, package, license, config, and expected repository are pinned in
  `scripts/git-town/git-town.lock`;
- the local license text and installed binary are checksum-verified;
- `.git-town.toml` is itself checksum-bound;
- the checkout origin must resolve exactly to `ed3c/XT-Aegis` without embedded credentials;
- new branches, proposal breadcrumbs, push hooks, auto-sync, and auto-resolve are disabled;
- the no-network fixture validates fail-closed Bash behavior.

This layer does not download a binary and cannot promote a live worker claim.

## Worker image gate

A Worker Agent may run Git Town only when:

1. the official Linux amd64 package passes `verify-release-artifact.sh` or another platform artifact is
   separately pinned and reviewed;
2. `checksums.txt`, package SHA-256, package metadata, tag, and release commit agree;
3. `git town --version` exactly reports `24.0.0`;
4. the resolved `git-town` on `PATH` matches `GIT_TOWN_LINUX_AMD64_BINARY_SHA256` in `git-town.lock`,
   which the worker cannot override — an expectation supplied by whoever started the run would verify
   the run against its own claim;
5. the installed binary and copied MIT license match their pinned digests;
6. Bash, Git, GitHub CLI, GNU `timeout`, and ShellCheck versions are pinned;
7. credentials are injected outside repository files, prompts, arguments, logs, and evidence;
8. the checkout contains only manifest-declared local branches and exact reviewed parent metadata;
9. no install path uses `latest`, an unpinned package-channel head, or `curl | sh`;
10. the live acceptance matrix in #44 has passed for that exact worker profile.

Repository scripts reject missing, `UNSET`, malformed, or mismatched checksums. #44 remains the deployment
gate for real binary, ShellCheck, conflict, remote-race, timeout, background, and secret-canary evidence.

## Update process

A Git Town upgrade uses its own issue and PR:

- review the new upstream license, tag, release commit, schema, defaults, and migration notes;
- update the copied license only when its exact text changes;
- update version, artifact, binary, license, and config hashes;
- rebuild an immutable worker image;
- rerun Bash syntax, ShellCheck, config parse, dry-run, clean sync, semantic conflict, complete-ref recovery,
  remote-race, timeout, output-bound, and secret-canary evals;
- preserve failed and timed-out raw evidence;
- update this runbook, `stack.tsv`, and accepted evidence links;
- do not combine the upgrade with XT-Aegis product implementation.

## Installation policy

Build or install Git Town only in a controlled worker image. A repository checkout does not download or
install the binary. Secrets remain in the worker credential mechanism, never in `.git-town.toml`, scripts,
arguments, logs, or committed evidence.
