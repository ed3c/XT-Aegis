# Evidence Model

## Why a claim registry exists

Architecture documentation can mix implemented behavior, design intent, benchmark targets, and future
work. XT-Aegis separates them in `PROJECT_EVIDENCE.json` so a user or verification client can inspect
what is runnable without relying on persuasive prose.

## Status vocabulary

| Status | Meaning |
|---|---|
| `implemented` | code and local tests exist |
| `verified-in-ci` | protected CI evidence is bound to a referenced commit |
| `planned` | design or issue exists; no current capability |
| `unverified` | a hypothesis or result lacks reproducible artifacts |

Execution does not promote a registry status automatically. Status changes require a normal code change,
updated evidence, and CI.

## Registry v2 requirements

Every runnable claim contains:

1. a falsifiable statement;
2. implementation and negative-test paths;
3. an argv-only recipe;
4. relative cwd and artifact paths;
5. timeout and output bounds;
6. default-deny network mode;
7. expected verdict;
8. explicit limitations.

The verifier additionally records source, registry, recipe, backend policy, command, and artifact identity.

## Evidence anti-patterns

The following are not proof:

- a diagram without executable behavior;
- prose that repeats a claim;
- a badge with no accessible run;
- screenshots without raw data and environment details;
- benchmark numbers without corpus, hardware, versions, repetitions, and variance;
- a model-generated verdict prompted with the desired outcome;
- a test that mocks the control being claimed;
- a project-operated local run represented as independent sandbox isolation;
- a hash represented as publisher authentication.

## Verification output

A portable result contains:

```text
Claim ID:
Declared status:
Source commit and dirty state:
Registry SHA-256:
Recipe SHA-256:
Backend and policy SHA-256:
Exact argv and cwd:
Exit code / timeout:
Bounded stdout and stderr:
Artifact hashes:
Observed verdict:
Limitations:
```

## Evidence levels

- **Static:** metadata is internally consistent; code is not executed.
- **Project CI:** repository-controlled automation observed the result.
- **User sandbox:** the user reproduced the result in a runtime they selected.
- **Release provenance:** package/image identity is linked to a release workflow and attestation.

These levels are related but not interchangeable.

## Updating a claim

1. implement the behavior;
2. add a negative or failure-path test;
3. update the threat model;
4. add a strict recipe and limitations;
5. run the full suite and structured verification;
6. publish raw evidence where a numeric result is claimed;
7. update release metadata and attestations.
