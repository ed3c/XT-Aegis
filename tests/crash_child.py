"""Child process used by the fault-injection tests: build a runner, then die at one named transition.

Run as ``python tests/crash_child.py <run_root> <transition|none> <action_id> <idempotency_key>``.
Exit codes: 0 the run completed, 9 the process was killed at the requested transition, 2 setup failed.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xt_aegis.checkpoint import CheckpointStore
from xt_aegis.events import EventRecorder
from xt_aegis.lifecycle import Transition
from xt_aegis.models import (
    ActionRequest,
    CommandSpec,
    CompiledSkill,
    FileWriteAction,
    NetworkPolicy,
    Provenance,
    RiskLevel,
    SkillContract,
)
from xt_aegis.runner import HarnessRunner
from xt_aegis.workspace import IsolatedWorkspace

GOOD_CODE = "VALUE = 2\n"
CRASH_EXIT_CODE = 9


def _contract() -> SkillContract:
    condition = CommandSpec(description="workspace check", argv=["python3", "check.py"])
    return SkillContract(
        schema_version="1.0",
        name="crash_recovery_fixture",
        description="Deterministic fixture used by the crash-recovery fault injection tests.",
        allowed_executables={"python3"},
        allowed_write_paths=["app.py"],
        network_policy=NetworkPolicy.DENY,
        risk_level=RiskLevel.LOW,
        preconditions=[condition],
        postconditions=[condition],
    )


def _skill() -> CompiledSkill:
    return CompiledSkill(
        contract=_contract(),
        markdown_body="fixture",
        source_path="crash.SKILL.md",
        source_sha256="c" * 64,
    )


def build_runner(run_root: Path, crash_at: str | None) -> HarnessRunner:
    workspace = IsolatedWorkspace(
        root=run_root / "workspace" / "workspace",
        run_root=run_root / "workspace",
        ownership_token=(run_root / "ownership.txt").read_text(encoding="utf-8"),
    )
    store = CheckpointStore(run_root / "state" / "checkpoints.db")
    events = EventRecorder(store, run_root / "state" / "events.jsonl")

    def fault_hook(transition: Transition) -> None:
        if crash_at is not None and transition.value == crash_at:
            (run_root / "crashed_at.txt").write_text(transition.value, encoding="utf-8")
            os._exit(CRASH_EXIT_CODE)

    return HarnessRunner(
        skill=_skill(),
        workspace=workspace,
        checkpoint_store=store,
        event_recorder=events,
        fault_hook=fault_hook if crash_at is not None else None,
    )


def main() -> int:
    run_root = Path(sys.argv[1]).resolve()
    crash_at = None if sys.argv[2] == "none" else sys.argv[2]
    runner = build_runner(run_root, crash_at)
    request = ActionRequest(
        thread_id="thread.crash.001",
        action_id=sys.argv[3],
        idempotency_key=sys.argv[4],
        actor_id="user:test",
        provenance=Provenance.AGENT_PROPOSAL,
        action=FileWriteAction(relative_path="app.py", content=GOOD_CODE),
    )
    result = runner.execute(request, timeout_seconds=30.0)
    (run_root / "result.json").write_text(result.model_dump_json(), encoding="utf-8")
    print(json.dumps({"status": result.status.value, "step_number": result.step_number}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
