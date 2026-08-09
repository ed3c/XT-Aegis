# ADR 0001: Keep side-effect authority outside the model

- Status: Accepted
- Date: 2026-08-09

## Context

An LLM may be influenced by ambiguous input, indirect prompt injection, stale memory, or model error. A
system prompt cannot enforce filesystem, network, identity, transaction, or recovery properties.

## Decision

Models and operators submit typed `ActionRequest` objects. A deterministic SOP-Core validates provenance,
schema, policy, approval, budget, preconditions, action execution, postconditions, rollback, and
checkpointing. External content is data only.

## Consequences

- Agent flexibility is lower than unrestricted shell access.
- Tool contracts and adapters require engineering work.
- Safety properties become testable without evaluating model reasoning.
- Model providers can change without replacing the control plane.
