# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| `main` | security fixes accepted |
| `0.2.x` | current alpha line |
| `0.1.x` | best-effort until the next minor release |

XT-Aegis is an alpha reference implementation. Do not use it as the sole security boundary for
production credentials, customer data, or remote code execution.

## Reporting a vulnerability

Do not open a public issue for a vulnerability that could enable host escape, credential exposure,
unauthorized mutation, approval bypass, idempotency bypass, evidence substitution, sandbox-policy bypass,
or external policy manipulation.

Use GitHub's private security advisory flow. Include:

- affected commit or release;
- threat scenario and required access;
- minimal reproduction in a disposable environment;
- selected runtime and policy digest;
- expected and observed behavior;
- impact and possible mitigations;
- whether secrets or personal data were exposed.

Use synthetic credentials and test workspaces only.

## Response targets

These are maintainer targets, not contractual guarantees:

- acknowledge a complete report within 7 days;
- provide an initial severity assessment within 14 days;
- coordinate a fix and disclosure timeline based on exploitability;
- credit reporters who request attribution.

## Security boundaries

The current release provides deterministic application controls and optional external sandbox adapters.
Known limits include:

- the local snapshot backend is not OS isolation;
- OpenShell, Podman, Docker, their daemons, and the host kernel remain external trust boundaries;
- runtime conformance is not yet continuously tested on every supported host;
- provenance labeling depends on the calling integration;
- local approval identity is not cryptographically authenticated;
- secret redaction is best-effort;
- SQLite is single-node;
- MCP execution tools are local opt-in only and remote authentication is not implemented.

See `docs/THREAT_MODEL.md` before proposing a production deployment.

## Security-sensitive contribution rules

Changes to policy, workspace ownership, rollback, approvals, checkpoint schema, verification recipes,
runtime adapters, evidence identity, secret handling, or MCP must include:

1. a threat-model update;
2. at least one negative test;
3. a migration or compatibility note when persisted state changes;
4. explicit user control over new execution authority;
5. no instruction that asks an external system to override its policy;
6. no production-readiness or performance claim without reproducible evidence.
