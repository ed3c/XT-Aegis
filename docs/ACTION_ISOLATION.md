# Strong Isolation for Mutating Command Actions

## Two properties that were being conflated

| Property | What it means | Where it comes from |
|---|---|---|
| Workspace rollback integrity | the owned workspace was restored to its pre-action hash | the snapshot transaction |
| Process isolation | the process could not read or write outside what it was granted | the action-execution backend |

A result that reports only the first can be misread as containment. `ExecutionResult` now carries
`isolation_backend` and `isolation_verdict` next to `rollback_integrity`, so a reader can tell which
property held.

## Backends

| Backend | Strong isolation | When it is used |
|---|---|---|
| `docker` / `podman` | yes | a container whose only writable bind mount is the owned workspace |
| `unsafe-local` | no | explicit development selection only |

`auto` selects a strong backend that passes its readiness probe, or raises. It never falls back to
`unsafe-local`; that backend must be named explicitly.

## The supported container profile

```text
--network none            no egress from the action
--read-only               root filesystem is immutable
--cap-drop ALL            no Linux capabilities
--security-opt no-new-privileges
--pids-limit 128  --memory 1g  --cpus 1
--mount type=bind,src=<owned workspace>,dst=/workspace   the only writable bind mount
--tmpfs /tmp:rw,noexec,nosuid,size=64m
--workdir /workspace/<recipe cwd>
--rm                      the container is removed when the command exits
```

The image is `python:3.12-slim` by default and is overridable with `XT_AEGIS_ACTION_IMAGE`. The image must
contain the executables the contract allowlists; the allowlist is still enforced by policy before the
backend is consulted.

## Failing closed

A contract sets `requires_isolation: true` when its actions must not run without strong isolation. The
runner then checks, **before any snapshot or mutation**, that the selected backend both claims strong
isolation and passes its readiness probe. If either is false the request is `blocked` with reason
`isolation_unavailable`, nothing is executed, and no rollback is needed because nothing changed.

A working directory that escapes the owned workspace is refused before the mount is constructed, so a
traversal cannot widen what the container can reach.

## What the live evidence covers

`tests/test_action_isolation.py` runs against a real Docker daemon when one is available, and is skipped
with a stated reason when it is not. On the supported profile it proves that a command:

- runs inside the workspace mount and sees the workspace content;
- cannot write outside the mount, and no artifact appears on the host;
- cannot read a host file placed next to the workspace;
- has no network;
- has its mutation rolled back inside the mount, with `rollback_integrity` true and `isolation_verdict`
  true reported separately;
- leaves no container behind.

## What it does not prove

- Nothing here is a claim about runtime or kernel zero-days. The container runtime is an external trust
  boundary with its own threat model.
- Snapshot rollback still cannot undo a network call or a host side effect. It restores the owned
  workspace and says nothing more.
- Evidence from one Docker version on one host is not a general claim. The version-pinned adversarial
  matrix across OpenShell and rootless Podman remains issue #12.
- Rootless Podman readiness is probed but has no live evidence in this repository yet.
