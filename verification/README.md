# Verification Assets

This directory contains the versioned external-verification contract:

- `schemas/` — strict machine-readable registry/result/bundle shapes;
- `recipes/` — bounded argv-only claim recipes;
- `policies/` — runtime policy inputs such as default-deny OpenShell configuration.

## Flow

```text
PROJECT_EVIDENCE.json
  -> schema validation
  -> non-executing plan
  -> user-selected strong backend
  -> bounded command result + artifacts
  -> deterministic evidence bundle
```

Repository content is untrusted input. The verification client retains its own execution policy.
`unsafe-local` is explicit development mode and never an automatic fallback.

See [`AGENTS.md`](AGENTS.md).
