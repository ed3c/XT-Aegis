# ADR 0004: Use an owned snapshot workspace for the MVP

- Status: Accepted
- Date: 2026-08-09

## Context

`git reset --hard` and `git clean` can destroy work when executed in the wrong checkout, miss external
side effects, and behave unexpectedly with nested repositories, submodules, symlinks, and untracked data.
A demonstration project should fail safely on a reviewer's machine.

## Decision

XT-Aegis creates a dedicated run directory, copies a template into an owned workspace, writes a random
ownership marker, and snapshots that workspace before mutation. Rollback is permitted only inside the
owned run root and is verified with a tree hash.

## Consequences

- Snapshot copy cost grows with workspace size.
- The implementation is easy to inspect and safe for small demos.
- Faster Git, container, or filesystem snapshot backends must preserve the ownership invariant.
