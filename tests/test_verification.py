from __future__ import annotations

import json
import shutil
import tarfile
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


def test_openshell_backend_builds_documented_argv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    policy = tmp_path / "verification/policies/openshell.yaml"
    policy.parent.mkdir(parents=True)
    policy.write_text("version: 1\nnetwork_policies: {}\n", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda value: "/usr/bin/openshell" if value == "openshell" else None)
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
        "HOME=/home/verifier",
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
    policy = tmp_path / "verification/policies/openshell.yaml"
    policy.parent.mkdir(parents=True)
    policy.write_text("version: 1\nnetwork_policies: {}\n", encoding="utf-8")
    nested = tmp_path / "tests"
    nested.mkdir()
    monkeypatch.setattr(shutil, "which", lambda value: "/usr/bin/openshell" if value == "openshell" else None)
    observed: dict[str, object] = {}

    def fake_run_process(argv: list[str], cwd: Path, timeout_seconds: int, max_output_bytes: int) -> object:
        observed.update(
            argv=argv,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
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
    recipe = VerificationRecipe(argv=["python", "--version"], cwd="tests")
    OpenShellBackend().run(recipe, tmp_path)

    assert observed["cwd"] == tmp_path.resolve()
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


def test_openshell_backend_requires_policy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda value: "/usr/bin/openshell" if value == "openshell" else None)
    availability = OpenShellBackend().availability(tmp_path)
    assert availability.available is False
    assert "policy" in availability.reason


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
