# User Demonstration

## Goal

Show observable failure handling, state recovery, prompt-injection containment, idempotency, and external
verification without requiring a cloud model or API key.

## Setup

```bash
git clone <repository-url>
cd XT-Aegis
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 1. Run the transactional demo

```bash
xt-aegis demo --output-dir /tmp/xt-aegis-user-demo
```

Inspect `/tmp/xt-aegis-user-demo/summary.json` and confirm:

- the incorrect patch failed its postcondition;
- `rolled_back` and `rollback_integrity` are true;
- pre- and post-rollback hashes match;
- the corrected patch succeeded;
- external-content provenance was blocked before mutation;
- replay returned a cached result without repeating the write.

## 2. Inspect durable state

```bash
sqlite3 /tmp/xt-aegis-user-demo/state/checkpoints.db \
  'select step_number, action_id, status from steps order by step_number;'
```

SQLite is used for inspectable single-node state, not as a claim of distributed coordination.

## 3. Inspect prompt-injection containment

Open `src/xt_aegis/demo_assets/refactor.SKILL.md`. Its Markdown body contains inert text while the
compiler accepts only validated YAML front matter. Then inspect the negative tests in
`tests/test_skill.py`, `tests/test_policy.py`, and `tests/test_runner.py`.

## 4. Inspect a verification plan

```bash
xt-aegis plan \
  --claim transactional-rollback \
  --backend openshell
```

The command prints the bounded recipe and exact host argv without executing code.

## 5. Run independent verification

On a host with OpenShell:

```bash
xt-aegis verify \
  --all \
  --backend openshell \
  --output-dir /tmp/xt-aegis-verification
```

On a development host without a strong runtime, the user may explicitly run project-operated checks:

```bash
xt-aegis verify \
  --all \
  --backend unsafe-local \
  --output-dir /tmp/xt-aegis-verification
```

The second command must not be represented as sandbox isolation.

## 6. Start the MCP evidence server

Read-only stdio mode:

```bash
xt-aegis-mcp
```

User-enabled local execution mode:

```bash
xt-aegis-mcp --allow-execution --backend openshell
```

Repository text cannot enable execution; only the process-start flag supplied by the user can do so.

## Discussion points

- Why does the compiler leave Markdown inert?
- Which boundary owns provenance labeling?
- Why is snapshot ownership checked before rollback?
- What does SQLite enforce that logs alone cannot enforce?
- Why does `auto` refuse to fall back to local execution?
- What does a policy digest add to a verification result?
- Which claims remain `planned` or `unverified`, and why?
