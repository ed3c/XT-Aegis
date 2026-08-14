# Research F: Local and hosted model/provider adapters

Owning issue: #18. Status: **promote — the interface is delivered; hosted adapters stay blocked on a named
gate**. Date: 2026-08-14.

## Problem

The deterministic core must not depend on any provider's schema, credentials, or prompt conventions, and a
provider must not be able to influence control-plane identity.

## What is already delivered

- **Provider-neutral typed interface.** `ProposalProvider` returns a `ProposalOutcome` carrying a status, a
  profile, an optional bounded proposal, a diagnostic, and usage counters. The model supplies code or a
  refusal; it never supplies thread IDs, action IDs, idempotency keys, provenance, digests, or policy
  fields. (#26 / PR #51.)
- **One local implementation.** The optional Ollama adapter is loopback-only with a bounded, no-redirect,
  no-proxy transport and typed refusal, timeout, malformed, oversized, truncated, and provider-error
  outcomes.
- **Declared profile enforcement.** The controller's admission gate refuses to continue when the observed
  provider, model, or version differs from the declared profile, and refuses a call whose reservation does
  not fit the remaining budget. (#60.)
- **Destination and credential contract.** Every outbound request passes one default-deny egress decision,
  and credentials are injected only through single-use authorizations bound to an exact request. (#13.)

## What is not delivered, and the gate for each

| Missing | Gate |
|---|---|
| A hosted provider adapter | requires the credential broker to have a production caller, which is #16's authenticated mutating adapter, and requires #13's runtime enforcement to be real rather than a decision plane |
| Schema-adherence measurement across providers | requires #11's benchmark contract and a pinned corpus; #24 already recorded that a 4B local model did not reliably emit a complex schema |
| Latency, token, and outcome comparison between providers | same gate; a comparison across different models, sampling settings, or corpora is not a comparison |

## Risks

- A hosted adapter turns a local-only tool into a network client with credentials, which changes the threat
  model far more than it changes the code.
- Provider-reported usage is the only accounting available; a provider that under-reports under-reports the
  budget. #60's response is to stop rather than to guess, which is the correct direction.
- Measuring schema adherence invites prompt tuning until the number looks good; the benchmark rules in
  `benchmarks/AGENTS.md` exist to prevent exactly that.

## Recommendation

**Promote** the interface work as delivered and close this track's design question: the provider-neutral
boundary exists, is enforced, and has negative tests.

**Do not** add a hosted adapter under this issue. It is a v0.5 concern behind #16, and adding it now would
introduce credentials and network dependence before the isolation and enforcement gates in v0.3 are met —
which is precisely the ordering `docs/ROADMAP.md` and #8's dependency policy require.

## Evidence status

The interface, admission, and egress behaviors have unit evidence in the repository. No live-provider
correctness, availability, privacy, latency, or cost claim is made; those remain `unverified` under #11,
#24, and #29.
