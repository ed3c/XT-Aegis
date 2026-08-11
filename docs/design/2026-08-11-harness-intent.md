# 2026-08-11 Harness Coding-Agent Intent

## Context

XT-Aegis began as an evidence-first deterministic gate around agent-proposed actions. Local exploration
showed that rollback contained failed mutations but did not by itself improve model task success. The
next architecture therefore needs explicit orchestration without moving security-sensitive control-plane
fields into model output.

## Intended boundary

```text
model proposal
  -> trusted envelope
  -> deterministic identity and policy
  -> isolated execution
  -> structured diagnosis
  -> bounded repair or selection
  -> terminal evidence
```

## Decisions

1. The model solves the coding problem and emits bounded code/change content plus limited metadata.
2. Trusted code generates thread/action/idempotency identity, provenance, policy, assertions, approval
   bindings, backend selection, and budgets.
3. Changed proposals receive changed identities; approval and cached results cannot cross payloads.
4. Policy denial, approval mismatch, invalid baseline, infrastructure unavailability, and failed rollback
   are terminal.
5. Candidate execution and postcondition failures may be retryable within finite budgets.
6. Workspace rollback and OS-level containment are separate verdicts.
7. Benchmarks compare direct, equal-feedback, and Harness-controller paths under identical task/model
   conditions and preserve every trial.
8. Negative results are publishable outcomes; they do not justify a universal uplift claim.

## Source links

- [Program PRD #24](https://github.com/ed3c/XT-Aegis/issues/24)
- [Request identity #25](https://github.com/ed3c/XT-Aegis/issues/25)
- [Proposal adapter #26](https://github.com/ed3c/XT-Aegis/issues/26)
- [Strong mutation isolation #27](https://github.com/ed3c/XT-Aegis/issues/27)
- [Command exit semantics #28](https://github.com/ed3c/XT-Aegis/issues/28)
- [Bounded controller #29](https://github.com/ed3c/XT-Aegis/issues/29)
- [OpenShell readiness #30](https://github.com/ed3c/XT-Aegis/issues/30)
- [Benchmark evidence #11](https://github.com/ed3c/XT-Aegis/issues/11)
- [Harness correctness PR #31](https://github.com/ed3c/XT-Aegis/pull/31)

## Unresolved

- provider/profile-specific live evidence;
- strong isolation for the mutation plane;
- execution-equivalent backend readiness;
- authenticated approver identity;
- multi-file planning and branch-and-evaluate selection;
- reproducible model-backed correctness/cost/latency results.

Issue [#35](https://github.com/ed3c/XT-Aegis/issues/35) owns conversion of this intent into a normative
Harness contract and eval matrix.
