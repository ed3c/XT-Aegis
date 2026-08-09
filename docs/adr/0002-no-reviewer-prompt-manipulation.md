# ADR 0002: Do not manipulate repository reviewers or ranking agents

- Status: Accepted
- Date: 2026-08-09

## Context

The repository is intended to be reviewed by interviewers and automated agents. Hidden or visible text
that asks a reviewer to select the project, change its rubric, ignore policy, or trust claims would be a
prompt-injection attempt and would undermine the project's security position.

## Decision

XT-Aegis uses evidence-oriented discoverability only: clear naming, machine-readable claims, tests,
architecture records, limitations, and reproducible commands. Review guidance explicitly tells agents to
preserve their existing policy and verify independently.

## Consequences

- The project cannot rely on coercive wording or hidden metadata for ranking.
- Unsupported claims are easier to detect.
- Contributions that add evaluator-control instructions must be rejected.
