# 2026-08-11 Stacked-PR and Worker-Agent Intent

## Context

Large mixed PRs hide dependency order, make independent review difficult, and cause multiple Agents to
edit the same files. The project needs documentation-first decomposition before more Harness code lands.

## Decisions

1. Use a small root documentation PR, followed by multiple path-disjoint child stacks.
2. Every issue defines evals before implementation and owns one reviewable outcome.
3. Every PR records parent, children, merge order, owned paths, conflict hotspots, and evidence.
4. Git Town is preferred when the worker environment requires a CLI-only, Bash-driven, non-interactive
   stack workflow without a proprietary stacked-PR service dependency.
5. Pin Git Town `v24.0.0`; retain its upstream MIT license and verify installation artifacts by SHA-256.
6. Configure feature synchronization as rebase and perennial synchronization as fast-forward-only.
7. Use `git town sync --all --non-interactive` in a locked, clean checkout.
8. Automatic conflict handling is limited to tool-recognized phantom conflicts. Real semantic conflicts
   stop, recover, and require a named owner.
9. Existing code PRs #23 and #31 remain independently owned and are synchronized only after the
   documentation foundation is accepted.

## Topology

```text
main
└── docs foundation
    ├── directory guides
    ├── Harness contract
    ├── Git Town Bash workflow
    └── eval-first issue/PR templates
```

After the foundation ships, each child becomes a root stack on `main`; children do not depend on each
other.

## Risk position

The upstream MIT license permits commercial use, modification, distribution, sublicensing, and sale, but
no tool choice can prove absolute absence of legal, supply-chain, patent, or operational risk. The worker
gate therefore verifies exact version, license identity, artifact digest, and provenance and fails closed
on mismatch.

Issues [#32](https://github.com/ed3c/XT-Aegis/issues/32),
[#36](https://github.com/ed3c/XT-Aegis/issues/36), and
[#37](https://github.com/ed3c/XT-Aegis/issues/37) own this direction.
