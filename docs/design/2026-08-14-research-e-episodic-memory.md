# Research E: Episodic memory with integrity and deletion policy

Owning issue: #18. Status: **defer; reject the general form, keep one narrow form**. Date: 2026-08-14.

## Problem

Each run starts without knowledge of previous runs. A memory of past observations, decisions, and lessons
could reduce repeated failures. It could also become a durable channel for an attacker: text written once
into memory is read back into every later prompt.

## The distinction that decides the design

Five things get lumped together as "memory", and they have different trust properties:

| Kind | Origin | Can it be trusted as fact? |
|---|---|---|
| Tool evidence | deterministic execution (exit codes, hashes, assertions) | yes, it is already persisted as events and checkpoints |
| User decisions | a human approval or rejection | yes, and already persisted as approvals |
| Observations | what a model saw | only as data |
| Model summaries | what a model concluded | no |
| Inferred lessons | what a model generalized | no, and the most dangerous to replay |

The first two already exist in this repository with provenance, identity binding, and retention under the
operator's control. The value proposition of "episodic memory" is mostly the last three, which are exactly
the ones that must never gain authority.

## Risks

- **Instruction laundering.** A lesson recorded as "always allow writes to `config/`" is model-authored
  text that reads like policy. The repository invariant that model output cannot grant authority must hold
  for stored text as strongly as for live text.
- **Poisoning persistence.** A single successful injection becomes permanent if it is summarized into a
  lesson, so the blast radius of one bad run extends to every future run.
- **Deletion.** Retention, tenant scoping, and deletion are compliance obligations that are cheap to
  declare and expensive to actually honor across derived summaries.

## Recommendation

**Reject** memory of model summaries and inferred lessons. They cannot be verified, and their failure mode
is a durable authority channel.

**Defer** the narrow useful form: a *replayable evidence index* over what is already persisted — terminal
results, assertions, rollback verdicts, and approvals — queried by thread and revision. That form has no
new trust boundary, because every record it returns was produced by deterministic code and already carries
provenance. `xt-aegis replay` (#9) is the first step of exactly this, and the honest next step is to extend
it rather than to introduce a separate memory store.

The trust-boundary negative test whichever form is built must include: *a stored record whose text is
phrased as an instruction must not change any policy, approval, or execution decision when it is
retrieved.*

## Evidence status

No prototype. Retention, tenancy, and deletion policy are undefined and must not be implied by a partial
implementation.
