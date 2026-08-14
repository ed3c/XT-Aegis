# Benchmark Contract

## Current status

XT-Aegis does **not** publish a numeric rollback-latency, reliability, accuracy, or token-savings claim in
version 0.2.0. Target-style numbers from the source brief are not project facts without reproducible raw
evidence.

## Deterministic runtime harness

`xt-aegis benchmark` (issue #11) measures the deterministic runtime cases only. It does not run a model.

```bash
xt-aegis benchmark --files 32 --file-bytes 4096 --warmup 1 --trials 5 \
  --output-dir benchmarks/<profile> --format text
```

| Case | Measured operation |
|---|---|
| `tree-hash` | full workspace tree hash |
| `snapshot` | snapshot creation and commit |
| `rollback` | snapshot rollback with before/after hash equality |
| `checkpoint-write` | SQLite WAL event append plus JSONL persistence |
| `policy-evaluate` | policy validation of one file-write request |

Every repetition is written to `trials[]` with `passed`, `failed`, or `timed_out`. Failed and timed-out
trials are excluded from the latency distribution and never from the counts, so a case cannot be improved
by discarding its worst runs. `summaries[]` is a derived view; the raw trials remain the evidence.

The declared deadline is observed after each repetition and does not interrupt an in-process call.
Subprocess-level cancellation and deadline enforcement belong to issue #10.

CI runs a small smoke benchmark that asserts only that the harness produces a schema-valid artifact with no
failed case. It enforces no wall-clock threshold, because a shared runner cannot support one.

## Required metadata

Every published result must include:

- commit SHA and clean/dirty source state;
- registry, recipe, backend policy, package, and image digests;
- operating system, runtime version, CPU, memory, filesystem, Python, and dependencies;
- task corpus and license;
- warm-up policy and repetition count;
- median, p90, p95, p99, minimum, maximum, and dispersion;
- raw per-run JSON records;
- failures, timeouts, exclusions, and rationale;
- baseline implementation and configuration;
- cold/warm cache state;
- model, network, or external-service dependencies;
- exact reproduction command.

## Planned benchmark families

### B1. Rollback integrity and latency

Measure multiple workspace sizes and deterministic failures after write, rename, delete, and partial
process execution. Record restore latency and full-tree hash equality across snapshot, Git worktree, and
copy-on-write backends.

### B2. Checkpoint overhead and recovery

Measure SQLite WAL overhead. Kill the process at each persisted transition and verify restart behavior.
Later compare PostgreSQL and distributed lease backends.

### B3. Prompt-injection containment

Use a versioned multilingual corpus across issues, source comments, web pages, tool output, memory,
skill bodies, MCP metadata, and evidence registries. Report bypasses, false blocks, and unsupported taint
transitions.

### B4. Task outcome and trajectory

Run the same task and model with and without XT-Aegis controls. Report final test pass rate, escaped side
effects, rollback success, attempts, elapsed time, tokens, user approvals, policy false positives, and raw
trajectories.

### B5. Verification runtime conformance

Run the same malicious repository corpus through OpenShell, rootless Podman, and Docker. Test host-secret
canaries, path escape, denied egress, process/memory/disk exhaustion, output bounds, timeout, cleanup, and
policy digest retention.

### B6. Context and token optimization

Static-cache or AST-pruning claims belong in a separate adapter. Measure a real corpus against a specified
retrieval baseline. Do not derive a percentage from one prompt or example.

## Publishing rules

A result may enter README only when:

1. the runner and raw data are committed or attached to a release;
2. schemas and calculations are CI-validated;
3. environment and runtime identities are documented;
4. limitations and negative results are included;
5. `PROJECT_EVIDENCE.json` links the artifact;
6. the evidence bundle is bound to source, recipe, and policy digests;
7. no model-generated evaluator is prompted toward a preferred conclusion.
