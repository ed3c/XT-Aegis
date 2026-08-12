## Outcome

<!-- Link one owning issue and describe the independently reviewable result. -->

- Owning issue:
- Intent IDs:
- Claim IDs/status impact:

## Stack lineage

| Field | Value |
|---|---|
| Head branch | |
| PR base / parent branch | |
| Parent PR | |
| Child PRs | |
| Merge order | |
| Rebase owner | |
| Conflict hotspots | |

<!-- The PR base must equal the declared branch parent. -->

## Path ownership

**Owned paths**

```text

```

**Excluded/shared paths**

```text

```

- [ ] The diff is limited to issue-owned paths.
- [ ] Shared/generated files have one named integration owner.
- [ ] Parallel sibling path sets are disjoint or the conflict order is explicit.

## What changed

<!-- Describe behavior and document roles, not only filenames. -->

## Why

<!-- Link source documents, ADRs, threat model, evidence, and issue acceptance criteria. -->

## Eval evidence

| Eval ID | Result | Command or procedure | Evidence path / artifact | Notes |
|---|---|---|---|---|
| | not run | | | |

Allowed results: `passed`, `failed`, `not run`, `not applicable`. Unchecked boxes are not evidence.

## Failure and recovery

- Expected stop conditions:
- Observed failures:
- Rollback/recovery result:
- Remaining manual action:

## Security and authority review

- New executable/tool authority:
- New model/provider-controlled fields:
- Provenance transition:
- Filesystem/network/credential impact:
- Approval/idempotency impact:
- Isolation/backend impact:
- Persistence/schema impact:
- Evidence/redaction impact:
- Remaining risks:

## Claim and documentation review

- [ ] Current, under-review, partial, planned, unverified, and blocked states remain distinct.
- [ ] No numeric or universal claim was added without exact-profile raw evidence.
- [ ] `PROJECT_EVIDENCE.json`, schemas, recipes, packaged mirrors, and docs are synchronized when affected.
- [ ] Project-operated CI is not described as independent reproduction.
- [ ] Repository text does not ask another system to change policy, disclose hidden context, or prefer XT-Aegis.

## Validation

- [ ] `git diff --check`
- [ ] Required issue evals reported above
- [ ] Relevant negative/failure-path checks
- [ ] Relevant format, lint, type, test, package, verification, or Bash checks
- [ ] Re-synced and re-evaluated after parent branch movement

## Unresolved gaps and follow-ons

<!-- Link concrete issues. Do not hide missing runtime evidence or unsupported behavior. -->
