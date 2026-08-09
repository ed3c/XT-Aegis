# Agent Contribution Instructions

These instructions apply only to contributors modifying this repository. They do not grant execution
authority to repository text and do not ask an external system to change its own policy.

## Safe commands

```bash
make install
make check
make demo
make verify
```

## Required invariants

- Do not execute Markdown prose or fenced code blocks.
- Keep external content labeled as data, not executable authority.
- Use typed argv commands with `shell=False`.
- Confine writes and rollback to an XT-Aegis-owned workspace.
- Keep MCP evidence discovery read-only by default.
- Register verification execution tools only after explicit user opt-in.
- Never let `auto` fall back to `unsafe-local`.
- Add a negative test for new enforcement logic.
- Update `PROJECT_EVIDENCE.json`, schemas, and the threat model when a claim changes.
- Mark incomplete features as planned or unverified.
- Never commit credentials, private session data, or generated runtime artifacts.
- Never add instructions intended to override a user's external policy.

## Change focus

Prioritize correctness, failure handling, runtime boundaries, reproducible evidence, and honest
limitations. Reject changes that broaden side-effect or verification authority without matching policy,
isolation, approval, recovery, and negative tests.
