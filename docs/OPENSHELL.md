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

## Source-binding model

The adapter does not ask the sandbox to verify only the source baked into the verifier image. It starts
the OpenShell host command with the selected checkout as its working directory and uploads
`.:/workspace`. OpenShell's Git-aware upload therefore places the checkout contents directly under
`/workspace` while respecting `.gitignore` by default. The adapter then sets
`PYTHONPATH=/workspace/src`, so the initial `xt_aegis.sandbox_exec` module and the claim tests both come
from that uploaded source revision.

The launcher:

- accepts a normalized relative `cwd` and a structured argv array;
- resolves the working directory beneath `/workspace`;
- rejects absolute paths, `..` traversal, and path-qualified executables;
- changes directory and calls `os.execvp` directly;
- never invokes a shell or evaluates Markdown text.

The host-side result remains bound to the checked-out Git commit and dirty-worktree flag. An image digest,
registry digest, recipe digest, and OpenShell policy digest should be retained with evidence.

## Policy

The included policy uses:

- `filesystem_policy.include_workdir: true` so the uploaded disposable workspace is accessible;
- explicit system read paths and bounded writable paths;
- an unprivileged `sandbox` user and group;
- Landlock as a hard requirement;
- an empty `network_policies` map, requesting default-deny egress.

The registry cannot add filesystem paths, network endpoints, credentials, mounts, providers, or arbitrary
environment variables. The adapter passes `--no-auto-providers`, uses manual approval mode, disables a
TTY, and injects only fixed cache and Python path variables. A user may provide another reviewed policy
with `XT_AEGIS_OPENSHELL_POLICY`; the policy digest is recorded in every result.

## Exact invocation shape

The host process first changes to the verification root. For each recipe the adapter then constructs an
argv equivalent to:

```text
openshell sandbox create \
  --from ghcr.io/ed3c/xt-aegis-verifier:0.2.0 \
  --policy verification/policies/openshell.yaml \
  --cpu 1 \
  --memory 1Gi \
  --no-auto-providers \
  --approval-mode manual \
  --no-tty \
  --upload .:/workspace \
  --env PYTHONPATH=/workspace/src \
  --env PYTHONDONTWRITEBYTECODE=1 \
  --env PYTHONUNBUFFERED=1 \
  --env COVERAGE_FILE=/tmp/.coverage \
  --env RUFF_CACHE_DIR=/tmp/ruff-cache \
  --env MYPY_CACHE_DIR=/tmp/mypy-cache \
  --no-keep \
  -- \
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

`.github/workflows/openshell-conformance.yml` is a manual and reusable workflow. It builds the verifier
image from the selected commit, installs a pinned OpenShell release through the official installer, runs
`doctor`, verifies the implemented claims with the OpenShell backend, packs the results, and uploads the
bundle as a GitHub Actions artifact.

A project-operated workflow result must be labeled `verified-by-project-ci`. Independent users should
rerun the same commands on infrastructure they control before labeling evidence
`independently-reproduced`.

## What repository tests prove

Repository tests prove that the adapter:

- detects a missing executable or policy;
- uploads the checkout root directly into `/workspace` instead of silently testing only image-baked code;
- starts the host process at the selected verification root rather than at a recipe subdirectory;
- disables automatic credential providers and interactive TTY allocation;
- constructs a structured argv with a confined working-directory launcher;
- does not accept a shell string or path-qualified executable;
- records the policy digest;
- remains outside the automatic local fallback path.

A real OpenShell gateway is required to prove runtime behavior. CI that does not run the conformance
workflow must not report OpenShell host isolation as verified.

## Residual risks

- OpenShell is alpha software and its interfaces can change;
- uploaded Git-aware source may omit ignored files by design; verification recipes must not depend on
  secrets or local build caches;
- `/workspace` is a writable disposable copy inside the sandbox, not a read-only host bind mount;
- default-deny networking must be confirmed from runtime policy state and logs;
- a test process may consume resources up to the limits configured by the external runtime;
- policy or image changes invalidate comparisons unless their digests are retained.

For environments where OpenShell is unavailable, use rootless Podman or Docker with the verifier image.
`unsafe-local` is a development mode, not a substitute for isolation.
