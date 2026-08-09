# ADR 0002: Preserve user policy and reject repository-driven authority

- Status: Accepted
- Date: 2026-08-09
- Updated: 2026-08-09

## Context

Repository files are untrusted input to humans, agents, scanners, and MCP hosts. Hidden or visible text
must not ask an external system to ignore its policy, reveal private data, trust a claim, enable execution,
or broaden sandbox authority.

## Decision

XT-Aegis uses evidence-oriented discovery only: accurate package metadata, typed claims, bounded recipes,
negative tests, limitations, and reproducible artifacts. The user retains authority over execution,
backend selection, credentials, and external evaluation policy.

MCP execution tools are absent by default and appear only when the user supplies `--allow-execution` at
process start. Backend `auto` never selects `unsafe-local`.

## Consequences

- Repository content cannot authorize itself.
- Claims remain separable from evidence.
- External clients can inspect plans before execution.
- Contributions that add policy-override instructions are rejected.
- Clear limitations and unsupported states remain visible.
