# Research A: Signed SKILL contracts and policy provenance

Owning issue: #18. Status: **defer with a named precondition**. Date: 2026-08-14.

## Problem

A compiled SKILL contract decides which executables, paths, network mode, risk level, and assertions apply
to every action. Today its integrity rests on repository access control plus the `source_sha256` recorded
at compile time. That detects a change between compile and execution; it does not establish *who* authored
the contract or whether the author was authorized when they did.

## Assumptions

- Contracts are authored in the repository and reviewed through pull requests.
- The operator running XT-Aegis controls the checkout and the policy file.
- The realistic attacker for v0.x is repository tampering or a compromised contributor account, not a
  nation-state key-extraction attack.

## Alternatives

| Option | What it proves | Cost |
|---|---|---|
| Repository-protected provenance (branch protection, required review, signed commits) | the contract reached `main` through the reviewed path | none beyond configuration; already partly in place |
| Detached signatures over the compiled contract | a named key approved these exact bytes | key custody, rotation, revocation, distribution, and a verification step in the runner |
| Sigstore-style keyless identity | an identity approved these bytes, with a transparency log | an external trust root and network dependency at verification time |

## What would be signed

Signing the raw Markdown is the wrong unit: whitespace and prose changes would invalidate a signature that
protects nothing, while the executable meaning lives in the front matter. The correct unit is the
**canonical compiled contract** — the same normalized bytes the policy digest already covers — plus the
schema version and the compiler version, because a compiler change can alter meaning without altering the
source.

## Risks

- A signature check that fails open is worse than no signature, because it advertises a property it does
  not enforce.
- Key rotation and revocation are the hard part; a stale-signature policy that nobody maintains becomes a
  permanent bypass.
- Verification at execution time adds a failure mode to the deterministic core, which currently has no
  external trust dependency.

## Recommendation

**Defer.** The precondition for revisiting is a distribution model where contracts arrive from outside the
operator's own reviewed checkout — for example a published skill registry, or the mutating MCP adapter in
#16 accepting a contract from a remote caller. Until then, repository-protected provenance covers the
realistic threat and a signature adds custody burden without changing what an attacker must defeat.

When it is revisited, the trust-boundary negative test to write first is: *a contract whose canonical bytes
differ from the signed digest must fail closed before any policy decision is made, and the failure must be
distinguishable from a missing signature.*

## Evidence status

No prototype and no measurement. `PROJECT_EVIDENCE.json` gains no claim.
