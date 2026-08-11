# Repository Scripts

Scripts provide bounded developer, benchmark, release, or Git-management entry points. They are not part
of model authority and must not turn repository text into commands.

## Areas

- `benchmark.py`: local measurement scaffold governed by `docs/BENCHMARKS.md`.
- `git-town/`: Bash-only stacked-branch worker workflow introduced by issue #36.

## Flow

```text
explicit user / worker invocation -> preflight -> bounded command -> log/evidence -> explicit status
```

See [`AGENTS.md`](AGENTS.md).
