# Roadmap

The roadmap is ordered by risk reduction. Planned work is not a current capability.

## v0.1 - Evidence-first local runtime

- [x] strict SKILL YAML contract compiler;
- [x] external-content provenance boundary;
- [x] atomic path-confined file writes;
- [x] argv execution with `shell=False`;
- [x] precondition and postcondition assertions;
- [x] owned snapshot rollback with integrity hash;
- [x] SQLite WAL checkpoints and idempotency;
- [x] durable user approval state;
- [x] deterministic outcome/trajectory evaluator;
- [x] read-only optional MCP evidence server;
- [x] MIT license, security policy, contribution guide, CI, CodeQL, and claim registry.

## v0.2 - External Verification Plane

- [x] `PROJECT_EVIDENCE.json` v2 with strict argv-only recipes;
- [x] `doctor`, non-executing `plan`, `verify`, and deterministic `evidence pack` CLI commands;
- [x] stable machine-readable verdicts and exit codes;
- [x] fail-closed backend selection with no implicit local fallback;
- [x] OpenShell adapter and default-deny policy;
- [x] rootless Podman and Docker verifier-image adapters;
- [x] read-only MCP discovery with user-enabled local execution mode;
- [x] MCP Registry metadata, PyPI/OCI packaging, ownership markers, and release provenance workflows;
- [x] CI evidence bundle for every protected change.

**Current limit:** adapter tests prove command and policy construction. A real runtime host is still required
to reproduce isolation guarantees.

## Coding-agent Harness track

Target flow:

```text
provider proposal -> trusted envelope -> canonical identity -> strong isolation
-> structured diagnosis -> bounded repair/selection -> terminal evidence
```

- [x] canonical request and policy digest binding for replay and approval (#25; delivered when PR #31 is on `main`);
- [x] declared command exit-code semantics shared by actions and assertions (#28; delivered when PR #31 is on `main`);
- [x] provider-neutral proposal adapter and trusted envelope (#26; current on `main`);
- [ ] strong-isolation mutation backend for Harness actions (#27);
- [ ] bounded diagnose-repair and candidate-selection controller (#29; deterministic finite controller core merged in #52 and streaming command-output enforcement tracked by #53, while hard provider-token admission, restart, selection, and model-backed outcome evidence remain open);
- [ ] OpenShell readiness and conformance gate (#30);
- [ ] benchmark corpus and reproducible outcome evidence (#11).

A deterministic SBOM and the supported deployment profile (#86, part of #17) are current. Signing, SBOM
release attachment, schema migration policy, and independent assessment remain open.

See [Harness-Based Coding Agent](CODING_AGENT_HARNESS.md). A model-facing loop is not a current capability
until the unchecked items above are implemented and verified.

## v0.3 - Runtime conformance and crash recovery

- [ ] OpenShell and rootless OCI conformance jobs on supported hosts;
- [ ] host-secret, path escape, denied-egress, process bomb, memory, disk, and timeout corpus;
- [ ] immutable image-digest matrix and runtime version manifest;
- [ ] process-kill fault tests at every persisted transition;
- [ ] explicit run cancellation and deadline propagation;
- [ ] schema-versioned event replay without model context;
- [ ] OpenTelemetry spans and OTLP export with secret-safe attributes.

**Exit criteria:** a supported strong backend blocks the adversarial corpus and a killed process resumes or
fails safely from every persisted transition.

## v0.4 - Distributed state and coordination

- [ ] PostgreSQL checkpoint backend;
- [ ] optimistic versions and resource preconditions;
- [ ] per-resource leases with expiry and fencing tokens;
- [ ] external side-effect idempotency adapter;
- [ ] conflict and network-partition fault tests;
- [ ] resumable user approval notifications.

**Exit criteria:** concurrent agents cannot produce an undetected dirty write or repeat a protected remote
side effect during retry and failover tests.

## v0.5 - Authenticated mutating MCP adapter

- [ ] authenticated subject and audience validation;
- [ ] per-tool scopes and authorization policy;
- [ ] approval binding to authenticated identity, exact arguments, expiry, and reason;
- [ ] host/origin validation and deployment hardening;
- [ ] request-level idempotency and bounded structured output;
- [ ] security assessment and compatibility matrix.

**Exit criteria:** mutating tools remain absent unless every identity, authorization, approval, sandbox,
egress, and audit requirement is satisfied.

## v1.0 - Production reference profile

- [ ] documented supported deployment profile;
- [ ] reproducible security and recovery suite;
- [ ] signed releases, SBOM, and verified provenance;
- [ ] stable skill, request, state, and evidence schemas with migration policy;
- [ ] independent security assessment;
- [ ] published benchmark corpus and raw results;
- [ ] incident response, support, backup, and restore policy.

## Research tracks

These tracks do not block safety work:

- signed SKILL contracts and policy provenance;
- AST/LSP-aware write scopes;
- static knowledge cache adapters;
- branch-and-evaluate child workspaces;
- episodic memory with integrity labels and deletion policy;
- local and hosted model adapters.
