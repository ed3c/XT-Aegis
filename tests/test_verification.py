from __future__ import annotations

import json
import shutil
import tarfile
from collections.abc import Mapping
from pathlib import Path

import pytest

from xt_aegis import verification
from xt_aegis.verification import (
    OciBackend,
    OpenShellBackend,
    VerificationError,
    VerificationPolicyError,
    doctor,
    load_registry,
    pack_evidence,
    select_backend,
    validate_recipe_policy,
    verification_plan,
    verify_claim,
    verify_many,
)
from xt_aegis.verification_models import (
    BackendName,
    EvidenceRegistry,
    VerificationRecipe,
    VerificationStatus,
)


def _registry_payload(*, status: str = "implemented", argv: list[str] | None = None) -> dict[str, object]:
    recipe = None
    expected = None
    if status in {"implemented", "verified-in-ci"}:
        recipe = {
            "argv": argv or ["python", "--version"],
            "cwd": ".",
            "timeout_seconds": 30,
            "expected_exit_codes": [0],
            "network": "deny",
            "max_output_bytes": 4096,
            "artifacts": ["artifact.txt"],
        }
        expected = {"status": "verified", "assertions": {}}
    return {
        "schema_version": "2.0",
        "project": "XT-Aegis",
        "version": "0.test",
        "maturity": "test",
        "license": "MIT",
        "repository": "https://example.invalid/XT-Aegis",
        "verification_contract": {
            "executable_allowlist": ["python", "python3", "pytest"],
            "default_backend": "auto",
            "strong_backends": ["openshell", "podman", "docker"],
            "unsafe_local_requires_explicit_opt_in": True,
            "environment_allowlist": [],
        },
        "claims": [
            {
                "id": "test-claim",
                "claim": "A bounded test claim.",
                "status": status,
                "evidence": ["artifact.txt"],
                "verification": recipe,
                "expected": expected,
                "limitations": ["test limitation"],
            }
        ],
    }


def _write_registry(root: Path, *, status: str = "implemented", argv: list[str] | None = None) -> Path:
    path = root / "PROJECT_EVIDENCE.json"
    path.write_text(json.dumps(_registry_payload(status=status, argv=argv)), encoding="utf-8")
    (root / "artifact.txt").write_text("evidence", encoding="utf-8")
    return path


def test_registry_and_recipe_are_strict(tmp_path: Path) -> None:
    path = _write_registry(tmp_path)
    loaded = load_registry(path)
    assert loaded.registry.schema_version == "2.0"
    assert loaded.registry.claim_by_id("test-claim").verification is not None

    payload = _registry_payload()
    payload["unexpected"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(VerificationError):
        load_registry(path)

    with pytest.raises(ValueError):
        VerificationRecipe(argv=["python"], cwd="../escape")


def test_recipe_policy_rejects_path_and_inline_code(tmp_path: Path) -> None:
    registry = EvidenceRegistry.model_validate(_registry_payload())
    with pytest.raises(VerificationPolicyError):
        validate_recipe_policy(VerificationRecipe(argv=["/usr/bin/python", "--version"]), registry)
    with pytest.raises(VerificationPolicyError):
        validate_recipe_policy(VerificationRecipe(argv=["python", "-c", "print('unsafe')"]), registry)
    with pytest.raises(VerificationPolicyError):
        validate_recipe_policy(VerificationRecipe(argv=["bash", "-lc", "true"]), registry)


def test_auto_backend_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(FileNotFoundError):
        select_backend(BackendName.AUTO, tmp_path)
    assert select_backend(BackendName.UNSAFE_LOCAL, tmp_path).name == BackendName.UNSAFE_LOCAL


def test_doctor_reports_explicit_local_backend(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path)
    report = doctor(
        registry_path=registry,
        root=tmp_path,
        requested_backend=BackendName.UNSAFE_LOCAL,
    )
    assert report.selected_backend == BackendName.UNSAFE_LOCAL
    assert any("not a sandbox" in note for note in report.notes)
    assert report.registry_sha256


def test_verify_claim_local_success_and_artifact(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path)
    output = tmp_path / "results"
    result = verify_claim(
        claim_id="test-claim",
        backend_name=BackendName.UNSAFE_LOCAL,
        registry_path=registry,
        root=tmp_path,
        output_dir=output,
    )
    assert result.status == VerificationStatus.VERIFIED
    assert result.command is not None
    assert result.command.exit_code == 0
    assert result.artifacts["artifact.txt"]
    assert (output / "test-claim" / "verification-result.json").is_file()


def test_verify_claim_failure_and_planned_claim(tmp_path: Path) -> None:
    failing = _write_registry(tmp_path, argv=["python", "--definitely-invalid"])
    result = verify_claim(
        claim_id="test-claim",
        backend_name=BackendName.UNSAFE_LOCAL,
        registry_path=failing,
        root=tmp_path,
    )
    assert result.status == VerificationStatus.FAILED

    planned_root = tmp_path / "planned"
    planned_root.mkdir()
    planned = _write_registry(planned_root, status="planned")
    planned_result = verify_claim(
        claim_id="test-claim",
        backend_name=BackendName.AUTO,
        registry_path=planned,
        root=planned_root,
    )
    assert planned_result.status == VerificationStatus.INCONCLUSIVE


def test_verify_many_writes_summary(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path)
    output = tmp_path / "out"
    summary = verify_many(
        claim_ids=None,
        backend_name=BackendName.UNSAFE_LOCAL,
        registry_path=registry,
        root=tmp_path,
        output_dir=output,
    )
    assert summary.overall_status == VerificationStatus.VERIFIED
    assert summary.counts["verified"] == 1
    assert (output / "verification-summary.json").is_file()


def test_verification_plan_never_executes(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path)
    plan = verification_plan(
        claim_id="test-claim",
        backend_name=BackendName.UNSAFE_LOCAL,
        registry_path=registry,
        root=tmp_path,
    )
    assert plan["executable"] is True
    assert plan["host_argv"] == ["python", "--version"]


def _install_openshell_policy(root: Path) -> Path:
    policy = root / "verification/policies/openshell.yaml"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text("version: 1\nnetwork_policies: {}\n", encoding="utf-8")
    return policy


def _stub_openshell_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    version_stdout: str = "openshell version 0.0.52",
    version_exit: int | None = 0,
    status_exit: int | None = 0,
    status_stderr: str = "",
    status_timed_out: bool = False,
) -> list[dict[str, object]]:
    """Answer readiness probes and sandbox launches without a real OpenShell installation."""

    calls: list[dict[str, object]] = []

    def fake_run_process(
        argv: list[str],
        cwd: Path,
        timeout_seconds: int,
        max_output_bytes: int,
        environment_overrides: Mapping[str, str] | None = None,
    ) -> verification.CommandEvidence:
        calls.append({"argv": argv, "cwd": cwd, "environment_overrides": environment_overrides})
        if argv[1:] == ["--version"]:
            return verification.CommandEvidence(
                argv=argv,
                cwd=str(cwd),
                exit_code=version_exit,
                duration_ms=1.0,
                stdout=version_stdout,
                stderr="",
            )
        if argv[1:] == ["status"]:
            return verification.CommandEvidence(
                argv=argv,
                cwd=str(cwd),
                exit_code=None if status_timed_out else status_exit,
                duration_ms=1.0,
                stdout="",
                stderr=status_stderr,
                timed_out=status_timed_out,
            )
        return verification.CommandEvidence(
            argv=argv,
            cwd=str(cwd),
            exit_code=0,
            duration_ms=1.0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(verification, "_run_process", fake_run_process)
    return calls


def _readiness_by_component(availability: object) -> dict[str, tuple[bool, str]]:
    components = availability.components  # type: ignore[attr-defined]
    return {item.component.value: (item.ready, item.reason) for item in components}


def test_openshell_backend_builds_documented_argv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    policy = _install_openshell_policy(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda value: "/usr/bin/openshell" if value == "openshell" else None)
    _stub_openshell_runtime(monkeypatch)
    backend = OpenShellBackend()
    availability = backend.availability(tmp_path)
    assert availability.available is True
    preview = backend.preview(VerificationRecipe(argv=["python", "--version"]), tmp_path)
    assert preview == [
        "/usr/bin/openshell",
        "sandbox",
        "create",
        "--from",
        "ghcr.io/ed3c/xt-aegis-verifier:0.2.0",
        "--policy",
        str(policy),
        "--cpu",
        "1",
        "--memory",
        "1Gi",
        "--no-auto-providers",
        "--no-tty",
        "--upload",
        ".:/workspace",
        "--no-keep",
        "--",
        "env",
        "HOME=/sandbox",
        "PYTHONPATH=/workspace/src",
        "PYTHONDONTWRITEBYTECODE=1",
        "PYTHONUNBUFFERED=1",
        "PYTHONPYCACHEPREFIX=/tmp/pycache",
        "COVERAGE_FILE=/tmp/.coverage",
        "RUFF_CACHE_DIR=/tmp/ruff-cache",
        "MYPY_CACHE_DIR=/tmp/mypy-cache",
        "python",
        "-m",
        "xt_aegis.sandbox_exec",
        "--root",
        "/workspace",
        "--cwd",
        ".",
        "--",
        "python",
        "--version",
    ]


def test_openshell_backend_runs_host_command_from_source_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_openshell_policy(tmp_path)
    nested = tmp_path / "tests"
    nested.mkdir()
    monkeypatch.setattr(shutil, "which", lambda value: "/usr/bin/openshell" if value == "openshell" else None)
    calls = _stub_openshell_runtime(monkeypatch)

    recipe = VerificationRecipe(argv=["python", "--version"], cwd="tests")
    OpenShellBackend().run(recipe, tmp_path)

    observed = calls[-1]
    assert observed["cwd"] == tmp_path.resolve()
    assert observed["environment_overrides"] == verification._openshell_host_environment()
    assert ".:/workspace" in observed["argv"]
    assert observed["argv"][-7:] == [
        "--root",
        "/workspace",
        "--cwd",
        "tests",
        "--",
        "python",
        "--version",
    ]


def test_openshell_host_environment_forwards_gateway_state_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", "/home/user")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/home/user/.config")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    monkeypatch.setenv("OPENSHELL_TELEMETRY_ENABLED", "false")
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-cross")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-cross")

    environment = verification._openshell_host_environment()

    assert environment == {
        "HOME": "/home/user",
        "XDG_CONFIG_HOME": "/home/user/.config",
        "XDG_RUNTIME_DIR": "/run/user/1000",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
        "OPENSHELL_TELEMETRY_ENABLED": "false",
    }
    assert "GITHUB_TOKEN" not in environment
    assert "AWS_SECRET_ACCESS_KEY" not in environment


def test_openshell_backend_requires_policy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda value: "/usr/bin/openshell" if value == "openshell" else None)
    availability = OpenShellBackend().availability(tmp_path)
    assert availability.available is False
    assert "policy" in availability.reason
    readiness = _readiness_by_component(availability)
    assert readiness["executable"][0] is True
    assert readiness["policy"][0] is False
    assert readiness["version"] == (False, "not probed because the policy component is not ready")
    assert readiness["gateway"][0] is False


def test_openshell_readiness_reports_missing_executable_without_probing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(shutil, "which", lambda value: None)
    probes = _stub_openshell_runtime(monkeypatch)
    availability = OpenShellBackend().availability(tmp_path)
    assert availability.available is False
    assert probes == []
    readiness = _readiness_by_component(availability)
    assert readiness["executable"] == (False, "openshell executable was not found")
    assert all(not ready for ready, _ in readiness.values())


def test_openshell_readiness_rejects_unreviewed_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_openshell_policy(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda value: "/usr/bin/openshell" if value == "openshell" else None)
    _stub_openshell_runtime(monkeypatch, version_stdout="openshell version 9.9.9")
    availability = OpenShellBackend().availability(tmp_path)
    assert availability.available is False
    readiness = _readiness_by_component(availability)
    assert readiness["version"][0] is False
    assert "9.9.9" in readiness["version"][1]
    assert readiness["gateway"] == (False, "not probed because the version component is not ready")


def test_openshell_readiness_accepts_reviewed_version_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_openshell_policy(tmp_path)
    monkeypatch.setenv("XT_AEGIS_OPENSHELL_SUPPORTED_VERSION", "9.9.9")
    monkeypatch.setattr(shutil, "which", lambda value: "/usr/bin/openshell" if value == "openshell" else None)
    _stub_openshell_runtime(monkeypatch, version_stdout="openshell version 9.9.9")
    availability = OpenShellBackend().availability(tmp_path)
    assert availability.available is True


def test_openshell_readiness_rejects_unparsable_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_openshell_policy(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda value: "/usr/bin/openshell" if value == "openshell" else None)
    _stub_openshell_runtime(monkeypatch, version_stdout="openshell (development build)")
    availability = OpenShellBackend().availability(tmp_path)
    assert availability.available is False
    assert "no parsable version" in _readiness_by_component(availability)["version"][1]


def test_openshell_readiness_rejects_missing_gateway(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _install_openshell_policy(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda value: "/usr/bin/openshell" if value == "openshell" else None)
    _stub_openshell_runtime(monkeypatch, status_exit=1, status_stderr="Error: No active gateway")
    availability = OpenShellBackend().availability(tmp_path)
    assert availability.available is False
    ready, reason = _readiness_by_component(availability)["gateway"]
    assert ready is False
    assert "No active gateway" in reason


def test_openshell_readiness_rejects_unreachable_gateway(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_openshell_policy(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda value: "/usr/bin/openshell" if value == "openshell" else None)
    _stub_openshell_runtime(monkeypatch, status_timed_out=True)
    availability = OpenShellBackend().availability(tmp_path)
    assert availability.available is False
    assert "timed out" in _readiness_by_component(availability)["gateway"][1]


def test_openshell_readiness_probe_launch_failure_stays_bounded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_openshell_policy(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda value: "/usr/bin/openshell" if value == "openshell" else None)

    def exploding_run_process(*args: object, **kwargs: object) -> object:
        raise OSError("x" * 4096)

    monkeypatch.setattr(verification, "_run_process", exploding_run_process)
    availability = OpenShellBackend().availability(tmp_path)
    assert availability.available is False
    reason = _readiness_by_component(availability)["version"][1]
    assert "OSError" in reason
    assert len(reason) < 1024


def test_openshell_readiness_probe_uses_the_execution_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_openshell_policy(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda value: "/usr/bin/openshell" if value == "openshell" else None)
    calls = _stub_openshell_runtime(monkeypatch)
    OpenShellBackend().availability(tmp_path)
    assert [call["argv"][1:] for call in calls] == [["--version"], ["status"]]
    assert all(call["environment_overrides"] == verification._openshell_host_environment() for call in calls)


def test_auto_does_not_select_openshell_without_a_ready_gateway(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_openshell_policy(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda value: f"/usr/bin/{value}" if value == "openshell" else None)
    _stub_openshell_runtime(monkeypatch, status_exit=1, status_stderr="Error: No active gateway")
    with pytest.raises(FileNotFoundError):
        select_backend(BackendName.AUTO, tmp_path)


def test_unready_openshell_gateway_is_unsupported_not_a_failed_claim(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    registry = _write_registry(tmp_path)
    _install_openshell_policy(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda value: f"/usr/bin/{value}" if value == "openshell" else None)
    _stub_openshell_runtime(monkeypatch, status_exit=1, status_stderr="Error: No active gateway")
    result = verify_claim(
        claim_id="test-claim",
        backend_name=BackendName.OPENSHELL,
        registry_path=registry,
        root=tmp_path,
    )
    assert result.status == VerificationStatus.UNSUPPORTED
    assert "No active gateway" in result.reason


def test_doctor_reports_openshell_readiness_components(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    registry = _write_registry(tmp_path)
    _install_openshell_policy(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda value: f"/usr/bin/{value}" if value == "openshell" else None)
    _stub_openshell_runtime(monkeypatch, status_exit=1, status_stderr="Error: No active gateway")
    report = doctor(registry_path=registry, root=tmp_path, requested_backend=BackendName.AUTO)
    payload = report.model_dump(mode="json")
    openshell = next(entry for entry in payload["backends"] if entry["name"] == "openshell")
    assert [item["component"] for item in openshell["components"]] == [
        "executable",
        "policy",
        "version",
        "gateway",
    ]
    assert openshell["available"] is False
    assert report.selected_backend != BackendName.OPENSHELL


def test_oci_backend_has_default_deny_and_read_only_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(shutil, "which", lambda value: f"/usr/bin/{value}" if value == "docker" else None)
    backend = OciBackend(BackendName.DOCKER)
    preview = backend.preview(VerificationRecipe(argv=["python", "--version"]), tmp_path)
    assert preview[0] == "/usr/bin/docker"
    assert "none" in preview
    assert "--read-only" in preview
    assert "no-new-privileges" in preview
    assert any(item.endswith("dst=/workspace,readonly") for item in preview)
    assert preview[-2:] == ["python", "--version"]


def test_podman_availability_requires_confirmed_rootless_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(shutil, "which", lambda value: "/usr/bin/podman" if value == "podman" else None)

    def fake_run(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return __import__("subprocess").CompletedProcess(
            [], 0, stdout='{"host":{"security":{"rootless":false}}}', stderr=""
        )

    monkeypatch.setattr(verification.subprocess, "run", fake_run)
    availability = OciBackend(BackendName.PODMAN).availability(tmp_path)
    assert availability.available is False
    assert "rootless" in availability.reason


def test_docker_availability_requires_reachable_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(shutil, "which", lambda value: "/usr/bin/docker" if value == "docker" else None)

    def fake_run(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return __import__("subprocess").CompletedProcess([], 1, stdout="", stderr="daemon unavailable")

    monkeypatch.setattr(verification.subprocess, "run", fake_run)
    availability = OciBackend(BackendName.DOCKER).availability(tmp_path)
    assert availability.available is False
    assert "daemon unavailable" in availability.reason


def test_evidence_bundle_is_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "b.json").write_text('{"b": 2}\n', encoding="utf-8")
    (source / "a.json").write_text('{"a": 1}\n', encoding="utf-8")
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    first_result = pack_evidence(source, first)
    second_result = pack_evidence(source, second)
    assert first_result["sha256"] == second_result["sha256"]
    with tarfile.open(first, "r:gz") as archive:
        names = archive.getnames()
        assert names == ["a.json", "b.json", "manifest.json"]
        manifest = json.load(archive.extractfile("manifest.json"))  # type: ignore[arg-type]
    assert manifest["files"][0]["path"] == "a.json"


def test_evidence_bundle_rejects_output_inside_input(tmp_path: Path) -> None:
    with pytest.raises(VerificationPolicyError):
        pack_evidence(tmp_path, tmp_path / "bundle.tar.gz")


def test_output_truncation() -> None:
    value, truncated = verification._truncate("x" * 10_000, 1_024)
    assert truncated is True
    assert value.endswith("[output truncated by XT-Aegis]")


def test_doctor_does_not_select_missing_requested_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    registry = _write_registry(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda _: None)
    report = doctor(
        registry_path=registry,
        root=tmp_path,
        requested_backend=BackendName.OPENSHELL,
    )
    assert report.selected_backend is None
    assert any("not found" in note for note in report.notes)
