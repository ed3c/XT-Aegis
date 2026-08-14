# Observability and Trajectory Replay

## What is emitted

XT-Aegis emits a fixed span vocabulary. A name outside this set is a contract error, not a free-form label.

| Span | Opened by |
|---|---|
| `run` | one `HarnessRunner.execute` call, parent of everything below |
| `policy.evaluate` | request and condition policy validation |
| `approval.wait` | the approval claim for a high-risk request |
| `action.execute` | the mutating action itself |
| `assertion.check` | one declared precondition or postcondition |
| `workspace.rollback` | the single rollback exit shared by every failure path |
| `checkpoint.persist` | terminal result persistence |

A span carries a status of `ok` or `error`. `error` means the observed step did not pass; it does not mean
the run was incorrect. A policy-denied run is a correct outcome, so its `run` span stays `ok` while its
`policy.evaluate` span is `error`.

## Default: telemetry is off

`HarnessRunner` uses `NullTelemetry` unless a recorder is passed explicitly. Nothing is buffered, written,
or exported by default. Passing `InMemoryTelemetry()` keeps spans in the process for tests and offline
review. Export requires the user to opt in, and export failure never changes authorization or execution
results — the span is recorded after the measured work has already completed.

## Attribute allowlist

Only reviewed keys may leave the process. An unreviewed key is **dropped**, not truncated, because an
unreviewed key is exactly how prompts, file paths, and credentials escape into a telemetry pipeline. The
allowlist lives in `xt_aegis.telemetry.ATTRIBUTE_ALLOWLIST`, and every dropped key name is recorded in
`dropped_attributes` so a reviewer can see that something was withheld.

Values are redacted with the shared redaction pass and then bounded to 256 characters; keys are bounded to
64. Command argv, stdout, stderr, file contents, actor identity, and model prompts are not allowlisted and
therefore never appear in a span.

## Optional OpenTelemetry export

The OpenTelemetry API, SDK, and OTLP exporter are optional extras:

```bash
pip install "xt-aegis[otel]"
```

`OpenTelemetryBridge` forwards spans to whatever tracer provider the host application configured. XT-Aegis
owns no exporter, endpoint, or credential. For a local collector:

```python
from xt_aegis.telemetry import OpenTelemetryBridge, otlp_exporter

with otlp_exporter("http://127.0.0.1:4318/v1/traces"):
    runner = HarnessRunner(..., telemetry=OpenTelemetryBridge())
```

The endpoint is a network destination chosen by the user. Repository text and model output cannot select
it, and no endpoint is contacted unless `otlp_exporter` is called explicitly.

## Event envelope and compatibility

Each JSONL trajectory record carries `schema_version`. The major component is the compatibility boundary: a
reader accepts a record whose major matches and whose minor is less than or equal to its own, and fails
closed otherwise. Adding an optional payload key is a minor change; removing or retyping one is a major
change. A record without `schema_version` is refused rather than guessed.

## Replay

```bash
xt-aegis replay --events .xt-aegis/state/events.jsonl
xt-aegis replay --events .xt-aegis/state/events.jsonl --format json
```

Replay reads persisted events only. It invokes no model, runs no tool, and touches no workspace. Each event
is projected onto the span vocabulary through `xt_aegis.replay.EVENT_SPAN_MAP`, which is the deterministic
mapping between what was persisted and what was traced, so a trajectory recorded without an exporter can
still be read as a trace afterwards. Payload keys outside the attribute allowlist are not shown.

An event type with no mapping is reported in `unmapped_event_types` instead of being silently skipped.

## What this does not prove

A trace is not evidence of semantic correctness. Assertions, tests, and the evidence registry remain the
source of truth. Span timings come from one process on one host and are not a performance claim; see
[`BENCHMARKS.md`](BENCHMARKS.md).
