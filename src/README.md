# Source Packages

`src/` contains installable product code. Documentation-only work does not modify files here unless its
issue explicitly owns implementation.

## Flow

```text
validated contract / request
  -> deterministic policy and runner
  -> owned workspace / checkpoint
  -> result and events
  -> external verification and evidence
```

The package boundary is [`xt_aegis/`](xt_aegis/README.md). See [`AGENTS.md`](AGENTS.md).
