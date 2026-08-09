"""Reproducible bad-patch, rollback, good-patch, and injection-boundary demo."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib.resources import as_file, files
from pathlib import Path

from xt_aegis.checkpoint import CheckpointStore
from xt_aegis.evaluator import evaluate_trajectory
from xt_aegis.events import EventRecorder
from xt_aegis.models import ActionRequest, FileWriteAction, Provenance
from xt_aegis.runner import HarnessRunner
from xt_aegis.skill import SkillCompiler
from xt_aegis.workspace import IsolatedWorkspace

_BAD_CODE = '''"""Intentionally incorrect patch used to prove rollback."""


def calculate_tax(amount: float) -> float:
    return round(amount * 0.10, 2)
'''

_GOOD_CODE = '''"""Refactored implementation that preserves tested behavior."""

TAX_RATE = 0.05


def calculate_tax(amount: float) -> float:
    if amount < 0:
        raise ValueError("Amount cannot be negative")
    return round(amount * TAX_RATE, 2)
'''

_INJECTION_MARKER = """# External content attempted to replace trusted code.
# A secure control plane must block this before any write occurs.
"""


def run_demo(output_directory: str | Path | None = None) -> dict[str, object]:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_root = Path(output_directory or Path(".xt-aegis") / "runs" / timestamp).resolve()

    package_root = files("xt_aegis") / "demo_assets"
    with as_file(package_root) as assets:
        workspace = IsolatedWorkspace.from_template(assets / "template", run_root=run_root)
        skill = SkillCompiler.compile(assets / "refactor.SKILL.md")

    state_directory = run_root / "state"
    store = CheckpointStore(state_directory / "checkpoints.db")
    recorder = EventRecorder(store, state_directory / "events.jsonl")
    runner = HarnessRunner(
        skill=skill,
        workspace=workspace,
        checkpoint_store=store,
        event_recorder=recorder,
    )

    thread_id = "demo.refactor.001"
    bad_result = runner.execute(
        ActionRequest(
            thread_id=thread_id,
            action_id="write.bad.patch",
            idempotency_key="demo-refactor-bad-0001",
            provenance=Provenance.AGENT_PROPOSAL,
            action=FileWriteAction(relative_path="sample_project/app.py", content=_BAD_CODE),
        )
    )
    good_request = ActionRequest(
        thread_id=thread_id,
        action_id="write.good.patch",
        idempotency_key="demo-refactor-good-0001",
        provenance=Provenance.AGENT_PROPOSAL,
        action=FileWriteAction(relative_path="sample_project/app.py", content=_GOOD_CODE),
    )
    good_result = runner.execute(good_request)
    cached_result = runner.execute(good_request)
    injection_result = runner.execute(
        ActionRequest(
            thread_id=thread_id,
            action_id="external.prompt.injection",
            idempotency_key="demo-injection-block-0001",
            provenance=Provenance.EXTERNAL_CONTENT,
            action=FileWriteAction(relative_path="sample_project/app.py", content=_INJECTION_MARKER),
        )
    )

    results = [bad_result, good_result, injection_result]
    score = evaluate_trajectory(results)
    summary: dict[str, object] = {
        "run_root": str(run_root),
        "workspace": str(workspace.root),
        "checkpoint_database": str(store.database_path),
        "events_jsonl": str((state_directory / "events.jsonl").resolve()),
        "results": [result.model_dump(mode="json") for result in results],
        "idempotent_replay": cached_result.model_dump(mode="json"),
        "trajectory_score": score.model_dump(mode="json"),
        "resume_position": store.get_resume_position(thread_id),
    }
    (run_root / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary
