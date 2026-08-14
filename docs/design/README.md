# Design Provenance

These notes preserve maintainer intent that previously existed in design discussions and issue bodies.
They are inputs to ADRs and issues, not implementation claims.

- [`2026-08-11-harness-intent.md`](2026-08-11-harness-intent.md)
- [`2026-08-11-stacked-pr-intent.md`](2026-08-11-stacked-pr-intent.md)

Research-track decisions owned by issue #18. Each note states a decision — promote, defer, split, or
reject — and none of them promotes a capability claim:

| Track | Note | Decision |
|---|---|---|
| A. Signed SKILL contracts | [`2026-08-14-research-a-signed-skills.md`](2026-08-14-research-a-signed-skills.md) | defer until contracts arrive from outside the operator's reviewed checkout |
| B. AST/LSP write scopes | [`2026-08-14-research-b-ast-write-scopes.md`](2026-08-14-research-b-ast-write-scopes.md) | reject as a policy primitive; split out an unchanged-symbol assertion |
| C. Static knowledge caches | [`2026-08-14-research-c-knowledge-caches.md`](2026-08-14-research-c-knowledge-caches.md) | defer; adapter contract recorded, implementation unjustified |
| D. Branch-and-evaluate | [`2026-08-14-research-d-branch-and-evaluate.md`](2026-08-14-research-d-branch-and-evaluate.md) | promote; already owned by leaf 29-C |
| E. Episodic memory | [`2026-08-14-research-e-episodic-memory.md`](2026-08-14-research-e-episodic-memory.md) | reject model summaries and lessons; defer a replayable evidence index |
| F. Provider adapters | [`2026-08-14-research-f-provider-adapters.md`](2026-08-14-research-f-provider-adapters.md) | promote as delivered; hosted adapters stay gated by #16 |

A design note records context, decisions, rejected shortcuts, source links, unresolved questions, and the
issue that owns promotion into a normative contract. Once accepted, an ADR or other normative document
takes precedence while the provenance note remains historical.
