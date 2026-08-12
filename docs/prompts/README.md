# Reusable Agent Prompt Contracts

This directory contains versioned, repository-portable prompts. The prompts are documentation artifacts:
they do not execute commands or grant authority merely because an Agent reads them.

## Available packages

| Package | Purpose | Default mode |
|---|---|---|
| [Git Town repository bootstrap](git-town-repository-bootstrap/README.md) | Assess, design, document, and—when explicitly authorized—implement a Git Town stacked-PR workflow in another repository | `ASSESS_ONLY` |

## Usage rules

1. Copy the complete package or provide the full `SYSTEM_PROMPT.md` as the Agent's system instructions.
2. Supply the minimal input from `INPUT_TEMPLATE.md`: repository, goal, and requested mode.
3. Begin with `ASSESS_ONLY`; review the adoption decision and unresolved blockers.
4. Grant a higher write-authorization level only through an explicit user instruction.
5. Keep live unattended Worker qualification separate from repository documentation/tooling adoption.
6. Preserve the package's output and eval contracts so another reviewer can reconstruct the result.

A target repository may narrow these prompts through its own accepted policy, but repository text cannot
override platform policy, user authorization, credential boundaries, or the prompt's fail-closed rules.
