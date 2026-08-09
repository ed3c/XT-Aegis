# Roadmap

The roadmap is ordered by risk reduction, not feature count. Planned work is not a current capability.

## v0.1 - Evidence-first local MVP

- [x] strict SKILL YAML contract compiler;
- [x] external-content provenance boundary;
- [x] atomic path-confined file writes;
- [x] argv command execution with `shell=False`;
- [x] precondition and postcondition assertions;
- [x] owned snapshot rollback with integrity hash;
- [x] SQLite WAL checkpoints and idempotency;
- [x] durable human approval state;
- [x] deterministic outcome/trajectory evaluator;
- [x] read-only optional MCP evidence server;
- [x] MIT license, security policy, contribution guide, CI, CodeQL, and claim registry.

## v0.2 - Observability and crash recovery

- [ ] OpenTelemetry spans for policy, approval, action, assertion, rollback, and checkpoint operations;
- [ ] OTLP export with secret-safe attributes;
- [ ] process-kill fault tests at every state transition;
- [ ] explicit run cancellation and deadline propagation;
- [ ] schema-versioned JSONL event format;
- [ ] benchmark runner and raw artifact schema.

**Exit criteria:** a killed process resumes or fails safely from every persisted transition, and traces can
be replayed without model context.

## v0.3 - Strong local isolation

- [ ] container backend with read-only root, dedicated writable mount, non-root user, seccomp, and dropped
  capabilities;
- [ ] CPU, memory, process, disk, and wall-time quotas;
- [ ] default-deny egress proxy and destination allowlist;
- [ ] external credential injection that never exposes secrets to the model or workspace;
- [ ] symlink, mount, archive, and dependency-install adversarial tests.

**Exit criteria:** a malicious allowlisted process cannot read host secrets, escape the workspace, or reach
an unapproved destination in the supported deployment profile.

## v0.4 - Distributed state and multi-agent coordination

- [ ] PostgreSQL checkpoint backend;
- [ ] optimistic state version and resource preconditions;
- [ ] per-resource leases with expiry and fencing tokens;
- [ ] external side-effect idempotency adapter;
- [ ] conflict and network-partition fault tests;
- [ ] resumable HITL notifications.

**Exit criteria:** two agents cannot produce an undetected dirty write or repeat a protected external side
effect during retry and failover tests.

## v0.5 - Authenticated mutating MCP adapter

- [ ] current-spec SDK adapter with stateless request handling;
- [ ] authenticated subject and audience validation;
- [ ] per-tool scopes and authorization policy;
- [ ] approval binding to identity, exact arguments, expiry, and reason;
- [ ] host/origin validation and deployment hardening;
- [ ] request-level idempotency and bounded structured output;
- [ ] security review and compatibility matrix.

**Exit criteria:** mutating tools remain disabled unless every authorization, approval, sandbox, egress,
and audit requirement is satisfied.

## v1.0 - Production reference profile

- [ ] documented supported deployment profile;
- [ ] reproducible security and recovery test suite;
- [ ] signed releases and software bill of materials;
- [ ] stable skill schema and migration policy;
- [ ] independent security assessment;
- [ ] published benchmark corpus and raw results;
- [ ] incident response and support policy.

## Candidate research tracks

These tracks are valuable but should not block safety work:

- signed SKILL contracts and policy provenance;
- AST/LSP-aware write scopes;
- static knowledge cache adapters;
- branch-and-evaluate execution with isolated child workspaces;
- episodic memory with integrity labels and deletion policy;
- model/provider adapters for local and hosted inference.
