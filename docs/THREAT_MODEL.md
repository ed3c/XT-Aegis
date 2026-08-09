# Threat Model

## Scope

This document covers the repository implementation, including the SOP-Core and External Verification
Plane. It does not treat a Python process allowlist, a container, or an external runtime as protection
against every host-kernel or runtime vulnerability.

## Assets

- source files and execution workspace;
- credentials and environment data outside the workspace;
- checkpoint and idempotency integrity;
- user approval decisions;
- verification registry, recipes, results, and artifact hashes;
- host filesystem, network, runtime daemon, and user accounts.

## Trust levels

| Trust label | Examples | Authority |
|---|---|---|
| Maintainer contract | reviewed YAML front matter, release configuration | may define bounded policy |
| User | local person explicitly creating an action or enabling verification | may propose actions subject to policy |
| Agent proposal | structured model output | may propose, never bypass policy |
| External content | issue text, web page, README, tool result, memory excerpt | data only |
| SOP-Core | deterministic policy, runner, checkpoint, evaluator | enforces action policy |
| Verification client | CLI or MCP process started by the user | validates claims under its own policy |
| Sandbox runtime | OpenShell, Podman, Docker | external isolation boundary with separate risks |

## Primary threats and controls

### T1. Direct or indirect prompt injection

**Scenario:** External text asks the agent or verification client to ignore policy, reveal data, execute a
command, or enable tools.

**Controls:** provenance labeling, strict action schemas, inert Markdown, read-only MCP default, explicit
`--allow-execution`, and verifier-side recipe validation.

**Residual risk:** provenance and taint propagation begin outside this repository. A model may still
propose a harmful schema-valid action; the policy and sandbox must contain it.

### T2. Shell or interpreter injection

**Scenario:** A recipe or action supplies command chaining, a path-qualified executable, or inline code.

**Controls:** argv arrays, `shell=False`, executable allowlists, path-qualified executable rejection,
interpreter inline-code rejection, timeouts, and bounded output.

**Residual risk:** allowlisted tests are still code. Independent verification requires a strong runtime.

### T3. Malicious evidence registry

**Scenario:** Repository metadata attempts to request broad mounts, credentials, environment variables,
network access, arbitrary paths, or shell commands.

**Controls:** registry schema `extra=forbid`, relative path validation, one `deny` network mode, no registry
environment variables, fixed verifier backend configuration, and non-executing `plan` output.

**Residual risk:** a valid pytest recipe can execute malicious tests. Runtime isolation remains necessary.

### T4. Implicit unsafe fallback

**Scenario:** No sandbox is installed, so a tool silently executes repository code on the host.

**Controls:** `auto` considers OpenShell, Podman, and Docker only. Absence returns `unsupported`.
`unsafe-local` requires explicit user selection and is labeled as non-isolated evidence.

### T5. Sandbox escape or host-secret access

**Scenario:** Repository code attempts to read host files, mutate outside the source root, reach the
network, consume excessive resources, or exploit the runtime.

**Controls:** OpenShell policy, OCI read-only root/source mounts, no network, non-root process, dropped
capabilities, no-new-privileges, PID/memory/CPU limits, bounded tmpfs, and automatic cleanup.

**Residual risk:** external runtime and kernel flaws are out of scope. OpenShell runtime behavior must be
reproduced on a supported host; adapter unit tests alone do not prove isolation.

### T6. Filesystem escape or destructive rollback

**Scenario:** An action path or rollback escapes the owned workspace.

**Controls:** relative path normalization, resolved-root checks, allowlisted write paths, ownership marker,
and snapshot hash validation.

**Residual risk:** platform-specific TOCTOU and filesystem behavior need stronger runtime tests.

### T7. Retry and approval confusion

**Scenario:** A completed side effect is repeated, or approval is reused for a different action.

**Controls:** unique idempotency keys, terminal result replay, action-bound approval IDs, immutable local
decisions, and suspended state.

**Residual risk:** remote services need their own idempotency and authenticated user identity.

### T8. Evidence tampering or substitution

**Scenario:** A result is detached from its source, recipe, policy, or artifact; a generated archive is
modified after creation.

**Controls:** source commit and dirty flag, registry/recipe/policy digests, per-artifact hashes,
deterministic archive layout, and release attestations.

**Residual risk:** SHA-256 integrity does not establish publisher identity. The user must verify trusted
attestations, signatures, or registry provenance.

### T9. Secret exposure in outputs

**Scenario:** Tests print credentials and outputs are persisted or returned through MCP.

**Controls:** no credential input in verification recipes, sanitized environment, existing redaction for
runtime events, output truncation, no network by default, and read-only public MCP mode.

**Residual risk:** pattern redaction is incomplete. Do not run verification with production credentials.

### T10. Remote MCP abuse

**Scenario:** A remotely reachable MCP endpoint offers anonymous code execution or is exposed through an
unsafe origin.

**Controls:** stdio default, localhost HTTP default, execution tools absent unless the user enables them,
and no remote deployment configuration in this repository.

**Residual risk:** anyone deploying remotely must add authentication, authorization, origin validation,
rate limits, audit storage, and deployment-specific incident controls.

## Explicit non-capabilities

XT-Aegis does not claim:

- universal protection against runtime or kernel vulnerabilities;
- anonymous remote verification as a safe public service;
- automatic trust in repository claims or CI artifacts;
- identity authentication from an integrity hash;
- production distributed state;
- measured latency or token savings without a published benchmark artifact.

## Acceptance criteria for a production verification profile

1. supported OS/runtime versions and immutable images are documented;
2. host-secret canaries cannot be read from a malicious test corpus;
3. source and output mounts cannot be escaped;
4. denied egress is confirmed from runtime evidence;
5. CPU, memory, PID, disk, time, and output limits are fault-tested;
6. runtime and policy digests are retained;
7. release artifacts have SBOM and provenance attestations;
8. crash and cancellation paths preserve result integrity;
9. independent users reproduce the conformance corpus;
10. limitations remain visible in the claim registry.
