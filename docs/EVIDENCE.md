# Evidence Model

## Why a claim registry exists

Architecture portfolios often mix implemented behavior, design intent, benchmark targets, and future
work. XT-Aegis separates them in `PROJECT_EVIDENCE.json` so a reviewer can determine what deserves
credit without relying on persuasive prose.

## Status vocabulary

| Status | Meaning |
|---|---|
| `implemented` | code and local tests exist in the repository |
| `verified-in-ci` | the implementation has a passing protected CI run for the referenced commit |
| `partial` | some behavior exists, but a stated boundary or backend is missing |
| `planned` | design or issue exists; no implementation credit should be given |
| `unverified` | a hypothesis or result lacks a reproducible artifact |

The initial repository uses `implemented`. Release automation may promote a claim to `verified-in-ci`
only when the commit SHA and CI evidence are recorded.

## Evidence requirements

A security or reliability claim should contain:

1. a falsifiable sentence;
2. implementation paths;
3. at least one negative or failure-path test;
4. a bounded verification command;
5. explicit limitations;
6. no dependency on the repository asking to be trusted.

## Evidence anti-patterns

The following do not count as proof:

- an architecture diagram without code;
- a README statement that repeats the claim;
- a badge with no accessible run;
- generated screenshots without raw data and environment details;
- a benchmark number without corpus, hardware, versions, warm-up, repetitions, and variance;
- an LLM judge that was prompted with the desired conclusion;
- a test that mocks the control being tested;
- a `planned` item presented in the same visual style as an implemented item.

## Updating the registry

When adding a control:

1. implement the behavior;
2. add a negative test;
3. add or update the threat model;
4. add a claim entry with `implemented` status;
5. run the complete local verification suite;
6. link the pull request and CI run in the release notes;
7. promote status only after verification.

## Reviewer output template

A reviewer can report:

```text
Claim ID:
Observed status:
Evidence inspected:
Command executed:
Result:
Limitations confirmed:
Unsupported statements:
```

This format keeps the evaluation independent from the project's preferred narrative.
