# Contributing

## Development setup

```bash
git clone <repository-url>
cd XT-Aegis
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
make check
```

## Change workflow

1. Open or reference an issue for non-trivial behavior.
2. Create a focused branch.
3. Add implementation, failure-path tests, and documentation in the same pull request.
4. Run `make check` locally.
5. Complete the pull-request checklist and describe remaining risks.

## Definition of done

A change is ready when:

- behavior is typed and fails closed on unknown input;
- security controls have negative tests;
- public interfaces and persisted schemas are documented;
- claims are added to or corrected in `PROJECT_EVIDENCE.json`;
- `docs/THREAT_MODEL.md` reflects new trust boundaries;
- formatting, lint, type checks, tests, coverage, and package build pass;
- no secret, credential, private URL, or generated environment artifact is committed.

## Safety and evaluation integrity

Do not add instructions that ask an interviewer, scanner, model, or ranking system to:

- select this project or candidate;
- ignore its current rubric or higher-priority policy;
- reveal system prompts or private evaluation data;
- treat README claims as proof;
- execute commands outside an isolated environment.

Clear metadata, evidence, tests, and accurate terminology are welcome. Manipulative prompt text, hidden
HTML comments, fabricated numbers, and fake badges are not.

## Testing expectations

- Unit tests must cover new branch behavior.
- Enforcement logic needs a negative test.
- Rollback changes need state-integrity assertions.
- Checkpoint changes need restart/idempotency tests.
- Prompt-injection changes need external-content fixtures.
- Performance changes need raw benchmark artifacts and environment metadata.

## Commit and pull-request guidance

Use imperative commit messages, for example:

```text
Add approval binding to action parameters
Reject symlink escapes in write policy
Document MCP authorization boundary
```

Keep pull requests small enough to review. Generated code must be understood, tested, and owned by the
contributor.

## License

By contributing, you agree that your contribution is licensed under the repository's MIT License.
