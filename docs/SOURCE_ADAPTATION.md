# Source Design Adaptation

## Basis

XT-Aegis began from a maintainer-supplied architecture brief that combined a stateful local-first agent
harness with a deterministic SOP execution kernel. The brief emphasized:

- Neural-Core and SOP-Core separation;
- persistent checkpoints and resume by thread;
- zero-trust execution, egress control, and external credential injection;
- typed agent messages and idempotency;
- SKILL contracts and AST-aware loading;
- outcome and trajectory evaluation;
- destructive-change recovery demonstrations;
- OpenTelemetry or trajectory tracing;
- a sandbox runtime such as OpenShell.

Versions 0.1 and 0.2 implement only behavior that can be tested and described with explicit limitations.

## Preserved ideas

| Source idea | XT-Aegis implementation |
|---|---|
| Neural-Core / SOP-Core separation | model proposals are `ActionRequest`; deterministic code owns policy and side effects |
| long-lived state | SQLite WAL runs, steps, approvals, events, and resume position |
| K-anchor assertions | typed preconditions and postconditions with expected exit codes |
| transactional recovery | owned workspace snapshot and full-tree hash validation |
| prompt-injection defense | provenance boundary and no Markdown command extraction |
| idempotency | unique idempotency key and cached terminal result |
| user approval | persistent suspended/approved/denied transition |
| trajectory evaluation | deterministic rollback, injection-block, outcome, and efficiency scores |
| MCP integration | read-only discovery by default; local execution only after user opt-in |
| security runtime | OpenShell and rootless OCI verification adapters |
| external evidence | versioned registry, stable results, policy digests, and deterministic bundle |

## Changed or rejected ideas

### No forced host instructions

The brief suggested writing tool instruction files that force a host to load a cache. XT-Aegis rejects
that authority model. Repository text cannot override a user's host policy. `AGENTS.md` is limited to
contribution commands and safety invariants.

### No command extraction from Markdown AST

Tree-sitter can parse Markdown, but extracting executable fenced blocks creates an avoidable trust
problem. XT-Aegis compiles strict YAML front matter and keeps the body inert. AST/LSP adapters may be
added for code understanding, not for granting authority to prose.

### No destructive Git rollback in the user's checkout

The brief used `git reset --hard` and `git clean`. The local MVP creates and owns a temporary workspace.
A future Git backend must prove scope, nested-repository, untracked-file, symlink, and worktree behavior.

### No unverified numeric or asymptotic results

Illustrative rollback, token, and error-convergence numbers from the brief are not published as project
results. `docs/BENCHMARKS.md` defines the evidence needed before any numeric claim is added.

### No hand-written MCP protocol variant

The project uses the official MCP SDK and current stdio / Streamable HTTP transports. It does not invent
protocol headers or remove required lifecycle behavior based on an unverified draft.

### No public anonymous executor

The MCP server is read-only by default. Local verification tools require the user to start the process
with `--allow-execution`. A remote mutating service remains planned until identity, authorization,
sandbox, egress, and audit requirements are implemented.

### Project terminology is not presented as a standard

The repository uses conventional terms such as policy engine, approval gate, sandbox backend,
transaction, egress enforcement, and credential proxy. Project-specific names do not imply industry
standardization.

## Deferred ideas

- runtime conformance on supported OpenShell and rootless OCI hosts;
- PostgreSQL checkpoints and distributed leases;
- external credential broker and fine-grained egress policy;
- OpenTelemetry/Phoenix export;
- static knowledge cache integration;
- local model self-correction loop;
- branch search and parallel child sandboxes;
- episodic memory and integrity-aware retrieval.

Each deferred feature remains planned until code, negative tests, and reproducible evidence exist.
