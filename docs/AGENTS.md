# Scoped Instructions: `docs`

Inherit the root `AGENTS.md`.

## Documentation rules

- State whether text is normative, explanatory, a runbook, evidence, or historical design provenance.
- Link every new requirement to intent IDs, an issue, and evals.
- Distinguish current, under-review, partial, planned, unverified, and blocked states.
- Do not copy implementation claims from an unmerged branch into current-state prose.
- Keep relative links valid and avoid duplicate ADR, intent, and eval IDs.
- Architecture and threat-model edits require matching code/test/evidence review unless they only correct
  documentation to the current implementation.
- Public terminology uses technical roles: user, agent, client, contributor, maintainer.

Issue #34 may add this file and nested navigation guides but does not authorize edits to existing
architecture, threat-model, roadmap, or runbook content.
