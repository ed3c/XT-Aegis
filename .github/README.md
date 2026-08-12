# GitHub Project Metadata

## Purpose

This directory contains contribution forms and project-operated automation. It is not runtime authority
for XT-Aegis and does not prove a product claim.

## Inputs and outputs

```text
issues / PR metadata -> review workflow -> GitHub Actions -> project-operated evidence
```

Inputs come from issue/PR contracts, release policy, and repository configuration. Outputs are review
metadata, CI status, artifacts, and release actions.

## Source of truth

- Root [`AGENTS.md`](../AGENTS.md)
- [`docs/EVALS.md`](../docs/EVALS.md)
- [`docs/TRACEABILITY.md`](../docs/TRACEABILITY.md)
- [`SECURITY.md`](../SECURITY.md)
- Local [`AGENTS.md`](AGENTS.md)

## Local evals

Validate issue-form syntax, workflow permissions, immutable action references where required, path
ownership, and the distinction between project-operated CI and independent reproduction.

## Escalate

Stop when a change adds write permissions, secrets, external network destinations, release authority,
untrusted checkout execution, or claim promotion without a dedicated issue and threat-model review.
