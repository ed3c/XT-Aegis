# ADR 0006: Package Git Town adoption as a portable system-prompt contract

- **Status:** Accepted
- **Date:** 2026-08-12
- **Intent ID:** `INTENT-021`
- **Owning issue:** #49

## Context

XT-Aegis developed a detailed Git Town contract covering explicit stack lineage, eval-first issues, pinned
MIT license evidence, conservative configuration, Bash-only unattended synchronization, fail-closed
recovery, and a separate live Worker qualification gate.

Copying the XT-Aegis files directly into another repository would also copy repository-specific branch
names, issue/PR identities, hashes, forge assumptions, documentation structure, and historical decisions.
A short checklist alone would omit the authority, idempotence, evidence, and recovery rules needed by an
Agent performing repository writes.

## Decision

Maintain a versioned prompt package under
[`docs/prompts/git-town-repository-bootstrap/`](../prompts/git-town-repository-bootstrap/).

The package:

- defaults to read-only assessment;
- requires explicit mode and write authorization;
- discovers target-repository facts before requesting user input;
- produces separate Git Town and unattended-worker adoption decisions;
- creates eval-first issue/PR topology before implementation;
- validates configuration and CLI behavior against an exact selected version;
- requires exact license, source, package, binary, and configuration identities for deployment;
- separates repository fixture, exact-binary, and live-worker evidence;
- preserves prompt-injection resistance, idempotence, path ownership, and fail-closed recovery;
- defines a bounded human-readable and machine-readable output contract.

The package contains no target repository credentials, fixed live checksums, or implicit authority.

## Alternatives

### Copy the XT-Aegis Git Town directory

Rejected as the default because repository-specific identities and assumptions would be mistaken for
portable requirements. Existing scripts may be used as a reference only after the target repository's
version, forge, branch protection, and path ownership are reviewed.

### Publish one short prompt without companion contracts

Rejected because inputs, output status, eval layers, and adoption gates would become ambiguous and drift
between uses.

### Depend on a proprietary stacked-PR service

Rejected as a requirement because the user requested a CLI and Bash-compatible path without proprietary
service licensing. A target repository may still choose another tool after its own assessment.

### Automatically install and run the latest Git Town release

Rejected because it weakens reproducibility, license review, configuration compatibility, and supply-chain
identity.

## Consequences

- A future Agent can begin with only a repository URL, goal, and mode.
- The prompt package is longer than a convenience prompt because it includes safety and evidence contracts.
- Every target repository still requires an exact version decision and its own eval-first issues.
- Repository/tooling adoption may complete while live unattended deployment remains blocked.
- The prompt must be versioned and re-evaluated when Git Town configuration, CLI behavior, forge support,
  or the repository governance contract changes.

## Acceptance boundary

Acceptance of this ADR means the reusable prompt contract is maintained in XT-Aegis. It does not mean:

- another repository has adopted Git Town;
- an exact Git Town binary or Worker image is qualified;
- semantic conflicts can be resolved unattended;
- legal, supply-chain, security, or operational risk is zero;
- XT-Aegis product runtime behavior changed.
