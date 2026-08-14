# Research D: Branch-and-evaluate child workspaces

Owning issue: #18. Status: **promote — already owned by leaf 29-C, no separate track needed**.
Date: 2026-08-14.

## Problem

The controller executes one proposal per attempt. Competing plans cannot be compared, so "the first
proposal that passes" is also "the only proposal considered".

## Why this is not a research question any more

The repository already has the three parts this track would have prototyped:

- **Isolation unit.** `IsolatedWorkspace.from_template` creates an owned workspace with an ownership marker
  and a snapshot transaction. A child workspace is another instance, not a new concept.
- **Selection criterion.** Deterministic assertions already decide pass or fail, so a branch is judged by
  the same postconditions as a single run rather than by a model's opinion.
- **Bounded budgets.** `ControllerBudgets` and the admission gate already refuse work that exceeds attempt,
  token, wall-clock, and output limits; N branches multiply the consumption of an existing accounted
  resource rather than introducing an unaccounted one.

## Open questions the implementing leaf must answer

1. **Merge.** Only an assertion-passing, conflict-checked candidate may be adopted. Two branches that touch
   the same region must be a detected conflict, not a last-writer-wins overwrite.
2. **Tie-breaking.** Two passing candidates need a deterministic order, or the run is not reproducible.
   Proposal digest ordering is the cheapest defensible rule.
3. **Escape.** A branch must not read or write outside its own workspace, and the ownership marker check is
   what proves that.
4. **Budget division.** Branch budgets must be divided from the run budget up front, not granted per branch,
   or N branches silently multiply the ceiling.

## Risks

- Branching multiplies cost linearly while improving outcome only when proposals differ meaningfully; a
  provider sampling at temperature 0 produces N identical branches and N times the cost.
- Selection quality is task-specific and is not model uplift by itself, which `docs/IMPLEMENTATION_STACKS.md`
  already states for leaf 29-C.

## Recommendation

**Promote**, and record that it is not a separate research track: leaf 29-C in
`docs/IMPLEMENTATION_STACKS.md` already owns it with a defined outcome, path ownership, and positive and
negative evals. This note exists so that #18 does not schedule duplicate work.

The trust-boundary negative test leaf 29-C must include: *a branch that attempts to write outside its own
workspace root, or to adopt a candidate that failed its assertions, must terminate the run without
mutating the parent workspace.*

## Evidence status

No prototype under this issue. Implementation evidence belongs to leaf 29-C and its child issue.
