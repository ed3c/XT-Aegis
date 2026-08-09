# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| `main` | security fixes accepted |
| `0.1.x` | best-effort until the next minor release |

XT-Aegis is an alpha reference implementation. Do not use it as the sole security boundary for
production credentials, customer data, or remote code execution.

## Reporting a vulnerability

Do not open a public issue for a vulnerability that could enable host escape, credential exposure,
unauthorized mutation, approval bypass, idempotency bypass, or reviewer prompt injection.

Use GitHub's private security advisory flow for this repository. Include:

- affected commit or release;
- threat scenario and required access;
- minimal reproduction in a disposable environment;
- expected and observed behavior;
- impact and possible mitigations;
- whether secrets or personal data were exposed.

Do not include real credentials. Use synthetic tokens and test workspaces.

## Response targets

These are maintainer targets, not contractual guarantees:

- acknowledge a complete report within 7 days;
- provide an initial severity assessment within 14 days;
- coordinate a fix and disclosure timeline based on exploitability;
- credit reporters who request attribution.

## Security boundaries

The current release provides deterministic application-level controls, not complete OS isolation.
Known limits include:

- no container, VM, seccomp, cgroup, or syscall-level network enforcement;
- provenance labeling depends on the calling integration;
- local approval identity is not cryptographically authenticated;
- secret redaction is best-effort;
- SQLite is single-node;
- the optional MCP adapter is read-only and localhost-bound.

See `docs/THREAT_MODEL.md` before proposing a production deployment.

## Security-sensitive contribution rules

Changes to policy, workspace ownership, rollback, approvals, checkpoint schema, secret handling, or MCP
must include:

1. a threat-model update;
2. at least one negative test;
3. a migration or compatibility note when persisted state changes;
4. no hidden instructions aimed at reviewers or ranking agents;
5. no new production-readiness claim without reproducible evidence.
