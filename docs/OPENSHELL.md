# OpenShell Verification Backend

## Role

OpenShell is an optional strong backend for user-operated verification. XT-Aegis supplies a bounded
adapter and a default-deny policy; OpenShell supplies the external runtime and enforcement mechanisms.
The two threat models remain separate.

## Prerequisites

1. Install OpenShell and select a reachable gateway with a Docker, Podman, Kubernetes, or MicroVM driver.
2. Publish or build the XT-Aegis verifier image, then set `XT_AEGIS_OPENSHELL_IMAGE` when a non-default image is required.
3. Keep `verification/policies/openshell.yaml` unchanged for the first run.
4. Run `xt-aegis doctor --backend openshell` before executing a recipe.

## Policy

The included policy uses:

- `filesystem_policy.include_workdir: true` so the checked-out source is available;
- explicit system read paths and bounded writable paths;
- an unprivileged `sandbox` user and group;
- Landlock as a hard requirement;
- an empty `network_policies` map, which requests default-deny egress.

The registry cannot add filesystem paths, network endpoints, credentials, mounts, or environment
variables. A user may provide another reviewed policy with `XT_AEGIS_OPENSHELL_POLICY`, but the resulting
policy digest is recorded in every result.

## Exact invocation

For each recipe the adapter constructs:

```text
openshell sandbox create \
  --from ghcr.io/ed3c/xt-aegis-verifier:0.2.0 \
  --policy verification/policies/openshell.yaml \
  --cpu 1 \
  --memory 1Gi \
  --no-keep \
  -- \
  <recipe argv...>
```

No shell interpolation is used. `--from` selects the verifier image, CPU and memory are bounded, and
`--no-keep` requests automatic sandbox cleanup after the command exits. The recipe timeout and output
bounds are still enforced by the XT-Aegis host process. Users should replace the mutable image tag with
a release digest for retained evidence.

## Run all claims

```bash
xt-aegis verify \
  --all \
  --backend openshell \
  --output-dir ./verification-out
```

## What the adapter proves

Repository tests prove that the adapter:

- detects a missing executable or policy;
- constructs the documented argv exactly;
- does not accept a shell string;
- records the policy digest;
- remains outside the automatic local fallback path.

A real OpenShell host is required to prove runtime behavior. CI that lacks OpenShell must not report host
isolation as verified.

## Residual risks

- a vulnerability in OpenShell, its compute driver, container runtime, VM, or host kernel is outside this
  repository's control;
- `include_workdir: true` gives the sandbox access to the source working directory according to the
  external runtime policy;
- default-deny networking must be confirmed from runtime logs and policy state on the user's host;
- a test process may consume resources up to the limits configured by the external runtime;
- policy changes after a result invalidate comparisons unless the policy digest is retained.

For environments where OpenShell is unavailable, use rootless Podman or Docker with the verifier image.
`unsafe-local` is a development mode, not a substitute for isolation.
