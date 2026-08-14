"""Execution backends for mutating command actions.

Workspace rollback and process isolation are different properties. Rollback restores the owned workspace;
it says nothing about what a process did outside that workspace. This module owns the second property and
reports it separately, so a result can never imply containment it did not have.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

CONTAINER_WORKSPACE = "/workspace"
DEFAULT_ACTION_IMAGE = "python:3.12-slim"
_PROBE_TIMEOUT_SECONDS = 10
_PROBE_DETAIL_CHARS = 240


class ActionBackendName(StrEnum):
    """Execution backends available to a mutating command action."""

    AUTO = "auto"
    DOCKER = "docker"
    PODMAN = "podman"
    UNSAFE_LOCAL = "unsafe-local"


@dataclass(frozen=True)
class IsolationReadiness:
    """Whether a backend can actually launch, and the exact reason when it cannot."""

    ready: bool
    reason: str


class IsolationUnavailableError(RuntimeError):
    """Raised when strong isolation is required and no conformant backend is ready."""


class ActionBackend(Protocol):
    """Turn a validated argv into the host argv that runs it, plus a readiness verdict."""

    name: ActionBackendName
    strong_isolation: bool

    def readiness(self, workspace_root: Path) -> IsolationReadiness:
        """Return whether this backend can launch a command right now."""

    def host_argv(self, argv: list[str], *, workspace_root: Path, relative_cwd: str) -> list[str]:
        """Return the argv the runner executes on the host."""

    def host_cwd(self, workspace_root: Path, relative_cwd: str) -> Path:
        """Return the working directory for the host process."""


class UnsafeLocalActionBackend:
    """Explicit development mode: the command runs as a host subprocess with no OS isolation."""

    name = ActionBackendName.UNSAFE_LOCAL
    strong_isolation = False

    def readiness(self, workspace_root: Path) -> IsolationReadiness:
        del workspace_root
        return IsolationReadiness(
            ready=True,
            reason="available only through explicit selection; no process isolation is provided",
        )

    def host_argv(self, argv: list[str], *, workspace_root: Path, relative_cwd: str) -> list[str]:
        del workspace_root, relative_cwd
        return list(argv)

    def host_cwd(self, workspace_root: Path, relative_cwd: str) -> Path:
        return _resolve_workspace_path(workspace_root, relative_cwd)


class OciActionBackend:
    """Run the command in a container whose only writable bind mount is the owned workspace."""

    strong_isolation = True

    def __init__(
        self,
        name: ActionBackendName = ActionBackendName.DOCKER,
        *,
        image: str | None = None,
    ) -> None:
        if name not in {ActionBackendName.DOCKER, ActionBackendName.PODMAN}:
            raise ValueError(f"unsupported OCI action backend: {name}")
        self.name = name
        self.image: str = image or os.getenv("XT_AEGIS_ACTION_IMAGE") or DEFAULT_ACTION_IMAGE

    def readiness(self, workspace_root: Path) -> IsolationReadiness:
        del workspace_root
        executable = shutil.which(self.name.value)
        if executable is None:
            return IsolationReadiness(False, f"{self.name.value} executable was not found")
        try:
            probe = subprocess.run(
                [executable, "info", "--format", "{{json .}}"],
                check=False,
                capture_output=True,
                text=True,
                timeout=_PROBE_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return IsolationReadiness(False, f"{self.name.value} probe failed: {exc}"[:_PROBE_DETAIL_CHARS])
        if probe.returncode != 0:
            detail = (probe.stderr or probe.stdout).strip().splitlines()
            return IsolationReadiness(
                False,
                f"{self.name.value} runtime is not ready: "
                f"{detail[0][:_PROBE_DETAIL_CHARS] if detail else 'no diagnostic output'}",
            )
        if self.name is ActionBackendName.PODMAN and not self._rootless(probe.stdout):
            return IsolationReadiness(False, "Podman is reachable but rootless mode was not confirmed")
        return IsolationReadiness(True, f"{self.name.value} runtime is ready")

    @staticmethod
    def _rootless(payload: str) -> bool:
        try:
            info = json.loads(payload)
        except json.JSONDecodeError:
            return False
        host = info.get("host", {}) if isinstance(info, dict) else {}
        security = host.get("security", {}) if isinstance(host, dict) else {}
        return bool(security.get("rootless")) if isinstance(security, dict) else False

    def host_argv(self, argv: list[str], *, workspace_root: Path, relative_cwd: str) -> list[str]:
        executable = shutil.which(self.name.value) or self.name.value
        # Guard here as well as in the runner: this method decides what the container may reach, so a
        # traversal must fail before the mount is built, not after.
        workdir = _resolve_workspace_path(workspace_root, relative_cwd)
        container_workdir = f"{CONTAINER_WORKSPACE}/{workdir.relative_to(workspace_root).as_posix()}".rstrip(
            "/."
        )
        return [
            executable,
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "128",
            "--memory",
            "1g",
            "--cpus",
            "1",
            "--mount",
            f"type=bind,src={workspace_root},dst={CONTAINER_WORKSPACE}",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=67108864",
            "--workdir",
            container_workdir or CONTAINER_WORKSPACE,
            "--env",
            "HOME=/tmp",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "PYTHONUNBUFFERED=1",
            self.image,
            *argv,
        ]

    def host_cwd(self, workspace_root: Path, relative_cwd: str) -> Path:
        del relative_cwd
        return workspace_root


def _resolve_workspace_path(workspace_root: Path, relative_cwd: str) -> Path:
    """Resolve a relative working directory that must stay inside the owned workspace."""

    root = workspace_root.resolve()
    candidate = (root / relative_cwd).resolve()
    if not candidate.is_relative_to(root):
        raise IsolationUnavailableError("the command working directory escaped the owned workspace")
    return candidate


def action_backends(*, image: str | None = None) -> dict[ActionBackendName, ActionBackend]:
    """Construct the available adapters."""

    return {
        ActionBackendName.DOCKER: OciActionBackend(ActionBackendName.DOCKER, image=image),
        ActionBackendName.PODMAN: OciActionBackend(ActionBackendName.PODMAN, image=image),
        ActionBackendName.UNSAFE_LOCAL: UnsafeLocalActionBackend(),
    }


def select_action_backend(
    requested: ActionBackendName,
    workspace_root: Path,
    *,
    image: str | None = None,
) -> ActionBackend:
    """Select a backend, never silently falling back to unsafe-local."""

    available = action_backends(image=image)
    if requested is not ActionBackendName.AUTO:
        return available[requested]
    reasons: list[str] = []
    for name in (ActionBackendName.PODMAN, ActionBackendName.DOCKER):
        backend = available[name]
        verdict = backend.readiness(workspace_root)
        if verdict.ready:
            return backend
        reasons.append(verdict.reason)
    raise IsolationUnavailableError(
        "no strong action-execution backend is ready: "
        + "; ".join(reasons)
        + "; select unsafe-local explicitly for development"
    )
