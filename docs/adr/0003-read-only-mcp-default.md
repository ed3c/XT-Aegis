# ADR 0003: Keep the initial MCP adapter read-only

- Status: Accepted
- Date: 2026-08-09

## Context

A remote mutating agent tool needs authenticated identity, authorization, approval binding, egress
control, secret isolation, idempotency, deployment hardening, and incident response. The MVP does not yet
satisfy those requirements.

## Decision

The optional MCP server exposes project capability and limitation metadata only. It uses the official SDK
abstraction, stateless HTTP mode, JSON responses, and localhost binding. No mutating tool is registered.

## Consequences

- Automated reviewers can inspect a bounded machine-readable surface.
- The architecture does not overstate remote execution readiness.
- A mutating adapter requires a new ADR and all roadmap exit criteria.
