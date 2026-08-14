"""Deterministic CycloneDX SBOM built from the installed distribution metadata.

Only the standard library is used. Adding a dependency in order to describe dependencies would be its own
small joke, and it would also mean the SBOM could not be produced from a minimal install.

The output carries no wall-clock timestamp and sorts its components, so two runs in the same environment
produce byte-identical bytes. That matters more than it looks: an artifact that changes every run cannot be
compared between builds, and an SBOM that cannot be compared is decoration.
"""

from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path
from typing import Any

CYCLONEDX_SPEC_VERSION = "1.5"
_PROJECT_DISTRIBUTION = "xt-aegis"


def _normalize(name: str) -> str:
    """PEP 503 normalization, which is also what a package URL expects."""

    return "-".join(part for part in name.lower().replace("_", "-").replace(".", "-").split("-") if part)


def _metadata_value(distribution: metadata.Distribution, key: str) -> str:
    """Read one metadata field, tolerating absence across importlib.metadata versions."""

    try:
        value = distribution.metadata[key]
    except KeyError:
        return ""
    return str(value) if value else ""


def _purl(name: str, version: str) -> str:
    return f"pkg:pypi/{_normalize(name)}@{version}"


def _license_entries(distribution: metadata.Distribution) -> list[dict[str, Any]]:
    # `PackageMetadata` is mapping-like across versions but only exposes `__getitem__` in its typed
    # interface, so the lookups go through a helper rather than `.get`.
    declared = _metadata_value(distribution, "License-Expression") or _metadata_value(
        distribution, "License"
    )
    if not declared or declared.lower() in {"unknown", "none"}:
        classifiers = [
            str(value).split("::")[-1].strip()
            for value in (distribution.metadata.get_all("Classifier") or [])
            if str(value).startswith("License ::")
        ]
        declared = classifiers[0] if classifiers else ""
    if not declared:
        return []
    return [{"license": {"name": declared[:128]}}]


def _component(distribution: metadata.Distribution) -> dict[str, Any]:
    name = _metadata_value(distribution, "Name")
    version = distribution.version or "0"
    component: dict[str, Any] = {
        "type": "library",
        "name": name,
        "version": version,
        "purl": _purl(name, version),
        "bom-ref": _purl(name, version),
    }
    licenses = _license_entries(distribution)
    if licenses:
        component["licenses"] = licenses
    return component


def build_sbom(*, project: str = _PROJECT_DISTRIBUTION) -> dict[str, Any]:
    """Return a CycloneDX document describing the environment this process is running in."""

    installed: dict[str, metadata.Distribution] = {}
    for distribution in metadata.distributions():
        name = _metadata_value(distribution, "Name")
        if not name:
            continue
        installed.setdefault(_normalize(name), distribution)

    project_distribution = installed.get(_normalize(project))
    if project_distribution is None:
        raise LookupError(f"distribution {project!r} is not installed in this environment")

    components = [
        _component(distribution)
        for key, distribution in sorted(installed.items())
        if key != _normalize(project)
    ]
    project_version = project_distribution.version or "0"
    return {
        "bomFormat": "CycloneDX",
        "specVersion": CYCLONEDX_SPEC_VERSION,
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": _metadata_value(project_distribution, "Name"),
                "version": project_version,
                "purl": _purl(project, project_version),
                "bom-ref": _purl(project, project_version),
                "licenses": _license_entries(project_distribution),
            }
        },
        "components": components,
    }


def render_sbom(document: dict[str, Any]) -> str:
    """Serialize deterministically: sorted keys, fixed separators, trailing newline."""

    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def write_sbom(destination: str | Path, *, project: str = _PROJECT_DISTRIBUTION) -> Path:
    """Write the SBOM and return its path."""

    path = Path(destination).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_sbom(build_sbom(project=project)), encoding="utf-8")
    return path
