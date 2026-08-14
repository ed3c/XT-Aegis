from __future__ import annotations

import json
from pathlib import Path

import pytest

from xt_aegis import benchmark
from xt_aegis.benchmark import (
    CASE_NAMES,
    BenchmarkCase,
    BenchmarkReport,
    BenchmarkTrial,
    BenchmarkWorkload,
    TrialOutcome,
    format_report,
    run_benchmark,
    summarize,
    write_report,
)
from xt_aegis.cli import main

ROOT = Path(__file__).resolve().parents[1]


def _workload(**overrides: object) -> BenchmarkWorkload:
    values: dict[str, object] = {
        "files": 3,
        "file_bytes": 64,
        "warmup": 0,
        "trials": 2,
        "seed": 0,
        "timeout_seconds": 60.0,
    }
    values.update(overrides)
    return BenchmarkWorkload(**values)  # type: ignore[arg-type]


def test_report_contract_matches_checked_in_schema() -> None:
    checked_in = json.loads(
        (ROOT / "verification/schemas/benchmark-report.schema.json").read_text(encoding="utf-8")
    )
    assert checked_in.pop("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert checked_in.pop("$id") == "https://github.com/ed3c/XT-Aegis/benchmark-report.schema.json"
    assert checked_in == BenchmarkReport.model_json_schema()


def test_every_case_produces_raw_trials_and_a_summary() -> None:
    report = run_benchmark(workload=_workload())

    assert [summary.case for summary in report.summaries] == list(CASE_NAMES)
    assert len(report.trials) == len(CASE_NAMES) * 2
    assert all(trial.outcome == TrialOutcome.PASSED for trial in report.trials), [
        trial.error for trial in report.trials if trial.error
    ]
    assert report.environment.dependency_digest
    assert report.reproduction_command.startswith("xt-aegis benchmark")
    assert any("not a production performance claim" in item for item in report.limitations)


def test_warmup_repetitions_are_not_recorded() -> None:
    report = run_benchmark(workload=_workload(warmup=2, trials=1), case_names=["policy-evaluate"])

    assert [trial.index for trial in report.trials] == [1]


def test_unknown_case_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown benchmark case"):
        run_benchmark(workload=_workload(), case_names=["does-not-exist"])


def test_aggregation_is_deterministic_and_keeps_failures() -> None:
    case = BenchmarkCase("demo", "fixture", lambda _root, _workload: None)  # type: ignore[arg-type]
    trials = [
        BenchmarkTrial(case="demo", index=1, outcome=TrialOutcome.PASSED, duration_ms=10.0),
        BenchmarkTrial(case="demo", index=2, outcome=TrialOutcome.PASSED, duration_ms=30.0),
        BenchmarkTrial(case="demo", index=3, outcome=TrialOutcome.FAILED, duration_ms=1.0, error="boom"),
        BenchmarkTrial(case="demo", index=4, outcome=TrialOutcome.TIMED_OUT, duration_ms=99.0),
        BenchmarkTrial(case="other", index=1, outcome=TrialOutcome.PASSED, duration_ms=5.0),
    ]

    summary = summarize(case, trials)

    assert summarize(case, trials) == summary
    assert summarize(case, list(reversed(trials))) == summary
    assert (summary.trials, summary.passed, summary.failed, summary.timed_out) == (4, 2, 1, 1)
    assert summary.median_ms == 20.0
    assert (summary.min_ms, summary.max_ms) == (10.0, 30.0)
    assert summary.p95_ms == 30.0


def test_a_failing_case_is_retained_and_reported_without_latency() -> None:
    def exploding_factory(root: Path, workload: BenchmarkWorkload) -> benchmark._MeasuredOperation:
        del root, workload

        def run() -> None:
            raise RuntimeError("measured operation failed")

        return benchmark._MeasuredOperation(run=run)

    case = BenchmarkCase("failing", "always fails", exploding_factory)
    report_trials = benchmark._run_case(case, Path.cwd(), _workload())
    summary = summarize(case, report_trials)

    assert [trial.outcome for trial in report_trials] == [TrialOutcome.FAILED, TrialOutcome.FAILED]
    assert all("measured operation failed" in trial.error for trial in report_trials)
    assert (summary.passed, summary.failed) == (0, 2)
    assert summary.median_ms is None


def test_observed_deadline_marks_a_trial_timed_out_and_stops_the_case(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ticks = iter([0.0, 5.0, 5.0, 10.0])
    monkeypatch.setattr(benchmark.time, "perf_counter", lambda: next(ticks))
    case = BenchmarkCase(
        "slow", "sleeps past the deadline", lambda _r, _w: benchmark._MeasuredOperation(run=lambda: None)
    )

    trials = benchmark._run_case(case, tmp_path, _workload(trials=2, timeout_seconds=1.0))

    assert [trial.outcome for trial in trials] == [TrialOutcome.TIMED_OUT]
    assert "deadline" in trials[0].error


def test_written_artifact_round_trips_and_validates(tmp_path: Path) -> None:
    report = run_benchmark(workload=_workload(trials=1), case_names=["tree-hash"])

    path = write_report(report, tmp_path / "out")

    assert path.name == "benchmark-report.json"
    assert BenchmarkReport.model_validate_json(path.read_text(encoding="utf-8")) == report


def test_text_report_shows_failure_counts_next_to_latency() -> None:
    rendered = format_report(run_benchmark(workload=_workload(trials=1), case_names=["policy-evaluate"]))

    assert "policy-evaluate" in rendered
    assert "fail" in rendered
    assert "reproduce: xt-aegis benchmark" in rendered


def test_cli_benchmark_writes_an_artifact_and_succeeds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "benchmark",
            "--case",
            "tree-hash",
            "--files",
            "2",
            "--file-bytes",
            "32",
            "--warmup",
            "0",
            "--trials",
            "1",
            "--output-dir",
            str(tmp_path / "artifact"),
            "--format",
            "json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summaries"][0]["case"] == "tree-hash"
    assert (tmp_path / "artifact" / "benchmark-report.json").is_file()
