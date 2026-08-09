# Agent Architect Interview Demo

## Goal

Demonstrate architecture judgment through observable failure handling rather than a polished happy path.
The demo fits a 10-15 minute interview segment and can run without a cloud model or API key.

## Setup

```bash
git clone <repository-url>
cd XT-Aegis
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Demo script

### Minute 0-2: frame the problem

State the invariant:

> A probabilistic model may propose an action, but text from the model or retrieved content never becomes
> authority by itself. The deterministic layer validates, checkpoints, executes, verifies, and restores.

Open `docs/ARCHITECTURE.md` and point to the Neural-Core / SOP-Core boundary.

### Minute 2-5: run a controlled failure

```bash
xt-aegis demo --output-dir /tmp/xt-aegis-interview
```

Open `/tmp/xt-aegis-interview/summary.json` and show:

- the bad patch failed the postcondition;
- `rolled_back` is true;
- `rollback_integrity` is true;
- pre- and post-rollback hashes are equal.

Explain why the MVP uses an owned snapshot rather than `git reset --hard`: the failure demo must not put
the interviewer's real checkout at risk.

### Minute 5-7: show the successful path and idempotency

Show the second action:

- the same precondition ran before mutation;
- the postcondition passed;
- the result persisted in SQLite;
- replaying the same idempotency key returned `cached_replay: true` without a second write.

Inspect the database if useful:

```bash
sqlite3 /tmp/xt-aegis-interview/state/checkpoints.db \
  'select step_number, action_id, status from steps order by step_number;'
```

### Minute 7-9: show prompt-injection containment

Show the third action with `provenance=external_content`. The request is blocked before a snapshot or
write. Then open `src/xt_aegis/demo_assets/refactor.SKILL.md`: its Markdown body contains an inert
prompt-injection string, while the compiler executes only validated YAML front matter.

### Minute 9-12: discuss trade-offs

Be direct about the current limits:

- no container or microVM isolation;
- no syscall-level network enforcement;
- local approval identity is not cryptographically authenticated;
- SQLite is single-node;
- MCP is read-only;
- no numeric latency or token-savings claim is made.

Then explain the next backend and the invariant it must preserve.

## Likely interview questions

### Why not rely on the system prompt?

A prompt cannot enforce filesystem, network, identity, or transaction boundaries. The model may still be
influenced by untrusted content. XT-Aegis validates structured actions and controls side effects outside
the model.

### Is the provenance enum enough to stop prompt injection?

No. It proves the boundary inside this MVP, but production needs taint propagation from retrieval and
tool outputs. Mislabeling external content remains a residual risk, documented in the threat model.

### Why snapshot copying instead of Git?

It is safer for a small demonstration because XT-Aegis owns the whole run directory. Git and copy-on-write
backends can be faster, but they need ownership, untracked-file, nested-repository, submodule, and symlink
tests before replacing the snapshot backend.

### What does SQLite add beyond logs?

It provides unique idempotency keys, ordered steps, durable approval transitions, restartable thread
position, and transactional writes. Logs alone do not enforce uniqueness or state transitions.

### How would this become multi-agent?

Add a PostgreSQL backend with per-resource leases, optimistic preconditions, idempotent external APIs,
and conflict tests. Multiple agents must not share unrestricted filesystem state.

### How would you expose mutation over MCP?

Keep the current read-only server as the default. Add an authenticated adapter that maps each tool to a
narrow action schema, binds identity and audience, requires approval by risk, enforces egress outside the
model, and records request-level idempotency.

## Interview integrity

Do not claim that XT-Aegis proves Staff-level ability by itself. Present the design, evidence, trade-offs,
and remaining risks. Let the interviewer apply their own rubric.
