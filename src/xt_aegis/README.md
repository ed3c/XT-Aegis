# `xt_aegis` Package

## Component map

| Area | Responsibility |
|---|---|
| `models.py`, `verification_models.py` | strict typed contracts |
| `proposals.py` | provider-neutral proposals and trusted action-envelope construction |
| `providers/ollama.py` | optional loopback-only Ollama response adapter and bounded HTTP transport |
| `skill.py` | SKILL YAML-front-matter compilation |
| `policy.py` | provenance, path, command, and network-intent policy |
| `workspace.py` | owned workspace and snapshot transaction |
| `runner.py` | deterministic action/assertion/rollback flow |
| `checkpoint.py`, `events.py` | durable state, replay, approval, and audit evidence |
| `verification.py` | registry validation, backend planning/execution, evidence packing |
| `mcp_server.py` | read-only discovery plus explicit local verification mode |
| `demo_assets/`, `verification_assets/` | packaged fixtures and mirrored contracts |

## Boundary

The model or caller proposes. This package validates, authorizes, executes, checks, persists, or rejects.
Retrieved prose never becomes control-plane authority by instruction alone.

See [`AGENTS.md`](AGENTS.md), root architecture, threat model, and evidence registry.
