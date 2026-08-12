# GitHub Actions Workflows

These workflows produce project-operated CI, security, packaging, verification, and release evidence.

## Data flow

```text
commit / PR -> isolated GitHub runner -> checks or build -> status + bounded artifact
release tag -> trusted publishing job -> package / image + provenance
```

## Invariants

- Minimal permissions and explicit OIDC scopes.
- Untrusted pull-request code cannot receive release credentials.
- Build and verification identity must name source revision and dependency/runtime versions.
- Project-operated success is not independent reproduction.
- Actions and downloaded tools follow the repository's supply-chain pinning policy.
- Failures remain visible; do not weaken checks to make a stack green.

See parent [`AGENTS.md`](../AGENTS.md) and root security/evidence documents.
