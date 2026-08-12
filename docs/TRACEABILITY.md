# Intent, Issue, PR, Eval, and Evidence Traceability

This index lets a human or Worker Agent reconstruct project intent without relying on conversation memory.
It records the path from source intent to owning document, issue, branch/PR, evals, evidence state, and
known limitation. An index entry is not execution authority and does not prove its claim.

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

When any link changes, update this file in the same reviewable PR. Do not silently replace an open gap
with optimistic prose.

## Status vocabulary

| Status | Meaning |
|---|---|
| `current` | Implemented on `main` and supported only to the stated evidence level. |
| `merged contract` | Documentation or repository tooling is accepted on `main`; runtime/live-profile evidence may still be pending. |
| `under review` | Exists only in an open PR or unmerged branch. |
| `planned` | Required behavior is specified, but no accepted implementation exists on `main`. |
| `unverified` | An implementation, adapter, or exploratory result exists, but the claimed profile or measurement lacks accepted reproducible evidence. |
| `deployment-blocked` | Repository-side tooling exists, but real unattended use is prohibited until its exact live profile passes. |
| `unsupported` | A required backend or protection is unavailable; no weaker automatic fallback is permitted. |

## Intent index

| Intent | Requirement | Controlling source | Issue / PR / branch | Primary evals | Status | Limitation or next gate |
|---|---|---|---|---|---|---|
| `INTENT-001` | Bind approvals and idempotency to a versioned canonical request and policy identity. | [`CODING_AGENT_HARNESS.md`](CODING_AGENT_HARNESS.md), [`HARNESS_EVALS.md`](HARNESS_EVALS.md), #24 | #25; PR #31 `agent/harness-request-identity-exit-contract` | `EVAL-IDENTITY-*`, #25 negative substitution/replay cases | `under review` | PR #31 is currently non-mergeable against current `main`; its owner must rebase, preserve the merged docs contract, and rerun full CI/evidence checks. |
| `INTENT-002` | Honor declared `expected_exit_codes` for command actions and preserve rollback/assertion semantics. | [`CODING_AGENT_HARNESS.md`](CODING_AGENT_HARNESS.md), #28 | #28; PR #31 | `EVAL-EXEC-*`, #28 zero/non-zero/timeout/signal/postcondition cases | `under review` | Shares the PR #31 rebase and evidence gate; no `main` capability is claimed yet. |
| `INTENT-003` | Keep model/provider output limited to a bounded proposal; trusted code constructs the execution envelope. | [`CODING_AGENT_HARNESS.md`](CODING_AGENT_HARNESS.md), ADR 0005, #26 | #26; parked `agent/harness-proposal-adapter` branch, no accepted PR | `EVAL-PROPOSAL-*` | `planned` | Provider failures, extra-field override attempts, size/encoding limits, and exact-profile metadata must pass before merge. |
| `INTENT-004` | Add a finite diagnose-repair controller outside `HarnessRunner` with explicit stop conditions. | [`CODING_AGENT_HARNESS.md`](CODING_AGENT_HARNESS.md), [`HARNESS_EVALS.md`](HARNESS_EVALS.md), #29 | #29; blocked by #25 and #26 | `EVAL-CONTROLLER-*` | `planned` | Policy, approval, infrastructure, baseline, recovery, repeated-cycle, and budget failures remain terminal. |
| `INTENT-005` | Route mutating command actions through a conformant strong-isolation backend. | [`THREAT_MODEL.md`](THREAT_MODEL.md), [`CODING_AGENT_HARNESS.md`](CODING_AGENT_HARNESS.md), #27 | #27; runtime evidence also tracked by #12 | `EVAL-ISOLATION-*`, #12 adversarial matrix | `planned` | Workspace rollback must never be described as host or OS containment. |
| `INTENT-006` | Make OpenShell auto-selection depend on execution-equivalent readiness and typed infrastructure verdicts. | [`OPENSHELL.md`](OPENSHELL.md), [`INTEGRATION_REQUIREMENTS.md`](INTEGRATION_REQUIREMENTS.md), #30 | #30; related #12; PR #23 advances source binding only | `EVAL-READINESS-*`, live version-pinned smoke | `planned` | PR #23 does not close readiness or mutation-isolation work. |
| `INTENT-007` | Measure first-pass success, post-repair success, Harness-specific uplift, mutation persistence, latency, cost, tokens, retries, and stop reasons separately. | [`HARNESS_EVALS.md`](HARNESS_EVALS.md), [`BENCHMARKS.md`](BENCHMARKS.md), #11, #24 | #11 and #24 | `EVAL-BENCH-*` | `unverified` | Exploratory local results are not a universal or accepted profile claim; failed and timed-out trials must remain in raw artifacts. |
| `INTENT-008` | Separate model correctness, orchestration effect, and safety/failure-containment effect. | [`CODING_AGENT_HARNESS.md`](CODING_AGENT_HARNESS.md), ADR 0005 | #35 / merged PR #40; implementation evidence still belongs to #11/#24 | `EVAL-HARNESS-05`, `EVAL-BENCH-*` | `merged contract` | Measurement rules are accepted; model-backed uplift remains unverified. |
| `INTENT-009` | Preserve failed, timed-out, unsupported, and negative-result evidence. | [`EVALS.md`](EVALS.md), [`HARNESS_EVALS.md`](HARNESS_EVALS.md), [`EVIDENCE.md`](EVIDENCE.md) | #33/#35; merged PRs #38/#40 | `EVAL-COMMON-03`, `EVAL-HARNESS-05` | `current` | Raw model/runtime artifacts are still pending under their owning issues. |
| `INTENT-010` | Scope security, correctness, latency, compatibility, and supply-chain claims to exact source and runtime profiles. | [`EVALS.md`](EVALS.md), [`THREAT_MODEL.md`](THREAT_MODEL.md), [`GIT_TOWN_LICENSE.md`](GIT_TOWN_LICENSE.md) | merged PRs #38/#41; #11, #12, and #44 retain live-profile gates | `EVAL-COMMON-04`, `EVAL-GIT-LIVE-*` | `current` | The rule is current; individual model, runtime, and Worker profiles remain unverified or deployment-blocked until their evidence passes. |
| `INTENT-011` | Require eval-first issues and PRs with explicit evidence status. | [`EVALS.md`](EVALS.md), [`ISSUE_PR_CONTRACT.md`](ISSUE_PR_CONTRACT.md) | #33/#37; merged PRs #38/#42 | `EVAL-FOUNDATION-*`, `EVAL-META-*` | `current` | New work must use the merged issue form and PR lineage/evidence template. |
| `INTENT-012` | Provide local directory routing, source-of-truth, data-flow, and escalation instructions. | root `AGENTS.md`, local `README.md`/`AGENTS.md` files | #34; merged PR #39 | `EVAL-DIR-*` | `current` | Scoped guides may narrow root rules but may not broaden authority. |
| `INTENT-013` | Make stacked-branch lineage explicit and machine-readable for parallel Workers. | [`STACKED_PRS.md`](STACKED_PRS.md), [`ISSUE_PR_CONTRACT.md`](ISSUE_PR_CONTRACT.md) | #33/#36/#37; merged PRs #38/#41/#42 | `EVAL-FOUNDATION-06`, `EVAL-GIT-09`, `EVAL-META-02` | `merged contract` | The committed `scripts/git-town/stack.tsv` is header-only; no active stack is authorized. |
| `INTENT-014` | Use an exact MIT-licensed Git Town release with license and artifact identity gates. | [`GIT_TOWN_LICENSE.md`](GIT_TOWN_LICENSE.md), `scripts/git-town/git-town.lock`, third-party notice | #36; merged PR #41 | `EVAL-GIT-03`, `EVAL-GIT-04` | `merged contract` | MIT removes a proprietary-service dependency; it does not guarantee zero legal, patent, trademark, supply-chain, security, or operational risk. |
| `INTENT-015` | Provide Bash-only foreground/background non-interactive stack synchronization that fails closed. | [`STACKED_PRS.md`](STACKED_PRS.md), [`scripts/git-town/README.md`](../scripts/git-town/README.md) | #36 / merged PR #41; live acceptance #44 | `EVAL-GIT-01..10`, `EVAL-GIT-LIVE-01..12` | `deployment-blocked` | Repository-side fake-CLI fixture and CI passed; exact binary, ShellCheck, real GitHub, conflict, remote-race, safe-force, timeout, and secret-canary evidence remain open in #44. |
| `INTENT-016` | Allow multiple Worker Agents only with disjoint path ownership and named conflict owners. | root `AGENTS.md`, [`ISSUE_PR_CONTRACT.md`](ISSUE_PR_CONTRACT.md) | #33/#37; merged PRs #38/#42 | `EVAL-FOUNDATION-*`, `EVAL-META-03`, `EVAL-META-04` | `current` | Scope expansion requires an issue update before editing. |
| `INTENT-017` | Bind external verification to the user-selected source revision and preserve stricter integration requirements. | [`INTEGRATION_REQUIREMENTS.md`](INTEGRATION_REQUIREMENTS.md), [`OPENSHELL.md`](OPENSHELL.md), #12 | PR #23 `fix/openshell-source-bound-verification` | PR #23 CI, live OpenShell source-matched conformance | `under review` | PR #23 is currently non-mergeable against current `main`; its owner must rebase and retain the stricter source-binding requirements. |
| `INTENT-018` | Keep repository prose, issues, retrieved memory, and model text outside execution authority. | root `AGENTS.md`, [`THREAT_MODEL.md`](THREAT_MODEL.md), [`PROMPT_INJECTION.md`](PROMPT_INJECTION.md) | established on `main`; reinforced by merged PRs #38–#42 | `EVAL-FOUNDATION-08`, policy/negative tests | `current` | Integrations outside this repository still own correct provenance labeling and authority separation. |
| `INTENT-019` | Accept one exact Git Town v24.0.0 Worker image before real unattended use. | [`GIT_TOWN_LICENSE.md`](GIT_TOWN_LICENSE.md), [`STACKED_PRS.md`](STACKED_PRS.md), #44 | #44; future evidence PR limited to `docs/evidence/git-town-worker/v24.0.0/**` | `EVAL-GIT-LIVE-01..12` | `deployment-blocked` | No scheduled or background Worker may operate on a real repository checkout until the exact profile is accepted. |
| `INTENT-020` | Reconcile merged documentation-program status without promoting runtime claims. | root `AGENTS.md`, root `README.md`, this index, [`docs/README.md`](README.md) | #45; PR #46 `agent/docs-program-closeout` | `EVAL-CLOSEOUT-01..08` | `under review` | Close #32 only after PR #46 merges and the four entry/index files match actual GitHub state. |

## Documentation-first program map

| Outcome | Issue | PR | Main paths | State |
|---|---:|---:|---|---|
| Agent reading order, source precedence, eval foundation, original design notes | #33 | #38 | root `AGENTS.md`, root `README.md`, docs router/evals/traceability/design notes | merged |
| Directory-local `README.md` and scoped `AGENTS.md` routing | #34 | #39 | directory guide files only | merged |
| Harness trust boundary, failure taxonomy, and pre-implementation eval matrix | #35 | #40 | `CODING_AGENT_HARNESS.md`, `HARNESS_EVALS.md`, ADR 0005 | merged |
| Pinned Git Town and fail-closed Bash stack contract | #36 | #41 | `.git-town.toml`, Git Town docs/scripts/third-party notice | merged; live deployment blocked by #44 |
| Eval-first issue form, PR template, and molecular work-slice contract | #37 | #42 | issue/PR metadata and `ISSUE_PR_CONTRACT.md` | merged |
| Program-status reconciliation | #45 | #46 | four root/index Markdown files | under review |

PRs #38–#42 changed documentation and repository Git tooling only. They did not add or modify XT-Aegis
Python product behavior.

## Open implementation and evidence branches

| Work | Current state | Collision / required action |
|---|---|---|
| PR #23 `fix/openshell-source-bound-verification` | open, non-mergeable; base `main`; head `531a76c43b940b8e5927b52994feafc634b68110` | Owner rebases onto current `main`, reconciles root `AGENTS.md` and integration docs, preserves source-bound verification, reruns all implementation and live-profile evals. |
| PR #31 `agent/harness-request-identity-exit-contract` | draft, open, non-mergeable; base `main`; head `144b30ad215f334cc9916101f2b7e3637574c3d3` | Owner rebases onto current `main`, removes duplicate/stale Harness prose in favor of merged #40 contract, reruns #25/#28 and full CI/evidence checks. |
| `agent/harness-proposal-adapter` | parked branch, no accepted PR | Re-open only from #26's eval-first scope after PR #31 dependencies and merged Harness contract are reconciled. |
| Issue #44 live Git Town Worker acceptance | open | Evidence remains path-disjoint from Python work; deployment stays blocked. |

Documentation Workers MUST NOT force-update these code branches or declare their conflicts resolved.

## Active stack state

The committed [`scripts/git-town/stack.tsv`](../scripts/git-town/stack.tsv) contains its header and no
active rows. This means:

- no unattended stack synchronization is authorized;
- `verify-stack.sh`, foreground sync, and background sync fail before mutation;
- future rows may be added only after open eval-first PRs exist and their bases match the reviewed parent
  graph;
- merged or closed PR rows are removed immediately;
- a dedicated Worker checkout contains only manifest-declared branches and their parents.

The disposable repository fixture writes synthetic rows solely to test orchestration and does not turn the
committed manifest into an active stack.

## Claim-change rule

A claim may move to a stronger state only when the same PR contains or links:

- implementation within a bounded trust boundary;
- positive, negative, failure, migration, and recovery tests required by the issue;
- a reproducible recipe or raw artifact for the exact profile;
- explicit limitations and non-goals;
- matching architecture, threat-model, roadmap, schema, and `PROJECT_EVIDENCE.json` updates where the
  verified product claim changes.

Documentation completion, green generic CI, adapter construction, a fake-CLI fixture, or one local model
run is not sufficient to promote a runtime, isolation, correctness-uplift, performance, compatibility, or
production claim.

## Program closeout boundary

The documentation-first program is operationally complete when PR #46 merges and #32 closes. That
closeout means the repository can route future Agents through accepted intent, path, lineage, and eval
contracts. It does not mean:

- PR #23 or PR #31 is merged;
- issues #24–#30, #11, or #12 are implemented;
- the exact Git Town Worker profile in #44 is accepted;
- the Harness improves model correctness;
- strong mutation isolation, production readiness, or universal safety is verified.
