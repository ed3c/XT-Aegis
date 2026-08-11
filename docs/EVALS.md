# Eval-First Contract

An eval is a falsifiable check with a stable ID, procedure, expected result, and evidence location. Evals
are designed in the issue before implementation and reported in the PR after execution.

## Required issue manifest

```text
Intent IDs:
Outcome:
Owned paths:
Excluded paths:
Dependencies:
Parallel-safe siblings:
Trust/claim impact:
Eval IDs:
  - procedure
  - expected result
  - evidence path
Target branch:
Expected PR base:
Stop and rollback conditions:
```

## Required PR evidence table

| Eval ID | Result | Command or procedure | Evidence | Notes |
|---|---|---|---|---|
| `EVAL-...` | passed / failed / not run / not applicable | exact invocation or review method | artifact/path/log | limitation |

`not run` and `not applicable` require a reason. A checklist without output is not evidence.

## Repository-wide evals

### EVAL-COMMON-01 — path ownership

```bash
git diff --name-only "$BASE"...HEAD
```

Every path must be declared by the issue. Generated/shared files require a named integration owner.

### EVAL-COMMON-02 — diff integrity

```bash
git diff --check "$BASE"...HEAD
```

Expected: no whitespace errors or malformed patch boundaries.

### EVAL-COMMON-03 — no hidden authority

Review changed prose, metadata, fixtures, and tool descriptions.

Expected: no request to override external policy, reveal hidden context, broaden runtime authority, skip
verification, or prefer a project outcome.

### EVAL-COMMON-04 — claim honesty

Expected: implemented, partial, planned, unverified, project-operated, and independently reproduced states
remain distinct. Numeric claims identify exact profiles and raw evidence.

### EVAL-COMMON-05 — traceability

Every changed requirement or claim maps through:

```text
intent -> source -> issue -> branch/PR -> eval -> evidence -> status/limitation
```

### EVAL-COMMON-06 — link and ID integrity

Relative links resolve from the containing file. Intent, ADR, and eval IDs are unique.

### EVAL-COMMON-07 — no unrelated implementation

For a documentation-only issue:

```bash
if git diff --name-only "$BASE"...HEAD | grep -E '\.py$'; then
  echo "unexpected Python change" >&2
  exit 1
fi
```

### EVAL-COMMON-08 — stack lineage

The branch parent, PR base, issue dependency, and stack manifest must agree. Each sibling path set is
disjoint unless the PR names a conflict owner and merge order.

## Domain eval families

| Family | Prefix | Required when |
|---|---|---|
| Documentation foundation | `EVAL-FOUNDATION-*` | root routing, intent, or eval contracts |
| Directory guidance | `EVAL-DIR-*` | local README/AGENTS changes |
| Harness | `EVAL-HARNESS-*` | proposal, controller, mutation, diagnosis, or benchmark design |
| Git Town | `EVAL-GIT-*` | stack configuration or unattended Bash |
| Issue/PR metadata | `EVAL-META-*` | forms, templates, lineage, or evidence reporting |
| Runtime security | issue-specific | authority, isolation, network, credential, approval, idempotency |
| Measurement | issue-specific | latency, tokens, correctness, safety, or outcome claims |

## Evidence rules

- Preserve failed, timed-out, unsupported, and inconclusive results.
- Record commit, dirty state, environment, tool versions, configuration, seed, and exact commands when
  they affect reproducibility.
- Redact credentials and private content before persistence.
- A digest proves integrity, not publisher identity or semantic correctness.
- Project-operated CI is not independent reproduction.
- Missing runtime capability produces `unsupported`, not a weakened fallback.

## Gate order

1. static structure and path ownership;
2. schema/config validation without execution;
3. deterministic unit and negative tests;
4. disposable local integration tests;
5. project-operated CI;
6. user-operated sandbox reproduction;
7. claim promotion for the exact verified profile.

A later gate does not erase a failure at an earlier gate.
