from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_openshell_policy_matches_verifier_image_identity() -> None:
    policy = yaml.safe_load((ROOT / "verification/policies/openshell.yaml").read_text(encoding="utf-8"))
    assert policy["process"] == {
        "run_as_user": "verifier",
        "run_as_group": "verifier",
    }
    assert policy["landlock"]["compatibility"] == "hard_requirement"
    assert policy["network_policies"] == {}
    assert policy["filesystem_policy"]["include_workdir"] is True

    dockerfile = (ROOT / "Dockerfile.verifier").read_text(encoding="utf-8")
    assert "useradd --create-home --uid 10001 verifier" in dockerfile
    assert "install -d -o verifier -g verifier /workspace" in dockerfile
    assert "USER verifier" in dockerfile


def test_conformance_workflow_pins_docker_driver_and_retains_diagnostics() -> None:
    workflow = (ROOT / ".github/workflows/openshell-conformance.yml").read_text(encoding="utf-8")
    assert 'OPENSHELL_VERSION: "v0.0.52"' in workflow
    assert 'compute_drivers = ["docker"]' in workflow
    assert "OPENSHELL_DRIVERS=docker" in workflow
    assert "policy_validation_failure_mode" in workflow
    assert "gateway-journal.txt" in workflow
    assert "xt-aegis-openshell-diagnostics.tar.gz" in workflow
