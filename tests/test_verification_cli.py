from __future__ import annotations

import json
from pathlib import Path

from xt_aegis import cli


def _write_registry(root: Path) -> Path:
    payload = {
        "schema_version": "2.0",
        "project": "XT-Aegis",
        "version": "0.test",
        "maturity": "test",
        "license": "MIT",
        "repository": "https://example.invalid/XT-Aegis",
        "verification_contract": {
            "executable_allowlist": ["python"],
            "default_backend": "auto",
            "strong_backends": ["openshell", "podman", "docker"],
            "unsafe_local_requires_explicit_opt_in": True,
            "environment_allowlist": [],
        },
        "claims": [
            {
                "id": "test-claim",
                "claim": "A test claim.",
                "status": "implemented",
                "evidence": ["artifact.txt"],
                "verification": {
                    "argv": ["python", "--version"],
                    "cwd": ".",
                    "timeout_seconds": 30,
                    "expected_exit_codes": [0],
                    "network": "deny",
                    "max_output_bytes": 4096,
                    "artifacts": ["artifact.txt"],
                },
                "expected": {"status": "verified", "assertions": {}},
                "limitations": [],
            }
        ],
    }
    path = root / "PROJECT_EVIDENCE.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    (root / "artifact.txt").write_text("artifact", encoding="utf-8")
    return path


def test_cli_doctor_plan_and_verify(tmp_path: Path, capsys: object) -> None:
    registry = _write_registry(tmp_path)
    assert (
        cli.main(
            [
                "doctor",
                "--registry",
                str(registry),
                "--root",
                str(tmp_path),
                "--backend",
                "unsafe-local",
            ]
        )
        == 0
    )
    assert "unsafe-local" in capsys.readouterr().out  # type: ignore[attr-defined]

    assert (
        cli.main(
            [
                "plan",
                "--claim",
                "test-claim",
                "--registry",
                str(registry),
                "--root",
                str(tmp_path),
                "--backend",
                "unsafe-local",
            ]
        )
        == 0
    )
    assert "host_argv" in capsys.readouterr().out  # type: ignore[attr-defined]

    output = tmp_path / "out"
    assert (
        cli.main(
            [
                "verify",
                "--all",
                "--registry",
                str(registry),
                "--root",
                str(tmp_path),
                "--backend",
                "unsafe-local",
                "--output-dir",
                str(output),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["overall_status"] == "verified"
    assert (output / "verification-summary.json").is_file()


def test_cli_evidence_pack(tmp_path: Path, capsys: object) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "result.json").write_text("{}\n", encoding="utf-8")
    output = tmp_path / "bundle.tar.gz"
    assert (
        cli.main(
            [
                "evidence",
                "pack",
                "--input",
                str(source),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["file_count"] == 1
    assert output.is_file()
