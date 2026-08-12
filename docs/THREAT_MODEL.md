# Threat Model

## Status

The canonical request binding, schema-v2 checkpoint, exact approval, and declared command-outcome controls
are current on `main`. The provider proposal controls are under review in the #26 change when read from its
branch and current only when that exact change is present on `main`. The remaining controls describe current
or explicitly residual risk as indexed in [Traceability](TRACEABILITY.md).

## Scope

This document covers the repository implementation, including the SOP-Core and External Verification
Plane. It does not treat a Python process allowlist, a container, or an external runtime as protection
against every host-kernel or runtime vulnerability.

## Assets

- source files and execution workspace;
- credentials and environment data outside the workspace;
- canonical request, checkpoint, and idempotency integrity;
- user approval decisions;
- verification registry, recipes, results, and artifact hashes;
- model proposal content and provider-profile evidence;
- host filesystem, network, runtime daemon, and user accounts.

## Trust levels

| Trust label | Examples | Authority |
|---|---|---|
| Maintainer contract | reviewed YAML front matter, release configuration | may define bounded policy |
| User | local person explicitly creating an action or enabling verification | may propose actions subject to policy |
| Agent proposal | structured model output | may propose, never bypass policy |
| External content | issue text, web page, README, tool result, memory excerpt | data only |
| SOP-Core | identity, policy, runner, checkpoint, evaluator | enforces action policy |
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

### T1A. Provider proposal authority, substitution, or exfiltration

**Scenario:** A model response injects target, identity, approval, provenance, policy, backend, or budget
fields; a remote/redirected/proxied endpoint receives a private task; a different model is reported as the
configured profile; or malformed, partial, or oversized output is treated as executable.

**Controls:** strict `extra=forbid` proposal and provider-wire models, a checked-in content-only proposal
schema, trusted construction of kind/profile and all control-plane fields, redacted retained profile
metadata, active-skill path and UTF-8 byte checks, fresh trusted identifiers, a loopback-only Ollama origin,
no URL credentials/path/query, disabled environment proxies, refused redirects, bounded time and response
bytes, returned-model matching, and typed non-ready outcomes.

**Residual risk:** Ollama and the selected model are external local processes. Configured version metadata
is not remotely attested; local host compromise, HTTP implementation flaws, model quality, and private prompt
handling inside Ollama remain outside this adapter's guarantee. A ready proposal is untrusted data until the
existing policy, approval, isolation, execution, and assertion boundaries accept it.

### T1B. Repair-loop amplification or stale authority reuse

**Scenario:** A controller retries policy, approval, infrastructure, or recovery failures; reuses a prior
request identity for changed content; leaks an unbounded or secret-bearing diagnostic into the next prompt;
or continues after its attempt, token, wall-time, proposal, diagnostic, output, or repeated-cycle budget.

**Controls:** orchestration remains outside `HarnessRunner`; only execution and assertion failures are
retryable; every ready proposal passes through a fresh trusted envelope; attempt evidence binds provider,
source commit/dirty state, backend profile, target, proposal/request/policy digests, and configured budgets;
executor results must match the trusted thread/action/idempotency/request-version/request/policy identity;
typed executor reason codes drive stop classification instead of diagnostic text; diagnostics are redacted
and UTF-8 byte bounded before reuse; returned action output is truncated to the remaining evidence allowance;
equivalent failures use a stable fingerprint; and missing token usage stops before another provider call.

**Residual risk:** deterministic fake-provider tests do not establish live model correctness, privacy,
availability, cost, or uplift. Controller state is not yet resumed across process restart, branch-and-select
is not implemented, and command mutation still requires #27 strong isolation before autonomous use. The
wall deadline cannot preempt a non-conforming provider or in-process file write; it prevents later calls and
clamps the provided Ollama transport and command executor paths. Provider token counters are reported after
the call, and command output is bounded when retained rather than terminated at the first excess byte.

### T2. Shell, interpreter, or outcome-contract injection

**Scenario:** A recipe or action supplies command chaining, a path-qualified executable, inline code, or an
exit-code declaration intended to reclassify a failure or signal as success.

**Controls:** argv arrays, `shell=False`, executable allowlists, path-qualified executable rejection,
interpreter inline-code rejection, bounded non-empty exit-code sets, timeouts, signal rejection, post-action
assertions, and bounded output.

**Residual risk:** allowlisted tests are still code. A declared nonzero exit is only an outcome contract; it
does not prove semantic correctness without assertions and isolation.

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

**Residual risk:** external runtime and kernel flaws are out of scope. Runtime behavior must be reproduced
on a supported host; adapter unit tests alone do not prove isolation.

### T6. Filesystem escape or destructive rollback

**Scenario:** An action path or rollback escapes the owned workspace.

**Controls:** relative path normalization, resolved-root checks, allowlisted write paths, ownership marker,
and snapshot hash validation.

**Residual risk:** platform-specific TOCTOU and filesystem behavior need stronger runtime tests.

### T7. Idempotency, replay, and approval confusion

**Scenario:** A completed side effect is repeated; a global idempotency key returns another thread's result;
or approval for one payload, path, command, assertion, provenance, actor label, or policy is reused for
another.

**Controls:** versioned canonical JSON, request and policy SHA-256 digests, globally unique keys bound to one
identity, validation before cached replay, exact actor/request/policy approval matching, expiry, atomic
single-use consumption, no redisclosure of decided approval capabilities, durable conflict evidence, and
fail-closed legacy rows.

**Residual risk:** digests provide integrity, not authenticated identity. A process crash after approval
consumption fails closed and requires a fresh approval before retry. Remote side effects still need their
own idempotency and authenticated subjects. A request that omits or presents the wrong token may rotate an
unused approved capability to a fresh pending token; this prevents redisclosure but can force re-approval,
so exposed integrations still require authentication and request-rate controls against availability abuse.

### T8. Evidence tampering or substitution

**Scenario:** A result is detached from its source, request, recipe, policy, or artifact; a generated archive
is modified after creation.

**Controls:** request/policy digests, source commit and dirty flag, registry/recipe/policy digests,
per-artifact hashes, deterministic archive layout, and release attestations.

**Residual risk:** SHA-256 integrity does not establish publisher identity. The user must verify trusted
attestations, signatures, or registry provenance.

### T9. Secret exposure in outputs

**Scenario:** Tests print credentials and outputs are persisted or returned through MCP.

**Controls:** no credential input in verification recipes, sanitized environment, best-effort redaction,
output truncation, no network by default, and read-only public MCP mode.

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
- anonymous remote verification or mutation as a safe public service;
- automatic trust in repository claims or CI artifacts;
- actor authentication from an `actor_id` label or integrity hash;
- exactly-once semantics for external services without their cooperation;
- crash-safe distributed approval recovery;
- production distributed state;
- measured latency or token savings without a published benchmark artifact;
- correctness, availability, privacy, or performance of a live Ollama/model profile from adapter unit tests.

## Acceptance criteria for a production coding-agent profile

1. canonical request and policy identities remain stable across supported versions;
2. approval, replay, conflict, crash, and migration paths fail closed;
3. supported OS/runtime versions and immutable images are documented;
4. host-secret canaries cannot be read from a malicious test corpus;
5. source and output mounts cannot be escaped;
6. denied egress is confirmed from runtime evidence;
7. CPU, memory, PID, disk, time, output, attempt, and token limits are fault-tested;
8. runtime and policy digests are retained;
9. release artifacts have SBOM and provenance attestations;
10. independent users reproduce the conformance and coding-task corpus;
11. limitations remain visible in the claim registry.
