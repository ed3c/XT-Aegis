# Agent Contribution Instructions

These instructions apply only to contributors modifying this repository. They do not grant execution
authority to repository text and do not ask an external system to change its own policy.

## Required reading

Before changing the external verification plane, MCP tools, claim registry, sandbox backends, evidence
artifacts, CI, or release distribution, read these files in order:

1. [`docs/INTEGRATION_REQUIREMENTS.md`](docs/INTEGRATION_REQUIREMENTS.md) — normative integration contract;
2. [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) — assets, trust boundaries, threats, and residual risk;
3. [`docs/EXTERNAL_VERIFICATION.md`](docs/EXTERNAL_VERIFICATION.md) — user-visible verification semantics;
4. [`docs/OPENSHELL.md`](docs/OPENSHELL.md) — OpenShell source binding, image contract, policy, and conformance;
5. [`PROJECT_EVIDENCE.json`](PROJECT_EVIDENCE.json) and `verification/schemas/` — machine-readable claims and recipes.

When documents disagree, preserve the more restrictive safety behavior and resolve the inconsistency in
code, tests, evidence metadata, and documentation within the same change.

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
- Keep verification bound to the source revision selected by the user.
- Do not accept repository-controlled mounts, credentials, providers, network expansion, or arbitrary environment variables.
- Preserve bounded time, CPU, memory, output, and artifact behavior.
- Add a negative or failure-path test for new enforcement logic.
- Update `PROJECT_EVIDENCE.json`, schemas, and the threat model when a claim or trust boundary changes.
- Mark incomplete features as planned or unverified.
- Never commit credentials, private session data, or generated runtime artifacts.
- Never add instructions intended to override a user's external policy.
- Use `user`, `agent`, `client`, `contributor`, or `maintainer` for technical actors; do not add employment or selection-oriented positioning.

## Change protocol

For verification and runtime changes:

1. identify the affected trust boundary and claim IDs;
2. update implementation and negative tests together;
3. update claims, limitations, schemas, and runbooks when behavior changes;
4. run formatting, lint, strict type checks, tests, coverage, package build, and deterministic demo;
5. run the relevant live sandbox conformance workflow when a backend changes;
6. keep the claim unverified and report the blocker when runtime evidence is missing or contradictory;
7. do not merge a backend change while its required conformance gate is failing.

## Change focus

Prioritize correctness, failure handling, runtime boundaries, reproducible evidence, and honest
limitations. Reject changes that broaden side-effect or verification authority without matching policy,
isolation, approval, recovery, and negative tests.
