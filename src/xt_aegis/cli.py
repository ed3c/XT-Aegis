"""Command-line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from xt_aegis.demo import run_demo
from xt_aegis.skill import SkillCompiler


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xt-aegis", description="Deterministic safety harness for agent actions"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo_parser = subparsers.add_parser("demo", help="run the transactional refactor demonstration")
    demo_parser.add_argument("--output-dir", type=Path, default=None)

    compile_parser = subparsers.add_parser("compile-skill", help="validate and print a SKILL contract")
    compile_parser.add_argument("path", type=Path)

    subparsers.add_parser("mcp", help="start the optional read-only MCP evidence server")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "demo":
        summary = run_demo(args.output_dir)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    if args.command == "compile-skill":
        compiled = SkillCompiler.compile(args.path)
        print(compiled.model_dump_json(indent=2))
        return 0
    if args.command == "mcp":
        from xt_aegis.mcp_server import main as mcp_main

        mcp_main()
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
