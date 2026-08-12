# Intent, Issue, PR, Eval, and Evidence Traceability

This index lets a human or Worker Agent reconstruct project intent without relying on conversation memory.
It records the path from source intent to controlling document, issue, branch/PR, evals, evidence state,
and known limitation. An index entry is not execution authority and does not prove its claim.

## Trace path

```text
source intent
  -> stable INTENT ID
  -> controlling document
  -> eval-first issue
  -> branch and PR lineage
  -> owned paths
  -> eval IDs and evidence
  -> status and limitation
```

Update this file in the same reviewable PR whenever a source, owner, branch parent, PR base, eval, evidence
level, or capability status changes.

## Status vocabulary

| Status | Meaning |
|---|---|
| `current` | Implemented or accepted on `main`, supported only to the stated evidence level. |
| `merged contract` | Documentation or repository tooling is accepted on `main`; target/live evidence may still be pending. |
| `under review` | Exists only in an open PR or unmerged branch. |
| `planned` | Required behavior is specified, but no accepted implementation exists on `main`. |
| `unverified` | An implementation, adapter, or exploratory result exists, but its claimed profile lacks accepted reproducible evidence. |
| `deployment-blocked` | Repository-side tooling exists, but real unattended use is prohibited until an exact live profile passes. |
| `unsupported` | A required backend or protection is unavailable; no weaker automatic fallback is permitted. |

## Intent index

| Intent | Requirement | Controlling source | Issue / PR / branch | Primary evals | Status | Limitation or next gate |
|---|---|---|---|---|---|---|
| `INTENT-001` | Bind approvals and idempotency to a versioned canonical request and policy identity. | [`CODING_AGENT_HARNESS.md`](CODING_AGENT_HARNESS.md), [`HARNESS_EVALS.md`](HARNESS_EVALS.md), #24 | #25; PR #31 `agent/harness-request-identity-exit-contract` | `EVAL-IDENTITY-*`, #25 substitution/replay cases | `under review` | PR #31 must rebase onto current `main`, preserve merged contracts, and rerun full CI/evidence checks. |
| `INTENT-002` | Honor declared `expected_exit_codes` for command actions while preserving assertion and rollback semantics. | [`CODING_AGENT_HARNESS.md`](CODING_AGENT_HARNESS.md), #28 | #28; PR #31 | `EVAL-EXEC-*`, #28 zero/non-zero/timeout/signal/postcondition cases | `under review` | Shares PR #31's rebase and evidence gate; no `main` capability is claimed. |
| `INTENT-003` | Limit model/provider output to a bounded proposal; trusted code constructs the execution envelope. | [`CODING_AGENT_HARNESS.md`](CODING_AGENT_HARNESS.md), ADR 0005, #26 | #26; parked `agent/harness-proposal-adapter` branch | `EVAL-PROPOSAL-*` | `planned` | Provider failures, override attempts, size/encoding limits, and exact-profile metadata must pass. |
| `INTENT-004` | Add a finite diagnose-repair controller outside `HarnessRunner` with explicit stop conditions. | [`CODING_AGENT_HARNESS.md`](CODING_AGENT_HARNESS.md), [`HARNESS_EVALS.md`](HARNESS_EVALS.md), #29 | #29; blocked by #25 and #26 | `EVAL-CONTROLLER-*` | `planned` | Policy, approval, infrastructure, baseline, recovery, repeated-cycle, and budget failures remain terminal. |
| `INTENT-005` | Route mutating command actions through a conformant strong-isolation backend. | [`THREAT_MODEL.md`](THREAT_MODEL.md), [`CODING_AGENT_HARNESS.md`](CODING_AGENT_HARNESS.md), #27 | #27; live runtime evidence also tracked by #12 | `EVAL-ISOLATION-*`, #12 adversarial matrix | `planned` | Workspace rollback must never be described as host or OS containment. |
| `INTENT-006` | Make OpenShell auto-selection depend on execution-equivalent readiness and typed infrastructure verdicts. | [`OPENSHELL.md`](OPENSHELL.md), [`INTEGRATION_REQUIREMENTS.md`](INTEGRATION_REQUIREMENTS.md), #30 | #30; related #12; PR #23 advances source binding only | `EVAL-READINESS-*`, live version-pinned smoke | `planned` | PR #23 does not close readiness or mutation-isolation work. |
| `INTENT-007` | Measure first-pass success, post-repair success, Harness-specific uplift, mutation persistence, latency, cost, tokens, retries, and stop reasons separately. | [`HARNESS_EVALS.md`](HARNESS_EVALS.md), [`BENCHMARKS.md`](BENCHMARKS.md), #11, #24 | #11 and #24 | `EVAL-BENCH-*` | `unverified` | Exploratory local results are not universal or accepted profile claims; failed and timed-out trials remain raw evidence. |
| `INTENT-008` | Separate model correctness, orchestration effect, and safety/failure-containment effect. | [`CODING_AGENT_HARNESS.md`](CODING_AGENT_HARNESS.md), ADR 0005 | #35; merged PR #40; implementation evidence remains #11/#24 | `EVAL-HARNESS-05`, `EVAL-BENCH-*` | `merged contract` | Measurement rules are accepted; model-backed uplift remains unverified. |
| `INTENT-009` | Preserve failed, timed-out, unsupported, and negative-result evidence. | [`EVALS.md`](EVALS.md), [`HARNESS_EVALS.md`](HARNESS_EVALS.md), [`EVIDENCE.md`](EVIDENCE.md) | #33/#35; merged PRs #38/#40 | `EVAL-COMMON-03`, `EVAL-HARNESS-05` | `current` | Raw model/runtime artifacts remain with their owning implementation/evidence issues. |
| `INTENT-010` | Scope security, correctness, latency, compatibility, and supply-chain claims to exact source/runtime profiles. | [`EVALS.md`](EVALS.md), [`THREAT_MODEL.md`](THREAT_MODEL.md), [`GIT_TOWN_LICENSE.md`](GIT_TOWN_LICENSE.md) | merged PRs #38/#41; #11, #12, #44 retain live gates | `EVAL-COMMON-04`, `EVAL-GIT-LIVE-*` | `current` | The rule is current; individual model/runtime/Worker profiles remain unverified or blocked until evidence passes. |
| `INTENT-011` | Require eval-first issues and PRs with explicit evidence status. | [`EVALS.md`](EVALS.md), [`ISSUE_PR_CONTRACT.md`](ISSUE_PR_CONTRACT.md) | #33/#37; merged PRs #38/#42 | `EVAL-FOUNDATION-*`, `EVAL-META-*` | `current` | New work uses the merged issue form and PR lineage/evidence template. |
| `INTENT-012` | Provide local directory routing, source-of-truth, data-flow, and escalation instructions. | root [`AGENTS.md`](../AGENTS.md), local `README.md`/`AGENTS.md` files | #34; merged PR #39 | `EVAL-DIR-*` | `current` | Scoped guides may narrow root rules but may not broaden authority. |
| `INTENT-013` | Make stacked-branch lineage explicit and machine-readable for parallel Workers. | [`STACKED_PRS.md`](STACKED_PRS.md), [`ISSUE_PR_CONTRACT.md`](ISSUE_PR_CONTRACT.md) | #33/#36/#37; merged PRs #38/#41/#42 | `EVAL-FOUNDATION-06`, `EVAL-GIT-09`, `EVAL-META-02` | `merged contract` | The committed `scripts/git-town/stack.tsv` is header-only; no active stack is authorized. |
| `INTENT-014` | Use an exact permissively licensed Git Town release with license and artifact identity gates. | [`GIT_TOWN_LICENSE.md`](GIT_TOWN_LICENSE.md), `scripts/git-town/git-town.lock`, third-party notice | #36; merged PR #41 | `EVAL-GIT-03`, `EVAL-GIT-04` | `merged contract` | MIT removes a proprietary-service dependency; it does not guarantee zero legal, patent, trademark, supply-chain, security, or operational risk. |
| `INTENT-015` | Provide Bash-only foreground/background non-interactive stack synchronization that fails closed. | [`STACKED_PRS.md`](STACKED_PRS.md), [`scripts/git-town/README.md`](../scripts/git-town/README.md) | #36; merged PR #41; live acceptance #44 | `EVAL-GIT-01..10`, `EVAL-GIT-LIVE-01..12` | `deployment-blocked` | Repository fixture and CI passed; exact binary, ShellCheck, real forge/conflict/race/safe-force/secret evidence remains #44. |
| `INTENT-016` | Allow multiple Worker Agents only with disjoint path ownership and named conflict owners. | root [`AGENTS.md`](../AGENTS.md), [`ISSUE_PR_CONTRACT.md`](ISSUE_PR_CONTRACT.md) | #33/#37; merged PRs #38/#42 | `EVAL-FOUNDATION-*`, `EVAL-META-03`, `EVAL-META-04` | `current` | Scope expansion requires an issue update before editing. |
| `INTENT-017` | Bind external verification to the user-selected source revision and preserve stricter integration requirements. | [`INTEGRATION_REQUIREMENTS.md`](INTEGRATION_REQUIREMENTS.md), [`OPENSHELL.md`](OPENSHELL.md), #12 | PR #23 `fix/openshell-source-bound-verification` | PR #23 CI and live source-matched OpenShell conformance | `under review` | PR #23 must rebase onto current `main` and retain stricter source-binding requirements. |
| `INTENT-018` | Keep repository prose, issues, retrieved memory, and model text outside execution authority. | root [`AGENTS.md`](../AGENTS.md), [`THREAT_MODEL.md`](THREAT_MODEL.md), [`PROMPT_INJECTION.md`](PROMPT_INJECTION.md) | established on `main`; reinforced by merged PRs #38–#42/#46 | `EVAL-FOUNDATION-08`, policy/negative tests | `current` | External integrations still own correct provenance and authority separation. |
| `INTENT-019` | Accept one exact Git Town v24.0.0 Worker image before real XT-Aegis unattended use. | [`GIT_TOWN_LICENSE.md`](GIT_TOWN_LICENSE.md), [`STACKED_PRS.md`](STACKED_PRS.md), #44 | #44; future evidence PR limited to `docs/evidence/git-town-worker/v24.0.0/**` | `EVAL-GIT-LIVE-01..12` | `deployment-blocked` | No scheduled/background Worker may operate on a real XT-Aegis checkout until the exact profile is accepted. |
| `INTENT-020` | Reconcile the completed documentation program without promoting runtime claims. | root [`AGENTS.md`](../AGENTS.md), root [`README.md`](../README.md), this index, [`docs/README.md`](README.md) | #45; merged PR #46; parent #32 closed | `EVAL-CLOSEOUT-01..08` | `current` | Documentation routing is complete; PRs #23/#31, issues #24–#30/#11/#12, and live Worker #44 remain separate work. |
| `INTENT-021` | Package the Git Town adoption and unattended-worker rules as a repository-portable system prompt. | [`prompts/git-town-repository-bootstrap/README.md`](prompts/git-town-repository-bootstrap/README.md), ADR 0006 | #49; PR #50; `agent/git-town-bootstrap-prompt-pack` | `EVAL-PROMPT-01..12` | `under review` | The prompt defaults to assessment, contains no target-specific live identity, and cannot authorize adoption or deployment merely by being copied. |

## Documentation-first program

| Outcome | Issue | PR | Main paths | State |
|---|---:|---:|---|---|
| Agent reading order, precedence, eval foundation, design notes | #33 | #38 | root entry points and docs routing/evals/traceability/design | merged |
| Directory-local routing and scoped Agent instructions | #34 | #39 | directory `README.md`/`AGENTS.md` files | merged |
| Harness trust boundary, failure taxonomy, eval matrix | #35 | #40 | Harness docs and ADR 0005 | merged |
| Pinned Git Town and fail-closed Bash stack contract | #36 | #41 | config, Git Town docs/scripts, third-party notice | merged; live deployment blocked by #44 |
| Eval-first issue form, PR template, molecular work-slice contract | #37 | #42 | issue/PR metadata and contract | merged |
| Program status reconciliation | #45 | #46 | root/index Markdown files | merged; #32 and #45 closed |

These PRs did not add or modify XT-Aegis Python product behavior.

## Reusable prompt package

Issue #49 owns the portable package under
[`docs/prompts/git-town-repository-bootstrap/`](prompts/git-town-repository-bootstrap/).

The package must remain:

- target-repository agnostic;
- read-only by default;
- explicit about write authorization;
- version-aware rather than copying XT-Aegis Git Town keys blindly;
- eval-first and idempotent;
- strict about license, checksum, lineage, dedicated checkout, semantic conflict, and recovery;
- separate from exact-binary/live-worker qualification.

Acceptance of the prompt package does not accept Git Town in another repository.

## Open implementation and evidence work

| Work | Current state | Required action |
|---|---|---|
| PR #23 `fix/openshell-source-bound-verification` | open and requires rebase | Owner reconciles root/integration docs, preserves source binding, reruns implementation and live-profile evals. |
| PR #31 `agent/harness-request-identity-exit-contract` | draft/open and requires rebase | Owner removes stale duplicate prose, preserves merged Harness contract, reruns #25/#28 and full CI/evidence. |
| `agent/harness-proposal-adapter` | parked branch, no accepted PR | Resume only from #26's eval-first scope after dependencies are reconciled. |
| Issue #44 live Git Town Worker acceptance | open | Exact-profile evidence remains path-disjoint; deployment stays blocked. |
| Issues #24–#30, #11, #12 | open or planned evidence/implementation | Follow their dependency order and accepted Harness/runtime eval contracts. |

Documentation or prompt Workers MUST NOT force-update these code branches or claim their conflicts are
resolved.

## Active stack state

The committed [`scripts/git-town/stack.tsv`](../scripts/git-town/stack.tsv) contains its header and no
active rows. Therefore:

- no unattended XT-Aegis stack synchronization is authorized;
- `verify-stack.sh`, foreground sync, and background sync fail before mutation;
- future rows may be added only after open eval-first PRs exist and their bases match the reviewed graph;
- merged or closed PR rows are removed immediately;
- a dedicated Worker checkout contains only manifest-declared branches and parents.

The disposable fixture writes synthetic rows solely for orchestration tests.

## Claim-change rule

A stronger product/runtime claim requires the same PR to contain or link:

- implementation within a bounded trust boundary;
- positive, negative, failure, migration, and recovery tests required by its issue;
- a reproducible recipe or raw artifact for the exact profile;
- explicit limitations and non-goals;
- matching architecture, threat model, roadmap, schema, and `PROJECT_EVIDENCE.json` changes where applicable.

Documentation completion, a prompt package, generic green CI, adapter construction, a fake-client fixture,
or one local model run is not enough to promote runtime, isolation, correctness-uplift, performance,
compatibility, deployment, or production claims.
