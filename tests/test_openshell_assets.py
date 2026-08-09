from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_openshell_policy_matches_verifier_image_identity() -> None:
    policy_path = ROOT / "verification/policies/openshell.yaml"
    policy = policy_path.read_text(encoding="utf-8")
    assert "run_as_user: verifier" in policy
    assert "run_as_group: verifier" in policy
    assert "compatibility: hard_requirement" in policy
    assert "network_policies: {}" in policy
    assert "include_workdir: true" in policy

    dockerfile = (ROOT / "Dockerfile.verifier").read_text(encoding="utf-8")
    assert "useradd --create-home --uid 10001 verifier" in dockerfile
    assert "install -d -o verifier -g verifier /workspace" in dockerfile
    assert "USER verifier" in dockerfile


def test_conformance_workflow_pins_docker_driver_and_retains_diagnostics() -> None:
    workflow_path = ROOT / ".github/workflows/openshell-conformance.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    assert 'OPENSHELL_VERSION: "v0.0.52"' in workflow
    assert 'compute_drivers = ["docker"]' in workflow
    assert "OPENSHELL_DRIVERS=docker" in workflow
    assert "policy_validation_failure_mode" not in workflow
    assert "gateway-journal.txt" in workflow
    assert "xt-aegis-openshell-diagnostics.tar.gz" in workflow
