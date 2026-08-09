# Changelog

All notable changes to this project are documented here. The format follows Keep a Changelog, and the
project uses Semantic Versioning for published interfaces.

## [Unreleased]

### Changed

- pin the MCP Registry publisher and validate `server.json` in pull requests before release publication.

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
- MIT license, architecture, threat model, prompt-injection policy, evidence registry, ADRs, and open-source contribution files;
- CI, CodeQL, Dependabot, issue templates, and pull-request template.
