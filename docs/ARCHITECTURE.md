# Architecture

## 1. Purpose

XT-Aegis is a deterministic execution and verification boundary for agent-proposed actions. The model may
be probabilistic; authorization, mutation, rollback, and claim verification remain typed and bounded.

The system separates four planes:

- **Neural-Core:** a user or model that proposes a typed action;
- **SOP-Core:** schema validation, provenance policy, user approval, transactional execution, assertions,
  checkpointing, and evaluation;
- **External data plane:** repository text, web pages, issue bodies, tool output, and memory records that
  may contain adversarial instructions but cannot grant authority through text;
- **Verification Plane:** a versioned claim registry, strict recipes, sandbox adapters, MCP discovery, and
  portable evidence bundles.

## 2. Context diagram

```mermaid
flowchart TB
    U[User] --> AP[Typed Action Proposal]
    M[Model / Agent] --> AP
    D[External Data] -->|provenance: external_content| AP
    AP --> XA[XT-Aegis SOP-Core]
    XA --> W[Owned Workspace]
    XA --> DB[(SQLite WAL)]
    XA --> EV[Structured Evidence]
    W --> T[Tests and Assertions]
    EV --> RG[Evidence Registry]
    RG --> VC[Verification Client]
    VC --> SB[OpenShell / Podman / Docker]
    SB --> EB[Evidence Bundle]
```

## 3. SOP-Core components

### `SkillCompiler`

The compiler reads one YAML front-matter block and validates `SkillContract`. The remaining Markdown is
documentation only. A code fence copied from external content cannot silently become a tool invocation.

### `PolicyEngine`

The policy engine validates provenance, action type, unknown fields, file paths, write size, stale-plan
hash, executable allowlist, command fragments, interpreter flags, working directory, and declared network
intent. This is process-level policy, not OS isolation.

### `IsolatedWorkspace`

XT-Aegis creates a run root, copies a template into an owned workspace, and writes a random ownership
marker. Snapshot and restore refuse to act when ownership or path confinement is invalid. A failed action
is considered restored only when the final tree hash equals the pre-action hash.

### `HarnessRunner`

```mermaid
stateDiagram-v2
    [*] --> Received
    Received --> Blocked: schema/policy/budget failure
    Received --> Suspended: user approval required
    Suspended --> Received: approved request resubmitted
    Received --> Snapshot
    Snapshot --> RolledBack: precondition failure
    Snapshot --> Executing: preconditions pass
    Executing --> RolledBack: action failure
    Executing --> Verifying: expected action exit
    Verifying --> RolledBack: postcondition failure
    Verifying --> Succeeded: all postconditions pass
    RolledBack --> Checkpointed
    Succeeded --> Checkpointed
    Blocked --> Checkpointed
    Checkpointed --> [*]
```

The runner does not create an unbounded retry loop. Retry policy belongs to the caller and remains subject
to idempotency and approval checks.

### `CheckpointStore`

SQLite WAL stores run state, ordered steps, terminal idempotent results, user approval transitions,
structured events, and resume position. Distributed coordination is a separate backend with different
failure modes.

## 4. Verification Plane

### `PROJECT_EVIDENCE.json`

The registry uses schema version `2.0`. Implemented claims require a strict `VerificationRecipe` and
expected result. Planned and unverified claims cannot be promoted by execution.

### `verification_models.py`

Pydantic models reject unknown fields and constrain:

- claim identifiers and statuses;
- argv length and non-empty values;
- relative working and artifact paths;
- timeout and output limits;
- default-deny network mode;
- result, source identity, command evidence, and bundle manifests.

### `verification.py`

The verifier:

1. loads and hashes the registry;
2. resolves the user-selected source root;
3. validates executable policy;
4. selects a backend without local fallback;
5. executes one recipe with bounded output and time;
6. records source, registry, recipe, policy, command, and artifact identity;
7. emits one result per claim and an aggregate summary;
8. optionally creates a deterministic evidence archive.

### Backend selection

```mermaid
flowchart LR
    A[backend=auto] --> O{OpenShell available?}
    O -->|yes| OS[OpenShell]
    O -->|no| P{Rootless Podman available?}
    P -->|yes| PO[Podman]
    P -->|no| D{Docker available?}
    D -->|yes| DO[Docker]
    D -->|no| U[Unsupported]
    L[unsafe-local] -->|explicit user choice only| UL[No OS isolation]
```

OpenShell runs the exact recipe through a pinned-capable verifier image with `--from`, policy, CPU,
memory, and `--no-keep` arguments. OCI backends
use a non-root verifier image, no network, read-only source and root filesystems, dropped capabilities,
no-new-privileges, PID/memory/CPU limits, and a bounded tmpfs.

### MCP boundary

The stdio MCP server is read-only by default. It exposes claim discovery, runtime discovery, and plans.
Verification execution tools are registered only when the user starts the local process with
`--allow-execution`. Repository content cannot change that registration decision.

Stateless Streamable HTTP is available for localhost use. A remote deployment requires authenticated
identity, authorization, origin validation, rate limits, audit controls, and a dedicated deployment
threat model.

## 5. Sequence: external verification

```mermaid
sequenceDiagram
    participant U as User or Client
    participant M as MCP / CLI
    participant R as Registry Validator
    participant B as Sandbox Backend
    participant T as Repository Tests
    participant E as Evidence Store

    U->>M: doctor / plan
    M->>R: load + validate + hash registry
    R-->>M: bounded recipe + limitations
    M-->>U: non-executing plan
    U->>M: verify claim + selected backend
    M->>B: exact argv + timeout + network deny
    B->>T: execute inside user-controlled runtime
    T-->>B: bounded exit/output
    B-->>M: command and policy identity
    M->>E: result JSON + artifact hashes
    M-->>U: verdict and stable exit code
```

## 6. Implemented versus planned

| Layer | Implemented now | Remaining work |
|---|---|---|
| Contract | strict YAML front matter | signed policy bundles and migrations |
| Workspace | owned snapshot copy | copy-on-write production profile |
| Process | argv policy, timeout | broader per-tool schemas |
| Network | deny intent; sandbox adapters request no egress | runtime conformance corpus |
| State | SQLite WAL | PostgreSQL, leases, fencing tokens |
| Approval | local durable decision | authenticated identity, expiry, signatures |
| Trace | SQLite + JSONL | OpenTelemetry export |
| Verification | registry v2, CLI, MCP, OpenShell/OCI adapters, evidence bundle | signed release evidence and independent runtime matrix |
| MCP | read-only default; opt-in local execution | authenticated remote mutation adapter |

## 7. Architecture invariants

1. prose never becomes executable authority;
2. unknown schema fields fail closed;
3. external content cannot directly invoke a tool;
4. mutating actions have idempotency keys;
5. high-risk approval is bound to action identity;
6. rollback scope is owned and path-confined;
7. claims identify evidence and limitations;
8. repository text cannot alter the user's external policy;
9. `auto` never selects `unsafe-local`;
10. a verification result identifies source, recipe, runtime policy, and artifacts.
