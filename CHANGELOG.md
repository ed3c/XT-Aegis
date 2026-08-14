# Changelog

All notable changes to this project are documented here. The format follows Keep a Changelog, and the
project uses Semantic Versioning for published interfaces.

## [Unreleased]

### Added

- versioned canonical request and policy identities for replay, approval, results, and events;
- SQLite checkpoint schema v2 migration with fail-closed legacy trust records and future-version rejection;
- expiring, exact-request, optional-actor-bound, single-use approvals;
- Harness coding-agent architecture and ordered implementation track;
- provider-neutral strict proposal contracts, trusted action-envelope construction, and a synchronized
  portable proposal JSON Schema;
- an optional loopback-only Ollama adapter with bounded no-proxy/no-redirect stdlib HTTP transport and
  typed refusal, timeout, malformed, oversized, truncated, and provider-error outcomes;
- an argv-only sandbox launcher that confines recipe working directories beneath the uploaded source root;
- a pinned, artifact-producing OpenShell live-conformance workflow for user-triggered and relevant pull-request runs;
- a deny-by-default admission decision for mutating MCP calls that refuses before anything else when a
  required protection is unavailable, rejects replayed nonces, undeclared tools, missing scopes, and any
  approval that does not cover the exact call. No mutating tool is enabled by it.

### Changed

- command actions now honor `CommandSpec.expected_exit_codes` instead of requiring exit code zero;
- action, precondition, postcondition, and terminal evidence record actual and expected exit codes;
- OpenShell verification now uploads the selected checkout into `/workspace`, disables automatic providers,
  uses manual policy approval, and executes the recipe against that source rather than only image-baked code;
- pin the MCP Registry publisher and validate `server.json` in pull requests before release publication.

### Security

- idempotency keys can no longer replay results across changed payloads, paths, arguments, provenance,
  assertions, actors, threads, actions, or policies;
- legacy checkpoint and approval rows without canonical identity fields cannot authorize or replay work;
- model/provider output cannot supply target, identity, provenance, approval, policy, backend, or budget
  authority through the trusted proposal schema and envelope builder;
- Ollama proposal requests reject remote, credential-bearing, redirected, proxied, model-substituted, and
  over-limit response paths before a proposal can become ready.

## [0.2.0] - 2026-08-09

### Added

- evidence registry schema v2 with argv-only bounded recipes;
- `doctor`, `plan`, `verify`, and deterministic `evidence pack` CLI commands;
- stable structured verdicts and process exit codes;
- fail-closed OpenShell, rootless Podman, and Docker backend selection;
- default-deny OpenShell policy and non-root OCI verifier image;
- read-only MCP evidence discovery plus explicit user-enabled local execution mode;
- MCP Registry metadata, ownership markers, and OIDC publication workflow for PyPI and OCI stdio packages;
- verification JSON Schemas, recipe assets, CI evidence archives, and release attestations;
- external verification, OpenShell, and user demonstration documentation.

### Changed

- MCP now defaults to stdio and read-only tools;
- project language consistently uses user-controlled execution and external policy integrity;
- package development dependencies include the official MCP SDK for conformance tests.

## [0.1.0] - 2026-08-09

### Added

- strict YAML-front-matter SKILL compiler;
- typed action requests with provenance labels;
- fail-closed command and file-write policy engine;
- owned snapshot workspace with integrity-checked rollback;
- SQLite WAL checkpoints, idempotency, events, resume position, and approvals;
- deterministic outcome and trajectory evaluation;
- local refactor demonstration with failed patch, rollback, success, injection block, and cached replay;
- optional read-only stateless MCP evidence server;
- MIT license, security policy, contribution guide, CI, CodeQL, and claim registry;
- CI, CodeQL, Dependabot, issue templates, and pull-request template.
