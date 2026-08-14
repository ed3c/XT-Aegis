"""Command-line interface."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xt_aegis.demo import run_demo
from xt_aegis.replay import ReplayError, format_timeline, replay_events
from xt_aegis.skill import SkillCompiler
from xt_aegis.verification import (
    VerificationError,
    doctor,
    pack_evidence,
    result_exit_code,
    verification_plan,
    verify_many,
)
from xt_aegis.verification_models import BackendName, VerificationStatus


def _timestamped_output_dir() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path(".xt-aegis") / "verification" / stamp


def _add_verification_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument(
        "--backend",
        choices=[backend.value for backend in BackendName],
        default=BackendName.AUTO.value,
    )
    parser.add_argument("--format", choices=["json", "text"], default="json")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xt-aegis", description="Deterministic safety and verification harness for agent actions"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo_parser = subparsers.add_parser("demo", help="run the transactional refactor demonstration")
    demo_parser.add_argument("--output-dir", type=Path, default=None)

    compile_parser = subparsers.add_parser("compile-skill", help="validate and print a SKILL contract")
    compile_parser.add_argument("path", type=Path)

    doctor_parser = subparsers.add_parser(
        "doctor", help="inspect verification prerequisites without executing repository code"
    )
    _add_verification_common(doctor_parser)

    verify_parser = subparsers.add_parser(
        "verify", help="run bounded claim recipes through an explicit verification backend"
    )
    _add_verification_common(verify_parser)
    selection = verify_parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--claim", action="append", dest="claims")
    selection.add_argument("--all", action="store_true")
    verify_parser.add_argument("--output-dir", type=Path, default=None)

    plan_parser = subparsers.add_parser("plan", help="show a verification recipe without running it")
    _add_verification_common(plan_parser)
    plan_parser.add_argument("--claim", required=True)

    evidence_parser = subparsers.add_parser("evidence", help="manage portable verification evidence")
    evidence_subparsers = evidence_parser.add_subparsers(dest="evidence_command", required=True)
    pack_parser = evidence_subparsers.add_parser("pack", help="create a deterministic evidence archive")
    pack_parser.add_argument("--input", type=Path, required=True)
    pack_parser.add_argument("--output", type=Path, required=True)
    pack_parser.add_argument("--format", choices=["json", "text"], default="json")

    replay_parser = subparsers.add_parser(
        "replay", help="reconstruct an execution timeline from a persisted JSONL trajectory"
    )
    replay_parser.add_argument("--events", type=Path, required=True)
    replay_parser.add_argument("--format", choices=["json", "text"], default="text")

    mcp_parser = subparsers.add_parser("mcp", help="start the MCP evidence and verification server")
    mcp_parser.add_argument("--registry", type=Path, default=None)
    mcp_parser.add_argument("--root", type=Path, default=None)
    mcp_parser.add_argument("--allow-execution", action="store_true")
    mcp_parser.add_argument(
        "--backend",
        choices=[backend.value for backend in BackendName],
        default=BackendName.AUTO.value,
    )
    mcp_parser.add_argument("--output-root", type=Path, default=Path(".xt-aegis/mcp-verification"))
    mcp_parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    mcp_parser.add_argument("--host", default="127.0.0.1")
    mcp_parser.add_argument("--port", type=int, default=8765)
    return parser


def _print(value: Any, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))
        return
    if isinstance(value, dict):
        for key, item in value.items():
            print(f"{key}: {item}")
    else:
        print(value)


def _mcp_argv(args: argparse.Namespace) -> list[str]:
    argv = [
        "--transport",
        args.transport,
        "--backend",
        args.backend,
        "--output-root",
        str(args.output_root),
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    if args.registry is not None:
        argv.extend(["--registry", str(args.registry)])
    if args.root is not None:
        argv.extend(["--root", str(args.root)])
    if args.allow_execution:
        argv.append("--allow-execution")
    return argv


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            demo_summary = run_demo(args.output_dir)
            print(json.dumps(demo_summary, indent=2, sort_keys=True))
            return 0
        if args.command == "compile-skill":
            compiled = SkillCompiler.compile(args.path)
            print(compiled.model_dump_json(indent=2))
            return 0
        if args.command == "doctor":
            report = doctor(
                registry_path=args.registry,
                root=args.root,
                requested_backend=BackendName(args.backend),
            )
            _print(report.model_dump(mode="json"), args.format)
            return 0 if report.selected_backend is not None else 10
        if args.command == "replay":
            timeline = replay_events(args.events)
            if args.format == "json":
                print(timeline.model_dump_json(indent=2))
            else:
                print(format_timeline(timeline))
            return 0
        if args.command == "plan":
            plan = verification_plan(
                claim_id=args.claim,
                backend_name=BackendName(args.backend),
                registry_path=args.registry,
                root=args.root,
            )
            _print(plan, args.format)
            return 0 if plan.get("executable") else 10
        if args.command == "verify":
            output_dir = args.output_dir or _timestamped_output_dir()
            verification_summary = verify_many(
                claim_ids=None if args.all else args.claims,
                backend_name=BackendName(args.backend),
                registry_path=args.registry,
                root=args.root,
                output_dir=output_dir,
            )
            payload = verification_summary.model_dump(mode="json")
            payload["output_dir"] = str(output_dir.resolve())
            _print(payload, args.format)
            return result_exit_code(verification_summary.overall_status)
        if args.command == "evidence" and args.evidence_command == "pack":
            result = pack_evidence(args.input, args.output)
            _print(result, args.format)
            return 0
        if args.command == "mcp":
            from xt_aegis.mcp_server import main as mcp_main

            mcp_main(_mcp_argv(args))
            return 0
    except KeyError as exc:
        _print({"status": VerificationStatus.ERROR.value, "error": f"unknown claim: {exc.args[0]}"}, "json")
        return 50
    except (OSError, ReplayError, VerificationError, ValueError) as exc:
        _print(
            {
                "status": VerificationStatus.ERROR.value,
                "error": f"{type(exc).__name__}: {exc}",
            },
            "json",
        )
        return 50
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
