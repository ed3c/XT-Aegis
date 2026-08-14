# Research C: Static knowledge-cache adapters

Owning issue: #18. Status: **defer; the contract is specified here, the implementation is not justified
yet**. Date: 2026-08-14.

## Problem

A model proposing a change to an unfamiliar repository spends prompt budget rediscovering structure. A
precompiled knowledge cache — a derived index of modules, symbols, and their relationships — could reduce
that cost. The hazard is that cached prose reads exactly like instructions.

## Assumptions

- A cache is derived from a specific revision and is stale the moment the revision moves.
- Anything retrieved from a cache reaches the model's context, which is untrusted input by construction.
- Token savings only matter if task outcome and safety hold; a cheaper wrong answer is not a win.

## Adapter contract (the part worth writing down now)

1. Every derived node retains `source_path`, `source_revision`, and a byte range. A node that cannot name
   its source is dropped, not summarized.
2. A cache is bound to one revision. A retrieval against a different revision is a typed staleness error,
   not a best-effort answer.
3. Retrieved content enters the prompt as **data** under the existing external-content provenance, so it
   can never carry execution authority by wording alone.
4. The adapter reports retrieval completeness — what it searched and what it could not — so an empty answer
   is distinguishable from "nothing exists".
5. Invalidation is by revision identity, never by timestamp or heuristic freshness.

## Risks

- **Injection laundering.** A comment in the repository becomes a cache node, and a cache node reads as
  authoritative context. Rule 3 is the whole defense and must be tested, not assumed.
- **Silent staleness.** A cache that answers for the wrong revision produces confident wrong context, which
  is worse than no cache.
- **Measurement trap.** Token reduction is easy to demonstrate and meaningless alone; it must be reported
  next to task success and safety, which is exactly the discipline #11 and #24 impose.

## Recommendation

**Defer** implementation. There is no measured evidence that context assembly is the bottleneck for this
project's tasks, and #24 already recorded that a small model's ceiling was task-solving ability rather than
context. Building a cache first would optimize an unmeasured cost.

The precondition for revisiting: a benchmark under #11 that shows prompt-assembly cost is a material share
of a task's tokens on a pinned corpus. The trust-boundary negative test to write first: *a repository file
containing an instruction-shaped comment, once cached and retrieved, must not change any policy, approval,
or execution decision.*

## Evidence status

No prototype, no measurement, no claim.
