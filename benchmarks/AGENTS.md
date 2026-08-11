# Scoped Instructions: `benchmarks`

Inherit the root contract.

- Preserve raw failed, timed-out, unsupported, and inconclusive trials.
- Do not select favorable runs or compare different task/model conditions as equivalent.
- Separate correctness, safety, cost, latency, retry count, and mutation persistence.
- Redact private prompts, credentials, and source.
- Do not promote a universal claim from one machine or model profile.
- Benchmark implementation or result changes require issue #11 or a linked successor and explicit evals.
