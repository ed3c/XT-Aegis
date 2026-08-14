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
- per-component OpenShell readiness (`executable`, `policy`, `version`, `gateway`) reported by
  `xt-aegis doctor` with the exact reason each component is unavailable;
- a per-run sandbox entry token that proves an OpenShell recipe actually started inside the sandbox, so a
  runtime that never launched is reported as `unsupported` instead of as failed repository claims.
- a protected external side-effect runner that persists intent before dispatch, never repeats a committed
  operation, and records an ambiguous outcome as `unknown` for reconciliation instead of retrying it.
- a deny-by-default admission decision for mutating MCP calls that refuses before anything else when a
  required protection is unavailable, rejects replayed nonces, undeclared tools, missing scopes, and any
  approval that does not cover the exact call. No mutating tool is enabled by it.
- verifiable backup and restore of the durable state: a consistent online copy, a manifest with digest,
  schema version, and per-table row counts, and a restore that verifies everything before it writes.
- resumable approval notification that carries no payload, bounds re-notification per approval, and accepts
  a decision only when subject, action digest, policy version, nonce, and deadline all hold.
- `xt-aegis benchmark`, a deterministic runtime measurement harness that emits a schema-valid, profile-bound
  artifact retaining every raw trial including failures and deadline overruns, plus a CI smoke run that
  enforces no wall-clock threshold.
- a fixed span vocabulary (`run`, `policy.evaluate`, `approval.wait`, `action.execute`, `assertion.check`,
  `workspace.rollback`, `checkpoint.persist`) with an attribute allowlist, a local-only recorder, and an
  optional OpenTelemetry bridge that owns no exporter or endpoint;
- `xt-aegis replay`, which reconstructs an execution timeline from a persisted JSONL trajectory without
  invoking a model or a tool;
- a `schema_version` field on every JSONL trajectory record, with a fail-closed compatibility rule.
- a default-deny egress policy with host canonicalization, private/metadata address rejection, mixed-answer
  and rebinding detection, and redirect denial, plus a credential broker whose injections are single-use
  and bound to one subject, tool, destination, argument digest, reason, and expiry.
- a deterministic candidate-selection rule that disqualifies a candidate which started from a drifted
  baseline, failed its assertions, did not succeed, or could not establish rollback integrity, breaks ties
  by proposal digest so the same candidates always select the same one, and names every rejection.

### Changed

- `auto` selects OpenShell only after an execution-equivalent readiness probe resolves the reviewed version
  and an active gateway through the same environment the sandbox launch uses; an unready gateway now
  produces a typed `unsupported` infrastructure verdict instead of failed repository claims;
- `ProviderAdmission`, a trusted pre-call token-admission contract that declares the expected provider
  profile and the per-call prompt/completion reservation, recorded in every controller result.

### Changed

- the controller now admits every provider call through one gate before it is issued: a call is refused
  when the remaining prompt or completion budget is below the declared reservation, or when a previous
  attempt reported no usage, and each call receives the remaining budget instead of the run total;
- a controller attempt that never reached a provider records `proposal_status` and `provider_profile` as
  `null`, so a refusal is distinguishable from a provider outcome;
- controller runs given a run identifier persist their attempt number, token totals, repair context, and
  cycle counters, and a restart either resumes them or terminates with `recovery_failed`; a changed task,
  run context, budget, or provider admission profile, an unreadable or stale state record, an attempt still
  in flight, and an already-terminal run each refuse without calling the provider;
- cancellation and deadlines are enforced at named execution transitions, and a cancelled or expired
  request is persisted as a terminal `cancelled` or `deadline_exceeded` result that a restart replays
  instead of executing;
- mutating command actions run through an explicit action-execution backend; a contract that declares
  `requires_isolation` is blocked with `isolation_unavailable` before any snapshot when the backend is weak
  or unready, and `auto` never falls back to `unsafe-local`;
- results report `isolation_backend` and `isolation_verdict` separately from `rollback_integrity`, so a
  restored workspace is no longer readable as process containment;
- the canonical request-digest version moved to `1.1` because the skill contract gained `requires_isolation`;
  a record written under `1.0` now mismatches instead of comparing two different meanings;
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
