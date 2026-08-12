# Scoped Instructions: `scripts`

Inherit the root contract.

- Use strict input validation and deterministic exit codes.
- Never embed credentials, private URLs, or unreviewed `eval`/shell expansion.
- Product execution commands remain typed and policy-controlled; repository scripts do not broaden them.
- Destructive Git or filesystem operations require ownership, clean-state, and recovery checks.
- Bash files pass `bash -n` and shell-analysis policy.
- Benchmark scripts preserve raw failures and exact environment metadata.
- Each script documents inputs, outputs, side effects, failure semantics, and evidence.
