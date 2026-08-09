from __future__ import annotations

from pathlib import Path

import pytest

from xt_aegis.checkpoint import CheckpointStore
from xt_aegis.events import EventRecorder
from xt_aegis.models import CommandSpec, CompiledSkill, NetworkPolicy, RiskLevel, SkillContract
from xt_aegis.runner import HarnessRunner
from xt_aegis.workspace import IsolatedWorkspace


@pytest.fixture
def template_dir(tmp_path: Path) -> Path:
    template = tmp_path / "template"
    sample = template / "sample_project"
    sample.mkdir(parents=True)
    (sample / "app.py").write_text(
        "def calculate_tax(amount: float) -> float:\n"
        "    if amount < 0:\n"
        "        raise ValueError('Amount cannot be negative')\n"
        "    return round(amount * 0.05, 2)\n",
        encoding="utf-8",
    )
    (sample / "test_app.py").write_text(
        "import unittest\n"
        "from app import calculate_tax\n\n"
        "class T(unittest.TestCase):\n"
        "    def test_tax(self):\n"
        "        self.assertEqual(calculate_tax(100.0), 5.0)\n"
        "        with self.assertRaises(ValueError):\n"
        "            calculate_tax(-1.0)\n",
        encoding="utf-8",
    )
    return template


@pytest.fixture
def compiled_skill() -> CompiledSkill:
    condition = CommandSpec(
        description="tests pass",
        argv=["python3", "-m", "unittest", "discover", "-s", "sample_project", "-p", "test_*.py", "-q"],
    )
    contract = SkillContract(
        schema_version="1.0",
        name="safe_refactor",
        description="Safely update the sample project and preserve all unit tests.",
        allowed_executables={"python3"},
        allowed_write_paths=["sample_project/app.py"],
        network_policy=NetworkPolicy.DENY,
        risk_level=RiskLevel.MEDIUM,
        preconditions=[condition],
        postconditions=[condition],
    )
    return CompiledSkill(
        contract=contract,
        markdown_body="human documentation only",
        source_path="test.SKILL.md",
        source_sha256="a" * 64,
    )


@pytest.fixture
def runner(tmp_path: Path, template_dir: Path, compiled_skill: CompiledSkill) -> HarnessRunner:
    workspace = IsolatedWorkspace.from_template(template_dir, run_root=tmp_path / "run")
    store = CheckpointStore(tmp_path / "state" / "checkpoints.db")
    events = EventRecorder(store, tmp_path / "state" / "events.jsonl")
    return HarnessRunner(
        skill=compiled_skill,
        workspace=workspace,
        checkpoint_store=store,
        event_recorder=events,
    )
