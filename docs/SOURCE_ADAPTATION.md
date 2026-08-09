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
- DevOps refactor demonstrations with rollback;
- OpenTelemetry or trajectory tracing.

Version 0.1 implements the smallest set that can be tested honestly on a local machine.

## Preserved ideas

| Source idea | XT-Aegis implementation |
|---|---|
| Neural-Core / SOP-Core separation | model proposals are `ActionRequest`; deterministic code owns policy and side effects |
| long-lived state | SQLite WAL runs, steps, approvals, events, resume position |
| K-anchor assertions | typed preconditions and postconditions with expected exit codes |
| transactional failure recovery | owned workspace snapshot and full-tree hash validation |
| prompt-injection defense | provenance boundary and no Markdown command extraction |
| idempotency | unique idempotency key and cached terminal result |
| HITL | persistent suspended/approved/denied transition |
| trajectory evaluation | deterministic rollback, injection-block, outcome, and efficiency score |
| MCP integration | optional read-only evidence surface using the official SDK abstraction |

## Changed or rejected ideas

### No "active prompt hijacking"

The brief suggested writing agent instruction files that force tools to load a cache first. This project
rejects that framing. Repository instructions must not try to override a host policy, evaluator, or
reviewer. `AGENTS.md` is scoped to contribution commands and safety invariants only.

### No command extraction from Markdown AST

Tree-sitter can parse Markdown reliably, but extracting executable fenced blocks creates an avoidable
trust problem. XT-Aegis compiles strict YAML front matter and keeps the body inert. AST/LSP adapters may
be added later for code understanding, not for granting authority to prose.

### No destructive Git rollback in the caller's checkout

The brief used `git reset --hard` and `git clean`. The MVP instead creates and owns a temporary workspace.
This is slower but safer for a public demonstration. A Git backend must prove scope, nested-repository,
untracked-file, symlink, and worktree behavior before release.

### No unverified 10 ms, 88%, 90%, or asymptotic claims

The brief used illustrative rollback, token, and error-convergence numbers. XT-Aegis does not publish
them as results. `docs/BENCHMARKS.md` defines the evidence needed before any number enters the README.

### No ad hoc protocol implementation

The brief included hand-written MCP-like HTTP routing. The project uses the official SDK abstraction for
an optional read-only adapter instead of inventing protocol headers or lifecycle behavior. Remote
mutation remains disabled.

### "ZTEP" is project terminology, not a standard

The repository uses conventional terms such as policy engine, approval gate, isolated workspace,
transaction, egress enforcement, and credential proxy. A project-specific acronym must not be presented
as an industry standard.

## Deferred ideas

- PostgreSQL checkpoints and distributed locks;
- container/QuickJS/microVM sandbox adapters;
- external Auth Proxy and syscall-level egress policy;
- OpenTelemetry/Phoenix export;
- OpenWiki/static knowledge cache integration;
- local model self-correction loop;
- branch search and parallel child sandboxes;
- episodic memory and integrity-aware retrieval.

Each deferred feature is listed as planned until code, negative tests, and reproducible evidence exist.
