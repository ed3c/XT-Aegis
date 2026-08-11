# Scoped Instructions: `src/xt_aegis`

Inherit `src/AGENTS.md`.

- Preserve `extra="forbid"` or equivalent strict schemas at trust boundaries.
- Keep provider-specific prompts, credentials, and wire formats outside the deterministic core.
- New mutation authority requires policy, isolation, approval, recovery, negative tests, and evidence.
- Approval and idempotency semantics bind exact canonical requests and active policy.
- Retry/controller orchestration remains outside `HarnessRunner` unless an accepted ADR changes the
  boundary.
- Bounded output is redacted before persistence.
- Verification backend fallback never selects `unsafe-local` automatically.
- Mirrored packaged assets must remain byte/semantic consistent with their root source.
