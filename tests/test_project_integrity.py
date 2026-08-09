from __future__ import annotations

import json
from pathlib import Path

from xt_aegis.verification import load_registry

ROOT = Path(__file__).resolve().parents[1]


def test_distribution_metadata_and_ownership_markers_match() -> None:
    manifest = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    server_name = manifest["name"]
    assert manifest["version"] == "0.2.0"
    assert {package["registryType"] for package in manifest["packages"]} == {"pypi", "oci"}
    assert all(package["transport"]["type"] == "stdio" for package in manifest["packages"])
    assert f"mcp-name: {server_name}" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert (
        f'io.modelcontextprotocol.server.name="{server_name}"'
        in (ROOT / "Dockerfile.verifier").read_text(encoding="utf-8")
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


def test_public_project_files_use_user_neutral_terminology() -> None:
    forbidden = (
        "inter" + "view",
        "inter" + "viewer",
        "hir" + "ing",
        "rés" + "umé",
        "resume " + "screening",
        "candidate " + "selection",
        "面" + "試",
        "履" + "歷",
        "候選" + "人",
    )
    suffixes = {".md", ".json", ".toml", ".yml", ".yaml", ".py"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in suffixes or path.name.startswith("chunk"):
            continue
        if any(part in {".git", ".venv", ".pytest_cache", "__pycache__"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8").casefold()
        for term in forbidden:
            assert term.casefold() not in text, f"{term!r} found in {path.relative_to(ROOT)}"
