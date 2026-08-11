# Scoped Instructions: `tests`

Inherit the root contract.

- Test externally observable behavior and failure states, not only internal call counts.
- Add negative tests for every enforcement change.
- Use synthetic data and secret canaries; never real credentials or production endpoints.
- Preserve deterministic seeds and bounded time/output.
- A test must not weaken policy or use `unsafe-local` to prove isolation.
- Live runtime conformance is separate from adapter unit tests.
- Keep test names and evidence recipes traceable to issues and claim IDs.
