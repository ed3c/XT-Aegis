from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from xt_aegis.cli import main
from xt_aegis.sbom import CYCLONEDX_SPEC_VERSION, build_sbom, render_sbom, write_sbom


def test_the_document_is_cyclonedx_with_the_project_as_its_metadata_component() -> None:
    document = build_sbom()

    assert document["bomFormat"] == "CycloneDX"
    assert document["specVersion"] == CYCLONEDX_SPEC_VERSION
    assert document["version"] == 1
    component = document["metadata"]["component"]
    assert component["name"] == "xt-aegis"
    assert component["type"] == "application"
    assert component["purl"].startswith("pkg:pypi/xt-aegis@")


def test_dependencies_appear_with_names_versions_and_purls() -> None:
    components = build_sbom()["components"]

    by_name = {component["name"].lower(): component for component in components}
    assert "pydantic" in by_name
    pydantic = by_name["pydantic"]
    assert pydantic["type"] == "library"
    assert pydantic["version"]
    assert pydantic["purl"] == f"pkg:pypi/pydantic@{pydantic['version']}"
    assert all("purl" in component for component in components)


def test_the_project_is_not_listed_twice() -> None:
    document = build_sbom()

    names = [component["name"].lower() for component in document["components"]]
    assert "xt-aegis" not in names


def test_components_are_sorted_and_output_is_byte_identical_across_runs() -> None:
    first = render_sbom(build_sbom())
    second = render_sbom(build_sbom())

    assert first == second
    components = json.loads(first)["components"]
    normalized = [component["name"].lower().replace("_", "-").replace(".", "-") for component in components]
    assert normalized == sorted(normalized)


def test_the_rendered_document_carries_no_timestamp() -> None:
    """A document that changes every run cannot be compared between builds."""

    rendered = render_sbom(build_sbom()).lower()

    assert "timestamp" not in rendered


def test_the_module_itself_imports_only_the_standard_library() -> None:
    """Producing an inventory of dependencies must not itself require one.

    The module is loaded straight from its file, bypassing the package __init__, because importing
    `xt_aegis` pulls in every module and would hide whether this one is self-contained.
    """

    script = (
        "import importlib.util, pathlib, sys;"
        "path = pathlib.Path(sys.argv[1]);"
        "spec = importlib.util.spec_from_file_location('sbom_only', path);"
        "module = importlib.util.module_from_spec(spec);"
        "sys.modules['pydantic'] = None;"
        "spec.loader.exec_module(module);"
        "print(len(module.build_sbom()['components']))"
    )
    module_path = Path(__file__).resolve().parents[1] / "src" / "xt_aegis" / "sbom.py"
    completed = subprocess.run(
        [sys.executable, "-c", script, str(module_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
    assert int(completed.stdout.strip()) > 0


def test_an_absent_project_distribution_is_reported(tmp_path: Path) -> None:
    with pytest.raises(LookupError, match="not installed"):
        build_sbom(project="definitely-not-installed")


def test_write_sbom_creates_the_parent_directory(tmp_path: Path) -> None:
    path = write_sbom(tmp_path / "nested" / "sbom.json")

    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["bomFormat"] == "CycloneDX"


def test_the_cli_writes_a_file_and_reports_a_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["sbom", "--output", str(tmp_path / "sbom.json"), "--format", "json"])

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["project"] == "xt-aegis"
    assert summary["spec_version"] == CYCLONEDX_SPEC_VERSION
    assert summary["components"] > 0
    assert (tmp_path / "sbom.json").is_file()
