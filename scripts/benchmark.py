"""Local measurement scaffold; does not publish benchmark claims."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

from xt_aegis.demo import run_demo


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("benchmark-results.json"))
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")

    durations: list[float] = []
    records: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="xt-aegis-benchmark-") as temporary_directory:
        root = Path(temporary_directory)
        for index in range(args.repetitions):
            started = time.perf_counter()
            summary = run_demo(root / f"run-{index:03d}")
            duration_ms = (time.perf_counter() - started) * 1000
            durations.append(duration_ms)
            records.append(
                {
                    "index": index,
                    "duration_ms": duration_ms,
                    "trajectory_score": summary["trajectory_score"],
                }
            )

    payload = {
        "warning": "Local development measurement only; not a published performance claim.",
        "environment": {
            "platform": platform.platform(),
            "python": sys.version,
            "processor": platform.processor(),
        },
        "repetitions": args.repetitions,
        "aggregate": {
            "minimum_ms": min(durations),
            "median_ms": statistics.median(durations),
            "maximum_ms": max(durations),
        },
        "records": records,
    }
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
