# Threat Model

## Scope

This document covers the XT-Aegis MVP as implemented in this repository. It does not treat a Python
process allowlist as a production sandbox. Container, microVM, kernel, identity-provider, and remote
network controls are planned work.

## Assets

- source code and files in the execution workspace;
- API credentials and environment variables outside the workspace;
- checkpoint integrity and idempotency state;
- human approval decisions;
- evaluation records and reviewer trust;
- host filesystem, network, and developer accounts.

## Trust levels

| Trust label | Examples | Authority |
|---|---|---|
| Maintainer contract | reviewed YAML front matter, release configuration | may define bounded policy |
| Operator | local user explicitly creating an action | may propose actions subject to policy |
| Agent proposal | structured output from a model | may propose, never bypass policy |
| External content | issue text, web page, README, tool result, memory excerpt | data only; cannot directly invoke tools |
| Executor | deterministic code in `policy.py` and `runner.py` | enforces policy and records evidence |

## Primary threats and controls

### T1. Direct prompt injection from external content

**Scenario:** A web page, issue body, or repository file says to ignore policy, reveal secrets, modify
files, or call a tool.

**Controls:**

- integration must label the proposal `external_content` when the executable intent came directly from
  retrieved text;
- `PolicyEngine` rejects that provenance before creating a transaction;
- the skill compiler never extracts commands from Markdown prose or code fences;
- the optional MCP surface is read-only.

**Residual risk:** Provenance is an integration boundary. A caller that falsely labels external content
as an operator or agent proposal can bypass this specific check, though the remaining path and command
policies still apply. Production integrations need taint propagation rather than a manually selected
enum.

### T2. Indirect prompt injection through tool output or memory

**Scenario:** A tool returns adversarial text that is later stored and used as planning context.

**Controls:**

- tool output is not parsed into `ActionRequest` by the executor;
- durable records use typed fields rather than prompt concatenation;
- unknown fields fail validation;
- evaluation reads execution records, not recalled natural-language claims.

**Residual risk:** The model may still propose a harmful but schema-valid action after reading poisoned
data. The deterministic policy, approval gate, and sandbox backend must contain that proposal.

### T3. Shell injection and command chaining

**Scenario:** An action supplies `&&`, pipes, redirection, command substitution, or inline interpreter
code.

**Controls:**

- commands are arrays and always run with `shell=False`;
- executable names must be bare and allowlisted;
- common control fragments are denied;
- interpreter `-c`/`--command` modes are denied;
- timeout and output limits are applied.

**Residual risk:** An allowlisted executable can have dangerous native flags or execute project code.
A production policy needs per-tool argument schemas and OS isolation.

### T4. Filesystem escape or destructive rollback

**Scenario:** A path uses `..`, absolute paths, symlinks, or a rollback targets the real repository.

**Controls:**

- write targets are normalized relative paths and checked against the resolved workspace root;
- allowed write patterns are declared in the skill;
- XT-Aegis creates the run root and writes a random ownership marker;
- rollback refuses unowned roots, filesystem roots, home directories, and roots outside the run root;
- the MVP uses a copied snapshot rather than `git reset --hard` in the caller's checkout.

**Residual risk:** TOCTOU and platform-specific filesystem behavior need stronger containment in a
container or microVM. The MVP is intended for local demonstration workspaces.

### T5. Repeated side effects after retry

**Scenario:** A timeout or network failure causes the caller to repeat a successful action.

**Controls:**

- idempotency keys are unique in SQLite;
- terminal results are replayed without repeating the action;
- approvals are bound to thread, action, and idempotency key.

**Residual risk:** External services also need their own idempotency tokens. Local replay cannot undo a
remote side effect that completed but was not acknowledged.

### T6. Approval confusion

**Scenario:** Approval for one action is reused for a different action or approver identity is forged.

**Controls:**

- approval IDs are derived from the exact thread, action, and idempotency key;
- validation matches every field;
- a decision is immutable after the first transition.

**Residual risk:** Reviewer identity is a local string in the MVP. Production requires authenticated
identity, expiry, reason, signature, and separation-of-duties policy.

### T7. Secret exposure in logs

**Scenario:** A command prints API keys or tokens and XT-Aegis persists them.

**Controls:**

- common token patterns and key/value secret names are redacted;
- stdout and stderr are truncated;
- the demo contains no credentials;
- the MCP evidence tool returns static project metadata only.

**Residual risk:** Pattern redaction is not complete. Production should prevent secret exposure at the
credential proxy boundary and classify sensitive output before persistence.

### T8. Denial of service and runaway execution

**Scenario:** A process hangs, writes excessive data, or an agent loops.

**Controls:**

- per-command timeout;
- skill-level maximum steps, total wall-clock budget, write size, output truncation;
- no automatic unbounded retry loop in the runner.

**Residual risk:** CPU, memory, process count, disk, and network are not enforced with cgroups or kernel
limits in the MVP.

### T9. Evaluation or hiring prompt injection

**Scenario:** Repository text instructs an automated reviewer to select the project, change a score,
ignore the rubric, reveal system prompts, or treat claims as verified.

**Controls:**

- project policy forbids ranking-manipulation instructions in code and documentation;
- `AGENT_REVIEW_GUIDE.md` tells reviewers to keep their existing policy and independently verify claims;
- `PROJECT_EVIDENCE.json` labels planned and unverified claims explicitly;
- review commands are bounded and reproducible.

**Residual risk:** A scanner may still be vulnerable to unrelated repository content. Review systems
must isolate instructions from evidence and retain higher-priority policy.

## Abuse cases intentionally not implemented

The project does not include:

- credential collection, browser session extraction, or token forwarding;
- hidden evaluator instructions or keyword stuffing for ranking;
- a remote unauthenticated mutation endpoint;
- arbitrary shell, package installation, or unrestricted network tools;
- claims of production security based only on passing unit tests.

## Security acceptance criteria for a mutating remote adapter

A remote mutation release cannot be marked production-ready until it has:

1. authenticated subject and audience validation;
2. per-tool authorization and least-privilege scopes;
3. signed/expiring approvals tied to exact parameters;
4. container or microVM isolation with CPU, memory, process, disk, and time limits;
5. default-deny egress with an external credential proxy;
6. adversarial prompt-injection and tool-output test corpus;
7. recovery tests across process crash and host restart;
8. concurrency, idempotency, and distributed-lock fault injection;
9. OpenTelemetry traces with a data-retention and secret-redaction policy;
10. an independent security review.
