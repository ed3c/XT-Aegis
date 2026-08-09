# Benchmarks

No committed result in this directory is authoritative until it satisfies `docs/BENCHMARKS.md`.

Run the local scaffold with:

```bash
python scripts/benchmark.py --repetitions 5 --output /tmp/xt-aegis-benchmark.json
```

The output is a development measurement, not a public performance claim. Do not commit machine-specific
results without the full environment, raw records, corpus, baseline, and review required by the benchmark
contract.
