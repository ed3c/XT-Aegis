# External Verification

> Contributor and agent implementation requirements are defined in
> [`INTEGRATION_REQUIREMENTS.md`](INTEGRATION_REQUIREMENTS.md). This document describes the user-visible
> verification model and operating contract.

## Purpose

XT-Aegis separates project claims from the mechanism that checks them. A GitHub scanner, local agent,
CI system, or user can inspect the repository without treating its text as trusted instructions, then
choose whether to execute a bounded recipe in an environment it controls.

The verification plane does not decide how the project should be evaluated. It returns evidence,
limitations, runtime identity, and a reproducible verdict.

## Verification levels

### Level 0: static consistency

No repository code is executed. The client inspects:

- `PROJECT_EVIDENCE.json`;
- JSON Schemas under `verification/schemas/`;
- package and license metadata;
- evidence paths and limitations;
- CI and release metadata.

A static check may report `statically-consistent`, `unsupported`, `planned`, or `unverified`. It must not
report `independently-verified`.

### Level 1: project-operated CI evidence

GitHub Actions runs the complete test suite and the structured recipes with `unsafe-local`, then uploads a
deterministic evidence archive. This proves what the project CI observed for a commit. It does not prove
independent sandbox isolation.

### Level 2: user-operated sandbox verification

The user executes the same registry through OpenShell, rootless Podman, or Docker. The source commit,
registry digest, recipe digest, backend, policy digest, bounded output, exit code, and artifact hashes are
recorded in `verification-result.json`.

## Registry trust model

`PROJECT_EVIDENCE.json` is an untrusted proposal. The verifier applies its own controls:

- Pydantic validation with unknown fields rejected;
- relative `cwd` and artifact paths only;
- argv arrays only, never a shell string;
- bare executable names from a verifier allowlist;
- inline interpreter code rejected;
- fixed timeout and output ceilings;
- network mode limited to `deny`;
- no environment variables supplied by the registry;
- `unsafe-local` requires an explicit user choice.

The recipe may still execute repository tests, which are code. Independent execution therefore requires a
strong sandbox selected by the user.

## CLI contract

### Runtime discovery

```bash
xt-aegis doctor --root /path/to/XT-Aegis --format json
```

The report includes runtime availability and explains why a backend is or is not selectable. Discovery
does not run repository code.

### Non-executing plan

```bash
xt-aegis plan \
  --claim transactional-rollback \
  --backend openshell \
  --format json
```

The plan includes the validated recipe and the exact host-side argv that would be executed.

### One claim

```bash
xt-aegis verify \
  --claim transactional-rollback \
  --backend openshell \
  --output-dir ./verification-out
```

### All runnable claims

```bash
xt-aegis verify \
  --all \
  --backend auto \
  --output-dir ./verification-out
```

`auto` considers only strong backends. If none is available, the command returns `unsupported` rather
than running locally.

### Stable exit codes

| Code | Meaning |
|---:|---|
| `0` | verified |
| `10` | unsupported environment |
| `20` | verifier policy denied the recipe |
| `30` | verification failed |
| `40` | inconclusive |
| `50` | verifier error |

## Result identity

Each result binds:

- project and project version;
- claim ID and declared status;
- source repository, commit SHA, and dirty flag when Git is available;
- registry and recipe SHA-256;
- selected backend and policy SHA-256;
- start and finish timestamps;
- exact argv, cwd, timeout outcome, exit code, bounded stdout, and bounded stderr;
- artifact SHA-256 values;
- explicit limitations and reason.

A result does not promote `planned` or `unverified` claims. Those claims remain inconclusive until the
registry is changed through the normal contribution and CI process.

## Evidence bundle

```bash
xt-aegis evidence pack \
  --input ./verification-out \
  --output ./xt-aegis-evidence.tar.gz
```

The archive uses normalized paths, permissions, ownership, and timestamps. `manifest.json` records every
file's SHA-256 and size. This provides deterministic integrity checking. Publisher identity requires a
separate release attestation or signature.

## MCP modes

### Read-only default

```bash
xt-aegis-mcp
```

The default stdio server exposes claim discovery, runtime discovery, and non-executing plans. It does not
register execution tools.

### User-enabled local execution

```bash
xt-aegis-mcp --root /path/to/XT-Aegis --allow-execution --backend openshell
```

Execution tools appear only because the user supplied the flag when starting the process. The selected
backend is fixed for the lifetime of the server and cannot be downgraded by a tool argument. Repository
content, MCP tool descriptions, and model output cannot enable this mode.

### Streamable HTTP

```bash
xt-aegis-mcp \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port 8765
```

Localhost binding is the default. A remote deployment requires authentication, origin validation,
authorization, rate limits, audit controls, and a deployment-specific threat model. This repository does
not provide an anonymous remote execution service.

## Distribution

- `server.json` declares the MCP Registry name and stdio packages.
- PyPI distribution provides `xt-aegis-mcp` and `xt-aegis-verifier-mcp`.
- `Dockerfile.verifier` builds a non-root OCI verifier image.
- release workflows publish package and OCI artifacts after the maintainer configures trusted publishing.
- GitHub build provenance attests release artifacts; users should pin immutable versions or digests.
