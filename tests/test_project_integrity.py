from __future__ import annotations

import json
from pathlib import Path

from xt_aegis.verification import load_registry

ROOT = Path(__file__).resolve().parents[1]


def test_packaged_registry_matches_root_source_of_truth() -> None:
    assert (ROOT / "src/xt_aegis/verification_assets/PROJECT_EVIDENCE.json").read_bytes() == (
        ROOT / "PROJECT_EVIDENCE.json"
    ).read_bytes()


def test_distribution_metadata_and_ownership_markers_match() -> None:
    manifest = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    server_name = manifest["name"]
    assert manifest["version"] == "0.2.0"
    assert {package["registryType"] for package in manifest["packages"]} == {"pypi", "oci"}
    assert all(package["transport"]["type"] == "stdio" for package in manifest["packages"])
    assert f"mcp-name: {server_name}" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert f'io.modelcontextprotocol.server.name="{server_name}"' in (ROOT / "Dockerfile.verifier").read_text(
        encoding="utf-8"
    )


def test_checked_in_recipe_files_match_the_registry() -> None:
    loaded = load_registry(root=ROOT)
    for claim in loaded.registry.claims:
        if claim.verification is None:
            continue
        recipe_path = ROOT / "verification" / "recipes" / f"{claim.id}.json"
        assert recipe_path.is_file(), claim.id
        checked_in = json.loads(recipe_path.read_text(encoding="utf-8"))
        assert checked_in == {
            "schema_version": "1.0",
            "claim_id": claim.id,
            "declared_status": claim.status.value,
            "recipe": claim.verification.model_dump(mode="json"),
            "expected": claim.expected.model_dump(mode="json") if claim.expected is not None else None,
        }


def test_the_release_workflow_builds_its_sbom_from_the_installed_wheel() -> None:
    """The builder environment carries the dev extras; the wheel's does not.

    Generating the SBOM in the builder would describe software nobody installs — locally that is 52
    components against the 7 a clean wheel install produces. This pins the property, not the wording.
    """

    import yaml

    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["pypi"]
    runs = " ".join(step.get("run", "") for step in job["steps"])
    uses = [step.get("uses", "") for step in job["steps"]]

    assert "pip install dist/*.whl" in runs, "the SBOM must come from the built wheel, not the builder"
    assert "bin/xt-aegis" in runs and "sbom --output" in runs
    assert any(action.startswith("actions/attest-sbom@") for action in uses)
    assert job["permissions"]["attestations"] == "write"
    assert job["permissions"]["contents"] == "write", "uploading the SBOM to the release needs this"


def test_public_documentation_uses_user_facing_entry_points() -> None:
    expected = {
        ROOT / "docs" / "USER_DEMO.md",
        ROOT / "docs" / "USER_VERIFICATION_GUIDE.md",
        ROOT / "docs" / "EXTERNAL_VERIFICATION.md",
        ROOT / "docs" / "OPENSHELL.md",
        ROOT / "docs" / "adr" / "0002-user-policy-integrity.md",
    }
    assert all(path.is_file() for path in expected)
