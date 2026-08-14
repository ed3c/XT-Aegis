# OpenShell Verification Backend

## Role

OpenShell is an optional strong backend for user-operated verification. XT-Aegis supplies a bounded
adapter, an argv-only launcher, and a default-deny policy; OpenShell supplies the external runtime and
enforcement mechanisms. The two threat models remain separate.

OpenShell is alpha software. Adapter compatibility and one successful conformance run do not prove
protection against flaws in OpenShell, its compute driver, the container runtime, a VM, or the host
kernel.

## Prerequisites

1. Install a reviewed OpenShell release and select a reachable gateway with a Docker, rootless Podman,
   Kubernetes, or MicroVM driver.
2. Publish or build the XT-Aegis verifier image, then set `XT_AEGIS_OPENSHELL_IMAGE` when a non-default
   image is required. Prefer an immutable image digest for retained evidence.
3. Keep `verification/policies/openshell.yaml` unchanged for the first run.
4. Run `xt-aegis doctor --backend openshell` before executing a recipe.

## Readiness model

`doctor` and `auto` do not treat executable presence as proof that a recipe can run. The adapter probes four
components in order and stops at the first failure, reporting the remaining components as `not probed`:

| Component | Probe | Not-ready meaning |
|---|---|---|
| `executable` | `shutil.which("openshell")` | OpenShell is not installed on `PATH` |
| `policy` | default-deny policy file is present | the reviewed policy is missing or `XT_AEGIS_OPENSHELL_POLICY` points elsewhere |
| `version` | `openshell --version` | the release does not match the reviewed adapter version, or reports no parsable version |
| `gateway` | `openshell status` | no active, reachable gateway resolves for the account and session that will launch the sandbox |

The version and gateway probes run through the same working directory and the same forwarded session
environment (`_openshell_host_environment`) that `sandbox create` uses, so a gateway that the launch path
cannot resolve also fails the probe. The adapter is reviewed against OpenShell `0.0.52`; another reviewed
release is accepted by setting `XT_AEGIS_OPENSHELL_SUPPORTED_VERSION`.

Consequences:

- `xt-aegis doctor --format json` reports `components[]` with `component`, `ready`, and the exact reason;
- `auto` never selects OpenShell while any component is not ready, and never falls back to `unsafe-local`;
- a probe failure, a launch failure, or a backend that becomes unready between probe and launch produces a
  typed `unsupported` infrastructure verdict with a bounded single-line diagnostic, not a failed claim.

### Proof that the recipe actually started

A ready gateway is still not proof that a sandbox can be created: an OpenShell gateway can answer `status`
and then reject `sandbox create` with `FailedPrecondition: sandbox is not ready`. Because a runtime that
never launched exits non-zero exactly like a failing test, the exit code cannot separate the two.

The adapter therefore issues a fresh 128-bit entry token per run and passes it to the in-sandbox launcher.
`xt_aegis.sandbox_exec` writes `xt-aegis-sandbox-entered:<token>` to stderr immediately before `execvp`, so
the marker exists only if the recipe really started inside the sandbox. The host removes that line from
retained evidence. A missing or non-matching marker is reported as `unsupported` with the bounded runtime
diagnostic instead of a failed repository claim.

The probe still does not create a throwaway sandbox during `doctor`; sandbox-creation readiness is proven
at launch time by the marker, and adversarial live coverage remains issue #12.

## Source-binding model

The adapter does not ask the sandbox to verify only the source baked into the verifier image. It starts
the OpenShell host command with the selected checkout as its working directory and uploads
`.:/workspace`. OpenShell's Git-aware upload therefore places the checkout contents directly under
`/workspace` while respecting `.gitignore` by default. The initial command sets
`PYTHONPATH=/workspace/src`, so the `xt_aegis.sandbox_exec` module and the claim tests both come from
that uploaded source revision.

The launcher:

- accepts a normalized relative `cwd` and a structured argv array;
- resolves the working directory beneath `/workspace`;
- rejects absolute paths, `..` traversal, and path-qualified executables;
- changes directory and calls `os.execvp` directly;
- never invokes a shell or evaluates Markdown text.

The host-side result remains bound to the checked-out Git commit and dirty-worktree flag. An image digest,
registry digest, recipe digest, and OpenShell policy digest should be retained with evidence.

## Verifier image contract

`Dockerfile.verifier` derives from a digest-pinned OpenShell Community sandbox base so the image retains
the expected supervisor, SSH/SFTP, virtual-environment, and `sandbox` user contract. The base image is
interactive and declares `/bin/bash` as its OCI entrypoint. XT-Aegis explicitly clears that entrypoint:

```dockerfile
ENTRYPOINT []
CMD ["xt-aegis-mcp"]
```

This matters in both execution modes:

- a normal OCI runtime executes `xt-aegis`, `xt-aegis-mcp`, or another argv directly instead of asking
  Bash to interpret a Python console-script file;
- OpenShell can inject its supervisor command directly instead of passing that executable as Bash input.

The verifier image is still non-root. OpenShell controls the runtime command and policy, while the image
only supplies reviewed tools and dependencies.

## Policy

The included policy uses:

- `filesystem_policy.include_workdir: true` so the uploaded disposable workspace is accessible;
- explicit system read paths and bounded writable paths;
- the unprivileged `sandbox` user and `supervisor` runtime contract supplied by the OpenShell Community
  base image;
- Landlock as a hard requirement;
- an empty `network_policies` map, requesting default-deny egress.

The registry cannot add filesystem paths, network endpoints, credentials, mounts, providers, or arbitrary
environment variables. The adapter passes `--no-auto-providers`, disables TTY allocation, and places a
fixed set of cache and Python variables before the argv-only launcher by using the standard `env`
executable. A user may provide another reviewed policy with `XT_AEGIS_OPENSHELL_POLICY`; the policy
digest is recorded in every result.

## Exact invocation shape

The host process first changes to the verification root. For each recipe the adapter then constructs an
argv equivalent to the OpenShell v0.0.52 interface:

```text
openshell sandbox create \
  --from ghcr.io/ed3c/xt-aegis-verifier:0.2.0 \
  --policy verification/policies/openshell.yaml \
  --cpu 1 \
  --memory 1Gi \
  --no-auto-providers \
  --no-tty \
  --upload .:/workspace \
  --no-keep \
  -- \
  env \
    HOME=/sandbox \
    PYTHONPATH=/workspace/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPYCACHEPREFIX=/tmp/pycache \
    COVERAGE_FILE=/tmp/.coverage \
    RUFF_CACHE_DIR=/tmp/ruff-cache \
    MYPY_CACHE_DIR=/tmp/mypy-cache \
  python -m xt_aegis.sandbox_exec \
    --root /workspace \
    --cwd <recipe cwd> \
    -- <recipe argv...>
```

No shell interpolation is used. CPU and memory are bounded, and `--no-keep` requests automatic cleanup
after the command exits. The recipe timeout and output bounds are also enforced by the XT-Aegis host
process.

## Run all claims

```bash
xt-aegis verify \
  --all \
  --backend openshell \
  --output-dir ./verification-out

xt-aegis evidence pack \
  --input ./verification-out \
  --output ./xt-aegis-openshell-evidence.tar.gz
```

## Live conformance workflow

`.github/workflows/openshell-conformance.yml` is a manual and pull-request workflow. It:

1. creates a user-owned gateway configuration that explicitly selects the Docker compute driver;
2. builds the verifier image on the digest-pinned OpenShell Community base and records the base manifest
   plus the derived image identity;
3. installs a checksum-recorded, pinned OpenShell release through the official installer;
4. runs `doctor` and all implemented claim recipes through the OpenShell backend;
5. propagates verifier failures through every `tee` pipeline with `pipefail`;
6. records gateway configuration, Docker and image metadata, status, journal, and sandbox inventory;
7. packs successful verification evidence or deterministic failure diagnostics;
8. uploads the resulting archive as a GitHub Actions artifact.

The explicit Docker selection avoids silently relying on OpenShell's runtime auto-detection order. The
workflow stores the same selection in both `gateway.toml` and the package-managed service environment
file, then verifies the active gateway before any claim recipe runs.

A project-operated workflow result must be labeled `verified-by-project-ci`. Independent users should
rerun the same commands on infrastructure they control before labeling evidence
`independently-reproduced`.

## What repository tests prove

Repository tests prove that the adapter:

- detects a missing executable or policy;
- reports each readiness component separately and marks unprobed components explicitly;
- refuses an unreviewed or unparsable OpenShell version and accepts an explicitly reviewed override;
- treats a failing, timing-out, or unlaunchable `openshell status` as an unready gateway;
- keeps `auto` from selecting OpenShell when any component is not ready;
- turns an unready gateway into an `unsupported` verification result rather than a failed claim;
- treats a recipe that never entered the sandbox, or a forged entry marker, as `unsupported`;
- emits the entry marker from the launcher before `execvp` and keeps it out of retained evidence;
- uploads the checkout root directly into `/workspace` instead of silently testing only image-baked code;
- starts the host process at the selected verification root rather than at a recipe subdirectory;
- uses only flags supported by the pinned OpenShell v0.0.52 interface;
- disables automatic credential providers and interactive TTY allocation;
- constructs a structured argv with a confined working-directory launcher;
- does not accept a shell string or path-qualified executable;
- records the policy digest;
- derives from a digest-pinned OpenShell-compatible base and clears its interactive entrypoint;
- remains outside the automatic local fallback path.

A real OpenShell gateway is required to prove runtime behavior. CI that does not run the conformance
workflow must not report OpenShell host isolation as verified.

## Residual risks

- OpenShell is alpha software and its interfaces can change;
- uploaded Git-aware source may omit ignored files by design; verification recipes must not depend on
  secrets or local build caches;
- the OpenShell Community base is digest-pinned; changing that digest requires review and invalidates
  direct comparison with earlier evidence;
- `/workspace` is a writable disposable copy inside the sandbox, not a read-only host bind mount;
- default-deny networking must be confirmed from runtime policy state and logs;
- a test process may consume resources up to the limits configured by the external runtime;
- policy or image changes invalidate comparisons unless their digests are retained.

For environments where OpenShell is unavailable, use rootless Podman or Docker with the verifier image.
The OCI adapter runs the verifier as the host uid and gid rather than as root inside the container; the
read-only mount means the process only needs read access to it.
`unsafe-local` is a development mode, not a substitute for isolation.
