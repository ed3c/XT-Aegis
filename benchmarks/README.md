# Benchmarks

This directory holds benchmark fixtures and raw, profile-bound result artifacts that satisfy
[`docs/BENCHMARKS.md`](../docs/BENCHMARKS.md). No committed number is authoritative merely because it is
stored here.

## Flow

```text
pinned corpus + source + environment + model/config
  -> benchmark run
  -> raw trials including failures/timeouts
  -> schema validation
  -> profile-specific summary
  -> optional claim-registry update
```

## Required metadata

Commit SHA, dirty state, OS/architecture, Python/runtime versions, dependency identity, filesystem/storage
when relevant, corpus, model/provider, sampling, budgets, seed, exact commands, warmups, trial count,
failures, and limitations.

See [`AGENTS.md`](AGENTS.md).
