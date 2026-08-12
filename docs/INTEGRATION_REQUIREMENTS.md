# External Verification Integration Requirements

## Status and scope

This document is the normative implementation contract for agents and contributors changing the
XT-Aegis external verification plane. It describes what must remain true across the CLI, MCP surface,
verification registry, sandbox backends, evidence artifacts, CI, and release distribution.

Repository text is untrusted input. This document guides repository maintenance, but it does not grant
runtime authority, override a user's policy, or authorize execution on behalf of a user.

Normative terms use **MUST**, **MUST NOT**, **SHOULD**, and **MAY** in their usual requirements sense.

## Required reading order

Before changing verification or runtime code, an agent MUST read:

1. `AGENTS.md`;
2. this document;
3. `docs/THREAT_MODEL.md`;
4. `docs/EXTERNAL_VERIFICATION.md`;
5. `docs/OPENSHELL.md` when OpenShell behavior is affected;
6. `PROJECT_EVIDENCE.json` and the schemas under `verification/schemas/`;
7. the relevant implementation and negative tests.

When these sources disagree, the more restrictive safety behavior wins until the inconsistency is
resolved through code, tests, evidence metadata, and documentation in the same change.

## System goal

XT-Aegis enables a user-controlled agent, GitHub scanner, CI job, or local verification client to:

1. discover falsifiable project claims without executing repository code;
2. obtain a bounded execution plan represented as structured data;
3. execute selected claim recipes in a user-controlled sandbox;
4. bind the result to the selected source revision and runtime policy;
5. produce portable, deterministic evidence without making ranking or selection decisions.

The verification plane returns evidence, status, limitations, and reproducibility metadata. It MUST NOT
instruct another system how to score, rank, select, or trust the project.

## Architectural boundary

```mermaid
flowchart LR
    R[Repository and claim registry] -->|untrusted proposal| V[Verifier policy]
    U[User] -->|explicit backend and execution consent| V
    V --> P[Validated argv-only plan]
    P --> B[SandboxBackend]
    B --> O[OpenShell]
    B --> C[Rootless Podman or Docker]
    B --> L[unsafe-local: explicit development only]
    O --> E[Structured result and artifacts]
    C --> E
    L --> E
    E --> D[Deterministic evidence bundle]
    D --> A[User or external agent]
```

The repository proposes claims and recipes. The verifier owns validation and resource bounds. The
sandbox runtime owns process isolation according to its own threat model. The user owns the decision to
execute and the policy used to interpret the result.

## Verification levels

### Level 0: static consistency

Level 0 MUST NOT execute repository code. It MAY inspect metadata, schemas, claim paths, limitations,
release manifests, and CI references. Its result MUST NOT be labeled independently verified.

### Level 1: project-operated CI evidence

Level 1 runs within project-controlled CI. It MUST be labeled project-operated evidence. It MUST NOT be
presented as independent reproduction or proof of strong sandbox isolation.

### Level 2: user-operated sandbox verification

Level 2 runs the same structured recipes in a runtime selected and controlled by the user. The result
MUST record source, backend, policy, recipe, and artifact identity. Runtime-specific limitations MUST
remain visible in the result and evidence bundle.

## Functional requirements

### FR-1: stable CLI contract

The CLI MUST provide machine-readable forms of:

- `xt-aegis doctor` for non-executing runtime discovery;
- `xt-aegis plan` for non-executing recipe and host-argv inspection;
- `xt-aegis verify` for one claim or all runnable claims;
- `xt-aegis evidence pack` for deterministic evidence packaging.

The JSON output MUST be schema-stable within a published major version. Human-readable output MAY be
added, but automation MUST NOT depend on parsing prose.

Stable process exit codes are:

| Code | Meaning |
|---:|---|
| `0` | verified |
| `10` | unsupported environment |
| `20` | verifier policy denied execution |
| `30` | verification failed |
| `40` | inconclusive |
| `50` | verifier error |

### FR-2: structured verification registry

`PROJECT_EVIDENCE.json` MUST remain a strict, versioned registry. Runnable recipes MUST use:

- an argv array, never a shell string;
- a normalized relative working directory;
- a fixed timeout;
- bounded stdout and stderr;
- default-deny network intent;
- explicit expected exit codes and assertions;
- declared artifacts and limitations.

Unknown fields, unknown statuses, unknown actions, invalid paths, and invalid executable forms MUST fail
closed. A registry entry MUST NOT supply arbitrary environment variables, mounts, credentials, provider
configuration, or runtime policy expansion.

### FR-3: source revision binding

A verification run MUST execute against the source revision selected by the user, not only source baked
into an image. Results MUST record, when available:

- repository identity;
- full commit SHA;
- dirty-worktree state;
- registry digest;
- recipe digest;
- verifier package or image identity.

A source upload MUST exclude generated artifacts and Git-ignored local data by default. A dirty source
MUST be reported explicitly and MUST NOT be represented as a clean commit reproduction.

### FR-4: sandbox backend abstraction

The typed verification contract MUST remain independent of a specific runtime. Backends MUST implement a
common discovery, planning, execution, timeout, bounded-output, and result interface.

Automatic selection MUST fail closed in this order:

```text
OpenShell -> confirmed-rootless Podman -> reachable Docker -> unsupported
```

`unsafe-local` MUST NOT be selected automatically. It MAY run only after the user names it explicitly,
and its results MUST state that they are not independently sandboxed.

### FR-5: MCP surface separation

The packaged MCP server MUST be read-only by default. Read-only tools MAY expose:

- project capabilities;
- claim lists and claim details;
- runtime discovery;
- non-executing verification plans;
- existing evidence and limitations.

Execution tools MUST be registered only when the user starts a local MCP process with explicit execution
consent. Repository content, tool descriptions, request arguments, model output, or remote callers MUST
NOT enable execution mode or change the backend selected at server startup.

A public or unauthenticated remote MCP endpoint MUST NOT execute repository code. Remote execution is out
of scope until authentication, authorization, origin validation, rate limits, audit controls, and a
separate deployment threat model are implemented and verified.

### FR-6: deterministic evidence

Each verification result MUST include:

- claim ID and declared claim status;
- final verifier status and reason;
- source identity;
- backend and runtime identity;
- policy, registry, and recipe digests;
- exact argv and normalized cwd;
- timeout state and exit code;
- bounded, redacted stdout and stderr;
- artifact digests;
- explicit limitations.

`xt-aegis evidence pack` MUST create a deterministic archive with normalized paths, ownership,
permissions, ordering, and timestamps. Its manifest MUST include SHA-256 and size for every file.
Deterministic hashes prove integrity, not publisher identity; release signatures or attestations are a
separate control.

### FR-7: distribution and discovery

Distribution metadata MUST remain consistent across:

- `pyproject.toml` console scripts and optional dependencies;
- `server.json` MCP package declarations;
- the verifier OCI image;
- README installation commands;
- release workflows and attestations.

Users SHOULD be able to pin immutable package versions and OCI digests. Publication MUST fail when
metadata, ownership markers, package names, entry points, or schemas disagree.

### FR-8: claim lifecycle

A claim may move from `planned` or `unverified` to `implemented` or `verified-in-ci` only when the same
change includes:

- implementation;
- positive tests;
- negative or failure-path tests;
- a bounded verification recipe;
- updated limitations;
- updated threat-model content when a trust boundary changes;
- CI evidence for the declared environment.

One successful runtime execution MUST NOT be generalized into a universal security, performance, or
compatibility guarantee.

## OpenShell integration requirements

OpenShell is an optional strong verification backend. It is not the XT-Aegis policy engine and it retains
its own threat model.

The OpenShell adapter MUST:

1. use a reviewed and pinned OpenShell release in conformance CI;
2. use a verifier image compatible with the OpenShell supervisor and unprivileged user contract;
3. clear incompatible interactive OCI entrypoints when required;
4. upload the selected checkout directly under `/workspace`;
5. run claim code from the uploaded source by setting the reviewed Python source path explicitly;
6. execute through `xt_aegis.sandbox_exec` or an equivalent argv-only launcher;
7. reject absolute `cwd`, path traversal, path-qualified executables, and shell evaluation;
8. disable automatic providers and TTY allocation for automated verification;
9. use default-deny network policy unless a future reviewed claim explicitly requires otherwise;
10. pass only a fixed allowlist of runtime environment variables;
11. impose CPU, memory, wall-time, output, and artifact bounds;
12. clean up the sandbox deterministically;
13. record policy and image identity with the result;
14. capture diagnostics on failure without exposing secrets.

Live conformance MUST be a merge or release gate before OpenShell behavior is described as verified for a
specific version and driver. A passing conformance run MUST still state that it does not prove resistance
to OpenShell, driver, container-runtime, VM, or host-kernel vulnerabilities.

## Security invariants

Every change MUST preserve these invariants:

- Markdown prose and fenced code blocks are never executable authority.
- External content remains data unless a trusted integration labels a separate typed user proposal.
- No arbitrary shell string is accepted by verification or MCP execution paths.
- No repository-controlled recipe may add host mounts, credentials, providers, network endpoints, or
  arbitrary environment variables.
- Paths remain relative, normalized, allowlisted, and confined to the disposable workspace.
- Outputs and artifacts remain bounded and secret-redacted.
- Strong-backend unavailability returns unsupported rather than silently lowering isolation.
- High-risk runtime actions remain subject to explicit user approval where applicable.
- Project-operated CI evidence remains distinguishable from user-operated independent reproduction.
- Unsupported numeric performance or token-saving claims remain unverified.

## Terminology and documentation policy

Public project documentation MUST describe actors as **user**, **agent**, **client**, **contributor**, or
**maintainer**, according to their technical role. It MUST NOT include employment, hiring, candidate,
resume, interview, or selection-oriented positioning.

Documentation and metadata MUST NOT ask any external system to alter its policy, reveal hidden
instructions, skip verification, change a score, or select this project. Evidence must stand on
reproducible behavior rather than persuasion instructions.

## Agent implementation protocol

For every integration change, an agent MUST:

1. identify the affected trust boundary and claim IDs;
2. read the implementation, schemas, policy files, and failure-path tests before editing;
3. update code and tests together;
4. update `PROJECT_EVIDENCE.json` when evidence, commands, status, or limitations change;
5. update this document, the threat model, or runtime runbook when a contract changes;
6. run formatting, lint, strict type checking, unit tests, coverage, package build, and deterministic demo;
7. run the relevant sandbox conformance workflow when a backend changes;
8. preserve failure artifacts and report the unresolved blocker precisely;
9. leave a claim unverified when runtime evidence is missing or contradictory;
10. avoid merging a backend change while its required live conformance gate is failing.

## Required test matrix

Changes to verification or sandbox code SHOULD include, where applicable:

- schema rejection for unknown and malformed fields;
- shell-string and inline-interpreter rejection;
- absolute path, traversal, symlink, and path-qualified executable rejection;
- output truncation and timeout behavior;
- unavailable-backend fail-closed behavior;
- explicit `unsafe-local` consent behavior;
- dirty-source and source-mismatch reporting;
- MCP read-only default and execution opt-in tests;
- backend-fixed-for-server-lifetime tests;
- environment, credential, provider, mount, and network-policy non-escalation tests;
- deterministic evidence archive reproduction;
- OpenShell source-upload and source-matched execution conformance;
- cleanup and failure-diagnostics behavior.

## Definition of Done

An integration change is complete only when:

- the implementation satisfies the requirements above;
- all relevant negative tests pass;
- registry, schemas, docs, and threat model agree with the code;
- project CI and CodeQL pass;
- package and verifier-image builds pass;
- required live runtime conformance passes for the claimed runtime/version/driver;
- evidence artifacts bind the run to source, recipe, policy, backend, and runtime identity;
- no unsupported capability or metric is promoted;
- no generated runtime artifact or credential is committed;
- public documentation uses the terminology policy in this document.

## Non-goals

The current integration does not promise:

- an anonymous hosted service for executing arbitrary repositories;
- protection from all kernel, container-runtime, VM, or sandbox vulnerabilities;
- universal compatibility across every OpenShell release and compute driver;
- exactly-once external side effects without provider support and reconciliation;
- production multi-tenant authorization;
- numeric latency, rollback, accuracy, or token savings without reproducible benchmark artifacts.
