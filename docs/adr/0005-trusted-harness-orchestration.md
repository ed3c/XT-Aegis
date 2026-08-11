# ADR 0005: Keep coding-agent orchestration outside the deterministic runner

- Status: Proposed
- Date: 2026-08-11
- Intent IDs: `INTENT-001`–`INTENT-010`
- Owning issue: #35

## Context

The current runner executes one validated action and produces policy, assertion, rollback, checkpoint, and
event evidence. Rollback can contain failed workspace mutations, but it does not diagnose failures,
re-prompt a model, compare candidates, or improve a model's task-solving ability by itself.

Asking a model to emit the complete action/control schema spends model capacity on security-sensitive
bookkeeping and permits untrusted output to shape identity, policy, approval, and execution authority.

## Decision

Add an explicit experimental orchestration layer around, not inside, the deterministic runner.

- Providers emit bounded code/change proposals and limited metadata.
- Trusted adapters construct the full execution envelope.
- A controller classifies structured outcomes and performs only bounded, policy-respecting repairs.
- Changed proposals receive changed request and approval/idempotency identities.
- Required isolation and backend readiness fail closed.
- Every attempt and terminal stop is preserved as evidence.

`HarnessRunner` remains a deterministic single-request authority boundary.

## Alternatives

### Put retry logic inside `HarnessRunner`

Rejected because it mixes probabilistic provider behavior with authorization, execution, and recovery,
making failure semantics and evidence harder to inspect.

### Let the model emit the full `ActionRequest`

Rejected because control-plane identity, provenance, policy, assertions, approval, backend, and budgets
must not be model authority.

### Treat rollback as sufficient coding improvement

Rejected because containment and task correctness are different metrics.

### Retry every failure

Rejected because security, approval, baseline, infrastructure, and recovery failures must be terminal.

## Consequences

- Provider adapters and controllers remain optional and experimental.
- Deterministic fake providers can cover transitions without a live model.
- Model-backed claims require pinned profiles and raw artifacts.
- More explicit schemas and evidence are required.
- The mutation plane must gain strong isolation before broad autonomous execution claims.
- Existing callers can continue using the deterministic runner directly.

## Promotion gate

This ADR becomes Accepted only after the Harness contract and eval matrix are reviewed and the relevant
issues adopt their evals. Acceptance does not mean the provider, controller, isolation, or benchmark
implementation is complete.
