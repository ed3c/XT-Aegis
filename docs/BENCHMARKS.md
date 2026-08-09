# Benchmark Contract

## Current status

XT-Aegis does **not** publish a numeric rollback-latency, reliability, accuracy, or token-savings claim in
version 0.1.0. The source design brief contained target-style numbers, but they are not carried into the
project as facts without reproducible evidence.

## Required benchmark metadata

Every published result must include:

- commit SHA and clean/dirty repository state;
- operating system, CPU, memory, filesystem, Python version, and dependency lock;
- task corpus and license;
- warm-up policy and number of repetitions;
- median, p90, p95, minimum, maximum, and dispersion;
- raw per-run JSON records;
- failure count and exclusion rationale;
- baseline implementation and configuration;
- whether caches were cold or warm;
- whether a model, network, or external service was involved;
- exact command used to reproduce the run.

## Planned benchmark families

### B1. Rollback integrity and latency

Measure workspace sizes from 10 files to 100,000 files. Inject deterministic failures after write,
rename, delete, and partial command execution. Record restore latency and verify full-tree hash equality.

The benchmark must compare:

- snapshot copy backend;
- Git worktree backend;
- copy-on-write container/filesystem backend.

### B2. Checkpoint overhead and recovery

Measure action throughput and latency with SQLite WAL. Kill the process at each state transition and
verify restart behavior. Later compare PostgreSQL and distributed lease backends.

### B3. Prompt-injection containment

Use a versioned corpus covering malicious instructions in:

- issue text;
- source comments and README files;
- web pages;
- tool output;
- retrieved memory;
- skill Markdown bodies;
- nested encodings and multilingual text.

Metrics should report policy bypasses, false blocks, and unsupported provenance transitions.

### B4. Agent task outcome and trajectory

Run the same task/model combination with and without XT-Aegis controls. Report:

- final test pass rate;
- destructive side effects escaped;
- successful rollback rate;
- attempts per successful task;
- elapsed time and model tokens;
- human approvals requested and accepted;
- policy false positives.

A model's final answer alone is not sufficient; raw trajectories are required.

### B5. Context and token optimization

OpenWiki/static-cache or AST-pruning claims belong in a separate adapter. Measure a real corpus against a
specified runtime retrieval baseline. Do not derive a percentage from one example or prompt length alone.

## Publishing rules

A result may enter README only when:

1. the benchmark runner and raw data are committed or attached to a release;
2. CI can validate schema and aggregate calculations;
3. the environment is documented;
4. limitations and negative results are included;
5. `PROJECT_EVIDENCE.json` links the artifact;
6. no benchmark instruction asks an LLM judge to produce a preferred conclusion.
