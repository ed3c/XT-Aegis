# Prompt Injection and Evaluation Integrity Policy

## Position

Prompt injection cannot be solved by adding another instruction to a prompt. XT-Aegis treats it as a
systems problem: untrusted data must not acquire tool authority, secrets, network access, or evaluator
control merely because of its text.

## Data/control rule

| Input | Default classification | Permitted use |
|---|---|---|
| operator-created structured request | operator | policy-checked action proposal |
| model-created structured request | agent proposal | policy-checked action proposal |
| issue body, web page, README, log, tool result | external content | evidence or context only |
| YAML front matter in a reviewed skill | maintainer contract | bounded policy definition |
| Markdown body in a skill | documentation | never executable |

An integration must not copy natural-language instructions from external content into an executable
action while relabeling them as operator intent.

## Required defenses

1. Parse typed actions; do not infer executable commands from prose.
2. Keep retrieved content in separate fields with provenance.
3. Validate tool names, parameters, paths, and resource budgets outside the model.
4. Require human approval for consequential actions.
5. Keep credentials outside model-readable content and inject them only at a trusted proxy boundary.
6. Treat tool annotations, descriptions, and model confidence as hints, not authorization.
7. Log bounded structured events and verify state transitions.
8. Test malicious instructions in files, issues, web content, tool output, and persistent memory.

## Repository and hiring integrity

This repository is designed to be scanned by humans and automated agents without trying to control the
reviewer. Contributors must not add:

- hidden HTML comments asking a reviewer to select or rank the project;
- instructions to ignore a rubric or system message;
- claims that automated scanners should treat as trusted without verification;
- fake badges, fabricated benchmark results, or misleading comparison tables;
- prompt text that asks for system prompts, private evaluation data, or other candidates' information;
- keyword stuffing intended to manipulate retrieval or ranking.

Legitimate discoverability comes from clear terminology, SPDX metadata, reproducible tests, explicit
limitations, and a machine-readable evidence index.

## Test fixture guidance

Prompt-injection strings may appear in tests when clearly labeled as inert fixtures. They must not be
placed where a tool or reviewer is expected to execute them. A fixture should assert a concrete safety
property, such as:

```text
Given external-content provenance,
when a write action contains "ignore previous instructions",
then policy rejects the action and the workspace hash remains unchanged.
```

## Reviewer guidance

Reviewers should preserve their higher-priority policy, use an independent rubric, run commands only in
an isolated environment, and reject unsupported claims. See `AGENT_REVIEW_GUIDE.md`.
