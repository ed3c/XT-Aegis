# Git Town Repository Bootstrap Prompt Package

- **Prompt ID:** `git-town-repository-bootstrap`
- **Package version:** `1.0.0`
- **Status:** reusable documentation contract
- **Default mode:** `ASSESS_ONLY`
- **Owning issue:** XT-Aegis issue #49
- **Intent:** `INTENT-021`

This package lets an Agent evaluate and prepare Git Town adoption in another repository without copying
XT-Aegis-specific identities, hashes, branches, issue numbers, or assumptions.

## Package files

| File | Purpose |
|---|---|
| [`SYSTEM_PROMPT.md`](SYSTEM_PROMPT.md) | Copy-ready system instructions |
| [`INPUT_TEMPLATE.md`](INPUT_TEMPLATE.md) | Minimal and full user input contract |
| [`OUTPUT_CONTRACT.md`](OUTPUT_CONTRACT.md) | Required human-readable and machine-readable result |
| [`EVALS.md`](EVALS.md) | Prompt conformance and target-repository acceptance evals |
| [`EVAL_RESULTS.md`](EVAL_RESULTS.md) | Static and synthetic portability evidence for this package version |
| [`ADOPTION_CHECKLIST.md`](ADOPTION_CHECKLIST.md) | Compact execution/review checklist |

## Recommended lifecycle

```text
ASSESS_ONLY
  -> DESIGN_AND_ISSUES
  -> DOCS_AND_TOOLING
  -> LIVE_WORKER_QUALIFICATION
  -> optional MERGE_AFTER_GREEN
```

Each transition requires explicit authorization. A repository may adopt Git Town for human-operated stacks
while keeping unattended synchronization rejected or deployment-blocked.

## Minimal invocation

Use the complete [`SYSTEM_PROMPT.md`](SYSTEM_PROMPT.md), then provide:

```text
REPOSITORY: owner/name or repository URL
GOAL: assess and prepare a safe Git Town stacked-PR workflow
REQUESTED_MODE: ASSESS_ONLY
WRITE_AUTHORIZATION: NONE
```

The Agent discovers repository facts before requesting more information. Unknown material facts remain
`UNRESOLVED`; they are not invented.

## Portability boundary

The package deliberately does not pin a universal Git Town version. Every target repository must select
and verify an exact version, source commit, license identity, configuration schema, package checksum, and
installed-binary checksum for its own declared profile.

The package also does not promise zero legal, security, supply-chain, or operational risk. Its supported
claim is limited to the evidence produced for the exact target profile.
