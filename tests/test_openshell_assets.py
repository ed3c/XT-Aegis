from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_openshell_policy_matches_verifier_image_contract() -> None:
    policy_path = ROOT / "verification/policies/openshell.yaml"
    policy = policy_path.read_text(encoding="utf-8")
    assert "run_as_user: sandbox" in policy
    assert "run_as_group: sandbox" in policy
    assert "compatibility: hard_requirement" in policy
    assert "network_policies: {}" in policy
    assert "include_workdir: true" in policy
    assert "    - /workspace" in policy

    dockerfile = (ROOT / "Dockerfile.verifier").read_text(encoding="utf-8")
    assert "ghcr.io/nvidia/openshell-community/sandboxes/base:latest" in dockerfile
    assert "/sandbox/.venv/bin/python -m pip install" in dockerfile
    assert "install -d -o sandbox -g sandbox /workspace" in dockerfile
    assert "USER sandbox" in dockerfile


def test_conformance_workflow_pins_driver_and_records_image_identity() -> None:
    workflow_path = ROOT / ".github/workflows/openshell-conformance.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    assert 'OPENSHELL_VERSION: "v0.0.52"' in workflow
    assert 'compute_drivers = ["docker"]' in workflow
    assert "OPENSHELL_DRIVERS=docker" in workflow
    assert "openshell-base-image.json" in workflow
    assert "verifier-image.json" in workflow
    assert "gateway-journal.txt" in workflow
    assert "xt-aegis-openshell-diagnostics.tar.gz" in workflow
