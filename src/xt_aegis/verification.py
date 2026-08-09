"""Bounded external verification with fail-closed sandbox selection."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from xt_aegis.verification_models import (
    BackendAvailability,
    BackendName,
    CommandEvidence,
    DoctorReport,
    EvidenceBundleFile,
    EvidenceBundleManifest,
    EvidenceRegistry,
    RegistryClaimStatus,
    SourceIdentity,
    VerificationClaim,
    VerificationRecipe,
    VerificationResult,
    VerificationStatus,
    VerificationSummary,
)

_RESULT_FILENAME = "verification-result.json"
_SUMMARY_FILENAME = "verification-summary.json"
_DEFAULT_IMAGE = "ghcr.io/ed3c/xt-aegis-verifier:0.2.0"

EXIT_CODES: dict[VerificationStatus, int] = {
    VerificationStatus.VERIFIED: 0,
    VerificationStatus.UNSUPPORTED: 10,
    VerificationStatus.POLICY_DENIED: 20,
    VerificationStatus.FAILED: 30,
    VerificationStatus.INCONCLUSIVE: 40,
    VerificationStatus.ERROR: 50,
}


class VerificationError(RuntimeError):
    """Base error for malformed or unsafe verification input."""


class VerificationPolicyError(VerificationError):
    """Raised when a recipe requests authority outside the verifier policy."""


@dataclass(frozen=True)
class LoadedRegistry:
    """Validated registry plus its source and digest."""

    registry: EvidenceRegistry
    display_path: str
    sha256: str


@dataclass(frozen=True)
class BackendExecution:
    """Backend process result plus the policy identity used to run it."""

    command: CommandEvidence
    policy_sha256: str | None


class SandboxBackend(Protocol):
    """Interface shared by verification execution backends."""

    name: BackendName
    strong_isolation: bool

    def availability(self, root: Path) -> BackendAvailability:
        """Return whether the backend can run in the current environment."""

    def run(self, recipe: VerificationRecipe, root: Path) -> BackendExecution:
        """Run one validated recipe."""

    def preview(self, recipe: VerificationRecipe, root: Path) -> list[str]:
        """Return the exact host-side argv without running it."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _truncate(value: str, maximum_bytes: int) -> tuple[str, bool]:
    encoded = value.encode(errors="replace")
    if len(encoded) <= maximum_bytes:
        return value, False
    marker = b"\n...[output truncated by XT-Aegis]"
    retained = encoded[: max(0, maximum_bytes - len(marker))] + marker
    return retained.decode(errors="replace"), True


def _read_registry_text(path: Path | None) -> tuple[str, str]:
    if path is not None:
        resolved = path.expanduser().resolve()
        return resolved.read_text(encoding="utf-8"), str(resolved)

    path_options = [
        Path.cwd() / "PROJECT_EVIDENCE.json",
        Path(__file__).resolve().parents[2] / "PROJECT_EVIDENCE.json",
    ]
    for path_option in path_options:
        if path_option.is_file():
            resolved = path_option.resolve()
            return resolved.read_text(encoding="utf-8"), str(resolved)

    resource = files("xt_aegis").joinpath("verification_assets/PROJECT_EVIDENCE.json")
    return resource.read_text(encoding="utf-8"), "package:xt_aegis/verification_assets/PROJECT_EVIDENCE.json"


def load_registry(
    path: str | Path | None = None,
    root: str | Path | None = None,
) -> LoadedRegistry:
    """Load and strictly validate a versioned evidence registry."""

    registry_path = Path(path) if path is not None else None
    if registry_path is None and root is not None:
        rooted_registry = Path(root).expanduser().resolve() / "PROJECT_EVIDENCE.json"
        if rooted_registry.is_file():
            registry_path = rooted_registry
    text, display_path = _read_registry_text(registry_path)
    try:
        raw = json.loads(text)
        registry = EvidenceRegistry.model_validate(raw)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise VerificationError(f"invalid evidence registry: {exc}") from exc
    return LoadedRegistry(registry=registry, display_path=display_path, sha256=_sha256_bytes(text.encode()))


def resolve_verification_root(registry: LoadedRegistry, explicit_root: str | Path | None = None) -> Path:
    """Resolve the source root without trusting a path from the registry itself."""

    if explicit_root is not None:
        root = Path(explicit_root).expanduser().resolve()
    elif not registry.display_path.startswith("package:"):
        root = Path(registry.display_path).resolve().parent
    else:
        root = Path.cwd().resolve()
    if not root.is_dir():
        raise VerificationError(f"verification root is not a directory: {root}")
    return root


def source_identity(root: Path, repository: str) -> SourceIdentity:
    """Read the Git identity when available without failing non-Git source archives."""

    git = shutil.which("git")
    if git is None or not (root / ".git").exists():
        return SourceIdentity(repository=repository)
    try:
        commit = subprocess.run(
            [git, "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            [git, "status", "--porcelain"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return SourceIdentity(repository=repository)
    return SourceIdentity(repository=repository, commit_sha=commit or None, dirty=bool(status.strip()))


def _safe_environment(root: Path) -> dict[str, str]:
    home = root / ".xt-aegis" / "verification-home"
    home.mkdir(parents=True, exist_ok=True)
    return {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": str(root / "src"),
        "PYTHONPYCACHEPREFIX": str(home / "pycache"),
        "COVERAGE_FILE": str(home / ".coverage"),
        "RUFF_CACHE_DIR": str(home / "ruff-cache"),
        "MYPY_CACHE_DIR": str(home / "mypy-cache"),
    }


def validate_recipe_policy(recipe: VerificationRecipe, registry: EvidenceRegistry) -> None:
    """Reject executable authority not declared by the repository verification contract."""

    executable = Path(recipe.argv[0]).name
    if recipe.argv[0] != executable:
        raise VerificationPolicyError("absolute or path-qualified executables are not allowed")
    if executable not in registry.verification_contract.executable_allowlist:
        raise VerificationPolicyError(f"executable is not allowlisted: {executable}")
    if executable in {"python", "python3"} and "-c" in recipe.argv[1:]:
        raise VerificationPolicyError("inline interpreter code is not allowed in verification recipes")
    if recipe.network.value != "deny":
        raise VerificationPolicyError("only default-deny network recipes are supported")


def _run_process(argv: list[str], cwd: Path, timeout_seconds: int, max_output_bytes: int) -> CommandEvidence:
    started = time.perf_counter()
    timed_out = False
    exit_code: int | None
    stdout = ""
    stderr = ""
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=_safe_environment(cwd),
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = None
        if isinstance(exc.stdout, bytes):
            stdout = exc.stdout.decode(errors="replace")
        elif isinstance(exc.stdout, str):
            stdout = exc.stdout
        if isinstance(exc.stderr, bytes):
            stderr = exc.stderr.decode(errors="replace")
        elif isinstance(exc.stderr, str):
            stderr = exc.stderr
        stderr = f"{stderr}\nverification timed out after {timeout_seconds}s".strip()
    duration_ms = (time.perf_counter() - started) * 1000
    stdout, stdout_truncated = _truncate(stdout, max_output_bytes)
    stderr, stderr_truncated = _truncate(stderr, max_output_bytes)
    return CommandEvidence(
        argv=argv,
        cwd=str(cwd),
        exit_code=exit_code,
        duration_ms=duration_ms,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        timed_out=timed_out,
    )


class UnsafeLocalBackend:
    """Explicit development backend; it is not an isolation boundary."""

    name = BackendName.UNSAFE_LOCAL
    strong_isolation = False

    def availability(self, root: Path) -> BackendAvailability:
        del root
        return BackendAvailability(
            name=self.name,
            available=True,
            executable=sys.executable,
            strong_isolation=False,
            reason="available only through explicit user opt-in; no OS isolation is provided",
        )

    def preview(self, recipe: VerificationRecipe, root: Path) -> list[str]:
        del root
        return list(recipe.argv)

    def run(self, recipe: VerificationRecipe, root: Path) -> BackendExecution:
        cwd = (root / recipe.cwd).resolve()
        if not cwd.is_relative_to(root):
            raise VerificationPolicyError("recipe cwd escaped the verification root")
        command = _run_process(list(recipe.argv), cwd, recipe.timeout_seconds, recipe.max_output_bytes)
        return BackendExecution(command=command, policy_sha256=None)


class OpenShellBackend:
    """NVIDIA OpenShell adapter using a default-deny policy file."""

    name = BackendName.OPENSHELL
    strong_isolation = True

    def _policy_path(self, root: Path) -> Path:
        override = os.getenv("XT_AEGIS_OPENSHELL_POLICY")
        return (
            Path(override).expanduser().resolve()
            if override
            else root / "verification/policies/openshell.yaml"
        )

    def availability(self, root: Path) -> BackendAvailability:
        executable = shutil.which("openshell")
        policy = self._policy_path(root)
        if executable is None:
            return BackendAvailability(
                name=self.name,
                available=False,
                strong_isolation=True,
                reason="openshell executable was not found",
            )
        if not policy.is_file():
            return BackendAvailability(
                name=self.name,
                available=False,
                executable=executable,
                strong_isolation=True,
                reason=f"OpenShell policy was not found: {policy}",
            )
        return BackendAvailability(
            name=self.name,
            available=True,
            executable=executable,
            strong_isolation=True,
            reason="OpenShell executable and default-deny policy are available",
        )

    def preview(self, recipe: VerificationRecipe, root: Path) -> list[str]:
        executable = shutil.which("openshell") or "openshell"
        image = os.getenv("XT_AEGIS_OPENSHELL_IMAGE", _DEFAULT_IMAGE)
        return [
            executable,
            "sandbox",
            "create",
            "--from",
            image,
            "--policy",
            str(self._policy_path(root)),
            "--cpu",
            "1",
            "--memory",
            "1Gi",
            "--no-auto-providers",
            "--approval-mode",
            "manual",
            "--no-tty",
            "--upload",
            ".:/workspace",
            "--env",
            "PYTHONPATH=/workspace/src",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "PYTHONUNBUFFERED=1",
            "--env",
            "COVERAGE_FILE=/tmp/.coverage",
            "--env",
            "RUFF_CACHE_DIR=/tmp/ruff-cache",
            "--env",
            "MYPY_CACHE_DIR=/tmp/mypy-cache",
            "--no-keep",
            "--",
            "python",
            "-m",
            "xt_aegis.sandbox_exec",
            "--root",
            "/workspace",
            "--cwd",
            recipe.cwd,
            "--",
            *recipe.argv,
        ]

    def run(self, recipe: VerificationRecipe, root: Path) -> BackendExecution:
        availability = self.availability(root)
        if not availability.available:
            raise FileNotFoundError(availability.reason)
        policy = self._policy_path(root)
        command = _run_process(
            self.preview(recipe, root),
            root.resolve(),
            recipe.timeout_seconds,
            recipe.max_output_bytes,
        )
        return BackendExecution(command=command, policy_sha256=_sha256_file(policy))


class OciBackend:
    """Rootless Docker or Podman verifier image adapter."""

    strong_isolation = True

    def __init__(self, name: BackendName) -> None:
        if name not in {BackendName.DOCKER, BackendName.PODMAN}:
            raise ValueError(f"unsupported OCI backend: {name}")
        self.name = name

    def availability(self, root: Path) -> BackendAvailability:
        del root
        executable = shutil.which(self.name.value)
        if executable is None:
            return BackendAvailability(
                name=self.name,
                available=False,
                strong_isolation=True,
                reason=f"{self.name.value} executable was not found",
            )
        try:
            if self.name == BackendName.PODMAN:
                probe = subprocess.run(
                    [executable, "info", "--format", "json"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if probe.returncode != 0:
                    raise VerificationError(probe.stderr.strip() or "Podman runtime probe failed")
                payload = json.loads(probe.stdout)
                host = payload.get("host", {}) if isinstance(payload, dict) else {}
                security = host.get("security", {}) if isinstance(host, dict) else {}
                rootless = security.get("rootless") if isinstance(security, dict) else None
                if rootless is not True:
                    return BackendAvailability(
                        name=self.name,
                        available=False,
                        executable=executable,
                        strong_isolation=True,
                        reason="Podman is reachable but rootless mode was not confirmed",
                    )
            else:
                probe = subprocess.run(
                    [executable, "info", "--format", "{{json .ServerVersion}}"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if probe.returncode != 0:
                    raise VerificationError(probe.stderr.strip() or "Docker runtime probe failed")
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, VerificationError) as exc:
            return BackendAvailability(
                name=self.name,
                available=False,
                executable=executable,
                strong_isolation=True,
                reason=f"{self.name.value} runtime is not ready: {exc}",
            )
        return BackendAvailability(
            name=self.name,
            available=True,
            executable=executable,
            strong_isolation=True,
            reason=(
                "rootless Podman runtime is available"
                if self.name == BackendName.PODMAN
                else "Docker runtime is available"
            ),
        )

    def preview(self, recipe: VerificationRecipe, root: Path) -> list[str]:
        executable = shutil.which(self.name.value) or self.name.value
        image = os.getenv("XT_AEGIS_VERIFIER_IMAGE", _DEFAULT_IMAGE)
        root_string = str(root.resolve())
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
            f"type=bind,src={root_string},dst=/workspace,readonly",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=536870912",
            "--workdir",
            f"/workspace/{recipe.cwd}" if recipe.cwd != "." else "/workspace",
            "--env",
            "PYTHONPATH=/workspace/src",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "PYTHONUNBUFFERED=1",
            "--env",
            "COVERAGE_FILE=/tmp/.coverage",
            "--env",
            "RUFF_CACHE_DIR=/tmp/ruff-cache",
            "--env",
            "MYPY_CACHE_DIR=/tmp/mypy-cache",
            image,
            *recipe.argv,
        ]

    def run(self, recipe: VerificationRecipe, root: Path) -> BackendExecution:
        availability = self.availability(root)
        if not availability.available:
            raise FileNotFoundError(availability.reason)
        preview = self.preview(recipe, root)
        command = _run_process(preview, root, recipe.timeout_seconds, recipe.max_output_bytes)
        policy = {
            "backend": self.name.value,
            "network": "none",
            "read_only_root": True,
            "read_only_source": True,
            "cap_drop": "ALL",
            "no_new_privileges": True,
            "pids_limit": 128,
            "memory": "1g",
            "cpus": "1",
            "image": os.getenv("XT_AEGIS_VERIFIER_IMAGE", _DEFAULT_IMAGE),
        }
        return BackendExecution(command=command, policy_sha256=_sha256_bytes(_canonical_json(policy)))


def backends() -> dict[BackendName, SandboxBackend]:
    """Construct available backend adapters."""

    return {
        BackendName.OPENSHELL: OpenShellBackend(),
        BackendName.PODMAN: OciBackend(BackendName.PODMAN),
        BackendName.DOCKER: OciBackend(BackendName.DOCKER),
        BackendName.UNSAFE_LOCAL: UnsafeLocalBackend(),
    }


def select_backend(requested: BackendName, root: Path) -> SandboxBackend:
    """Select a strong backend, never silently falling back to local execution."""

    available = backends()
    if requested != BackendName.AUTO:
        return available[requested]
    for name in (BackendName.OPENSHELL, BackendName.PODMAN, BackendName.DOCKER):
        backend_option = available[name]
        if backend_option.availability(root).available:
            return backend_option
    raise FileNotFoundError(
        "no strong verification backend is available; install OpenShell, rootless Podman, or Docker, "
        "or explicitly choose --backend unsafe-local for development"
    )


def doctor(
    *,
    registry_path: str | Path | None = None,
    root: str | Path | None = None,
    requested_backend: BackendName = BackendName.AUTO,
) -> DoctorReport:
    """Inspect verifier prerequisites without executing repository code."""

    loaded = load_registry(registry_path, root)
    verification_root = resolve_verification_root(loaded, root)
    availability = [backend.availability(verification_root) for backend in backends().values()]
    selected: BackendName | None = None
    notes: list[str] = []
    try:
        selected_backend = select_backend(requested_backend, verification_root)
        selected_availability = selected_backend.availability(verification_root)
        if selected_availability.available:
            selected = selected_backend.name
        else:
            notes.append(selected_availability.reason)
    except FileNotFoundError as exc:
        notes.append(str(exc))
    if selected == BackendName.UNSAFE_LOCAL:
        notes.append("unsafe-local is not a sandbox and must not be reported as independent isolation")
    return DoctorReport(
        project=loaded.registry.project,
        project_version=loaded.registry.version,
        repository_root=str(verification_root),
        registry_path=loaded.display_path,
        registry_sha256=loaded.sha256,
        python_version=platform.python_version(),
        backends=availability,
        selected_backend=selected,
        notes=notes,
    )


def verification_plan(
    *,
    claim_id: str,
    backend_name: BackendName,
    registry_path: str | Path | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Return a non-executing, machine-readable plan for one claim."""

    loaded = load_registry(registry_path, root)
    verification_root = resolve_verification_root(loaded, root)
    claim = loaded.registry.claim_by_id(claim_id)
    if claim.verification is None:
        return {
            "claim_id": claim_id,
            "declared_status": claim.status.value,
            "executable": False,
            "reason": "claim has no verification recipe",
        }
    validate_recipe_policy(claim.verification, loaded.registry)
    try:
        backend = select_backend(backend_name, verification_root)
    except FileNotFoundError as exc:
        return {
            "claim_id": claim_id,
            "declared_status": claim.status.value,
            "executable": False,
            "requested_backend": backend_name.value,
            "reason": str(exc),
            "recipe": claim.verification.model_dump(mode="json"),
        }
    availability = backend.availability(verification_root)
    return {
        "claim_id": claim_id,
        "declared_status": claim.status.value,
        "executable": availability.available,
        "backend": backend.name.value,
        "strong_isolation": backend.strong_isolation,
        "availability_reason": availability.reason,
        "host_argv": backend.preview(claim.verification, verification_root),
        "recipe": claim.verification.model_dump(mode="json"),
    }


def _hash_artifacts(recipe: VerificationRecipe, root: Path) -> dict[str, str]:
    artifact_hashes: dict[str, str] = {}
    for relative in recipe.artifacts:
        artifact_path = (root / relative).resolve()
        if artifact_path.is_relative_to(root) and artifact_path.is_file():
            artifact_hashes[relative] = _sha256_file(artifact_path)
    return artifact_hashes


def _inconclusive_result(
    *,
    loaded: LoadedRegistry,
    claim: VerificationClaim,
    backend_name: BackendName,
    source: SourceIdentity,
    reason: str,
    status: VerificationStatus = VerificationStatus.INCONCLUSIVE,
) -> VerificationResult:
    now = _utc_now()
    return VerificationResult(
        project=loaded.registry.project,
        project_version=loaded.registry.version,
        claim_id=claim.id,
        claim=claim.claim,
        declared_status=claim.status,
        status=status,
        backend=backend_name,
        source=source,
        registry_sha256=loaded.sha256,
        started_at=now,
        finished_at=now,
        limitations=claim.limitations,
        reason=reason,
    )


def verify_claim(
    *,
    claim_id: str,
    backend_name: BackendName,
    registry_path: str | Path | None = None,
    root: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> VerificationResult:
    """Verify one claim and persist a structured result when requested."""

    loaded = load_registry(registry_path, root)
    verification_root = resolve_verification_root(loaded, root)
    source = source_identity(verification_root, loaded.registry.repository)
    claim = loaded.registry.claim_by_id(claim_id)

    if claim.status not in {RegistryClaimStatus.IMPLEMENTED, RegistryClaimStatus.VERIFIED_IN_CI}:
        result = _inconclusive_result(
            loaded=loaded,
            claim=claim,
            backend_name=backend_name,
            source=source,
            reason=f"claim is declared {claim.status.value} and cannot be promoted by the verifier",
        )
        _write_result(result, output_dir)
        return result
    if claim.verification is None:
        result = _inconclusive_result(
            loaded=loaded,
            claim=claim,
            backend_name=backend_name,
            source=source,
            status=VerificationStatus.ERROR,
            reason="implemented claim has no recipe",
        )
        _write_result(result, output_dir)
        return result

    started_at = _utc_now()
    recipe_hash = _sha256_bytes(_canonical_json(claim.verification.model_dump(mode="json")))
    try:
        validate_recipe_policy(claim.verification, loaded.registry)
    except VerificationPolicyError as exc:
        result = VerificationResult(
            project=loaded.registry.project,
            project_version=loaded.registry.version,
            claim_id=claim.id,
            claim=claim.claim,
            declared_status=claim.status,
            status=VerificationStatus.POLICY_DENIED,
            backend=backend_name,
            source=source,
            registry_sha256=loaded.sha256,
            recipe_sha256=recipe_hash,
            started_at=started_at,
            finished_at=_utc_now(),
            limitations=claim.limitations,
            reason=str(exc),
        )
        _write_result(result, output_dir)
        return result

    try:
        backend = select_backend(backend_name, verification_root)
        availability = backend.availability(verification_root)
        if not availability.available:
            raise FileNotFoundError(availability.reason)
        execution = backend.run(claim.verification, verification_root)
    except FileNotFoundError as exc:
        result = VerificationResult(
            project=loaded.registry.project,
            project_version=loaded.registry.version,
            claim_id=claim.id,
            claim=claim.claim,
            declared_status=claim.status,
            status=VerificationStatus.UNSUPPORTED,
            backend=backend_name,
            source=source,
            registry_sha256=loaded.sha256,
            recipe_sha256=recipe_hash,
            started_at=started_at,
            finished_at=_utc_now(),
            limitations=claim.limitations,
            reason=str(exc),
        )
        _write_result(result, output_dir)
        return result
    except (OSError, subprocess.SubprocessError, VerificationError) as exc:
        result = VerificationResult(
            project=loaded.registry.project,
            project_version=loaded.registry.version,
            claim_id=claim.id,
            claim=claim.claim,
            declared_status=claim.status,
            status=VerificationStatus.ERROR,
            backend=backend_name,
            source=source,
            registry_sha256=loaded.sha256,
            recipe_sha256=recipe_hash,
            started_at=started_at,
            finished_at=_utc_now(),
            limitations=claim.limitations,
            reason=f"{type(exc).__name__}: {exc}",
        )
        _write_result(result, output_dir)
        return result

    command = execution.command
    verified = not command.timed_out and command.exit_code in claim.verification.expected_exit_codes
    status = VerificationStatus.VERIFIED if verified else VerificationStatus.FAILED
    reason = (
        "recipe completed with an expected exit code"
        if verified
        else "recipe timed out or returned an unexpected exit code"
    )
    result = VerificationResult(
        project=loaded.registry.project,
        project_version=loaded.registry.version,
        claim_id=claim.id,
        claim=claim.claim,
        declared_status=claim.status,
        status=status,
        backend=backend.name,
        source=source,
        registry_sha256=loaded.sha256,
        recipe_sha256=recipe_hash,
        policy_sha256=execution.policy_sha256,
        started_at=started_at,
        finished_at=_utc_now(),
        command=command,
        artifacts=_hash_artifacts(claim.verification, verification_root),
        limitations=claim.limitations,
        reason=reason,
    )
    _write_result(result, output_dir)
    return result


def _write_result(result: VerificationResult, output_dir: str | Path | None) -> None:
    if output_dir is None:
        return
    root = Path(output_dir).expanduser().resolve()
    claim_dir = root / result.claim_id
    claim_dir.mkdir(parents=True, exist_ok=True)
    (claim_dir / _RESULT_FILENAME).write_text(result.model_dump_json(indent=2), encoding="utf-8")


def _overall_status(results: list[VerificationResult]) -> VerificationStatus:
    priorities = [
        VerificationStatus.ERROR,
        VerificationStatus.FAILED,
        VerificationStatus.POLICY_DENIED,
        VerificationStatus.UNSUPPORTED,
        VerificationStatus.INCONCLUSIVE,
    ]
    for status in priorities:
        if any(result.status == status for result in results):
            return status
    return VerificationStatus.VERIFIED


def verify_many(
    *,
    claim_ids: list[str] | None,
    backend_name: BackendName,
    registry_path: str | Path | None = None,
    root: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> VerificationSummary:
    """Verify selected runnable claims and emit an aggregate summary."""

    loaded = load_registry(registry_path, root)
    verification_root = resolve_verification_root(loaded, root)
    source = source_identity(verification_root, loaded.registry.repository)
    selected_ids = claim_ids or [
        claim.id
        for claim in loaded.registry.claims
        if claim.status in {RegistryClaimStatus.IMPLEMENTED, RegistryClaimStatus.VERIFIED_IN_CI}
    ]
    started_at = _utc_now()
    results = [
        verify_claim(
            claim_id=claim_id,
            backend_name=backend_name,
            registry_path=registry_path,
            root=verification_root,
            output_dir=output_dir,
        )
        for claim_id in selected_ids
    ]
    counts = {
        status.value: sum(result.status == status for result in results) for status in VerificationStatus
    }
    summary = VerificationSummary(
        project=loaded.registry.project,
        project_version=loaded.registry.version,
        backend=results[0].backend if results else backend_name,
        source=source,
        registry_sha256=loaded.sha256,
        started_at=started_at,
        finished_at=_utc_now(),
        results=results,
        counts=counts,
        overall_status=_overall_status(results),
    )
    if output_dir is not None:
        output_root = Path(output_dir).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        (output_root / _SUMMARY_FILENAME).write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    return summary


def result_exit_code(status: VerificationStatus) -> int:
    """Map a structured verdict to a stable process exit code."""

    return EXIT_CODES[status]


def pack_evidence(
    input_dir: str | Path, output_path: str | Path, *, project: str = "XT-Aegis"
) -> dict[str, Any]:
    """Create a deterministic gzip-compressed tar archive with SHA-256 entries."""

    source = Path(input_dir).expanduser().resolve()
    destination = Path(output_path).expanduser().resolve()
    if not source.is_dir():
        raise VerificationError(f"evidence input is not a directory: {source}")
    if destination.is_relative_to(source):
        raise VerificationPolicyError("evidence archive must be written outside the input directory")

    files_to_pack = sorted(path for path in source.rglob("*") if path.is_file())
    entries = [
        EvidenceBundleFile(
            path=path.relative_to(source).as_posix(),
            sha256=_sha256_file(path),
            size_bytes=path.stat().st_size,
        )
        for path in files_to_pack
    ]
    manifest = EvidenceBundleManifest(project=project, created_at="1970-01-01T00:00:00+00:00", files=entries)
    manifest_bytes = manifest.model_dump_json(indent=2).encode()

    tar_buffer = BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for path in files_to_pack:
            relative = path.relative_to(source).as_posix()
            data = path.read_bytes()
            info = tarfile.TarInfo(relative)
            info.size = len(data)
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mode = 0o644
            archive.addfile(info, BytesIO(data))
        manifest_info = tarfile.TarInfo("manifest.json")
        manifest_info.size = len(manifest_bytes)
        manifest_info.mtime = 0
        manifest_info.uid = 0
        manifest_info.gid = 0
        manifest_info.uname = ""
        manifest_info.gname = ""
        manifest_info.mode = 0o644
        archive.addfile(manifest_info, BytesIO(manifest_bytes))

    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        destination.open("wb") as raw_handle,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as compressed,
    ):
        compressed.write(tar_buffer.getvalue())
    return {
        "path": str(destination),
        "sha256": _sha256_file(destination),
        "size_bytes": destination.stat().st_size,
        "file_count": len(entries),
        "manifest": manifest.model_dump(mode="json"),
    }
