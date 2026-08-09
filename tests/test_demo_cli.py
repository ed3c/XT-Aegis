from __future__ import annotations

import json
from pathlib import Path

from xt_aegis.cli import main
from xt_aegis.demo import run_demo
from xt_aegis.mcp_server import inspect_capabilities


def test_demo_runs_end_to_end(tmp_path: Path) -> None:
    summary = run_demo(tmp_path / "demo")
    statuses = [result["status"] for result in summary["results"]]  # type: ignore[index]
    assert statuses == ["rolled_back", "succeeded", "blocked"]
    assert summary["idempotent_replay"]["cached_replay"] is True  # type: ignore[index]
    assert Path(summary["checkpoint_database"]).is_file()  # type: ignore[arg-type]
    assert Path(summary["events_jsonl"]).is_file()  # type: ignore[arg-type]


def test_cli_compiles_skill(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    skill_path = tmp_path / "demo.SKILL.md"
    skill_path.write_text(
        """---
schema_version: "1.0"
name: cli_demo
description: Validate a safe command line skill contract for the CLI test.
allowed_executables: [python3]
allowed_write_paths: []
network_policy: deny
preconditions: []
postconditions: []
---
Documentation only.
""",
        encoding="utf-8",
    )
    assert main(["compile-skill", str(skill_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["contract"]["name"] == "cli_demo"


def test_mcp_capabilities_do_not_overclaim() -> None:
    capabilities = inspect_capabilities()
    assert capabilities["maturity"] == "MVP reference implementation"
    assert "kernel-grade sandbox isolation" in capabilities["not_claimed"]
