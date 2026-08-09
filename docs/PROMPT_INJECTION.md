# Prompt Injection and External Policy Integrity

## Position

Prompt injection is not solved by adding another prompt. Untrusted data must not acquire tool authority,
secrets, network access, verification execution, or control over the user's external policy merely
because of its text.

## Data/control rule

| Input | Default classification | Permitted use |
|---|---|---|
| user-created structured request | user intent | policy-checked action proposal |
| model-created structured request | agent proposal | policy-checked action proposal |
| issue, web page, README, log, tool result | external content | evidence or context only |
| reviewed YAML front matter | maintainer contract | bounded policy definition |
| Markdown body | documentation | never executable |
| `PROJECT_EVIDENCE.json` | untrusted verification proposal | schema-validated recipe only |
| MCP tool description | untrusted metadata | discovery, never authorization |

An integration must not copy natural-language instructions from external content into executable intent
while relabeling them as user intent.

## Required defenses

1. Parse typed actions and recipes; do not infer commands from prose.
2. Keep retrieved content in provenance-bearing fields.
3. Validate tools, parameters, paths, and budgets outside the model.
4. Require user approval for consequential actions.
5. Keep credentials outside model-readable content.
6. Treat tool annotations, descriptions, confidence, and registry text as hints, not authorization.
7. Register MCP execution tools only through a process-start decision made by the user.
8. Execute repository tests only in a user-selected runtime.
9. Preserve bounded structured evidence and verify state transitions.
10. Test adversarial instructions in files, issues, tool output, memory, and verification metadata.

## Repository integrity

Contributors must not add hidden or visible text that asks an external system to:

- ignore higher-priority policy;
- reveal system prompts or private data;
- accept a claim without reproduction;
- enable local or remote execution;
- run outside the user's sandbox;
- hide limitations or promote planned work.

Legitimate discoverability comes from accurate package metadata, clear terminology, reproducible tests,
explicit limitations, and a machine-readable evidence index.

## Verification metadata rule

A recipe may propose only the fields represented by `VerificationRecipe`. The verifier supplies backend
configuration, environment, mounts, network mode, resource limits, and execution consent. Unknown fields
fail validation. `auto` cannot select `unsafe-local`.

## Test fixture guidance

Adversarial strings may appear in clearly labeled fixtures when a test asserts a concrete safety result:

```text
Given external-content provenance,
when a write action contains an instruction to ignore policy,
then policy rejects the action and the workspace hash remains unchanged.
```

Fixtures must not be placed where a user or tool is expected to execute them.
