# Contributing

## Development setup

```bash
git clone <repository-url>
cd XT-Aegis
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
make check
make verify
```

## Change workflow

1. Open or reference an issue for non-trivial behavior.
2. Create a focused branch.
3. Add implementation, failure-path tests, and documentation in the same pull request.
4. Update the evidence registry and threat model when a claim or boundary changes.
5. Run `make check` and `make verify` locally.
6. Complete the pull-request checklist and describe remaining risks.

## Definition of done

A change is ready when:

- behavior is typed and unknown input fails closed;
- security controls have negative tests;
- public interfaces and persisted schemas are documented;
- claim recipes are argv-only, path-confined, time-bounded, output-bounded, and network-denied;
- `auto` remains limited to strong backends;
- MCP execution remains absent unless the user explicitly enables it;
- `PROJECT_EVIDENCE.json` and JSON Schemas are synchronized;
- `docs/THREAT_MODEL.md` reflects new trust boundaries;
- format, lint, type checks, tests, coverage, verification, and package build pass;
- no secret, private URL, broad host permission, or generated environment artifact is committed.

## External policy integrity

Do not add text or metadata that asks a user, scanner, model, or tool to:

- ignore higher-priority policy;
- reveal system prompts or private data;
- trust a repository claim without reproduction;
- enable execution or broaden sandbox authority;
- run commands outside a disposable environment;
- hide limitations or represent planned work as implemented.

Clear metadata, reproducible tests, raw artifacts, and accurate terminology are welcome. Hidden control
instructions, fabricated numbers, fake badges, and unverifiable security claims are not.

## Testing expectations

- enforcement logic needs a negative test;
- rollback changes need state-integrity assertions;
- checkpoint changes need restart and idempotency tests;
- prompt-injection changes need external-content fixtures;
- verification changes need malformed registry, policy-denial, unavailable-runtime, and explicit-local tests;
- runtime adapters need exact argv, policy digest, cleanup, and adversarial conformance tests;
- performance changes need raw benchmark artifacts and environment metadata.

## Commit guidance

Use imperative commit messages, for example:

```text
Add OpenShell verification adapter
Reject inline code in claim recipes
Record policy digest in verification results
```

Generated code must be understood, tested, and maintained by the contributor.

## License

By contributing, you agree that your contribution is licensed under the repository's MIT License.
