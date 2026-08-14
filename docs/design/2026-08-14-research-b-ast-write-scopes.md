# Research B: AST and LSP-aware write scopes

Owning issue: #18. Status: **reject as a policy primitive; split one narrow piece**. Date: 2026-08-14.

## Problem

Write policy is expressed as allowlisted relative paths. A path is coarse: "may write `app.py`" permits
rewriting the whole module when the intent was "may change one function". A symbol-level scope would be a
tighter permission.

## Assumptions

- Scope inference would run on the proposal before execution, in the trusted core.
- The repository targets multiple languages over time; today's fixtures are Python.
- A scope check is only meaningful if a violation is *detected*, not merely discouraged.

## Alternatives

| Option | Failure mode that decides it |
|---|---|
| Static AST scope inference in the trusted core | a parser is a large, language-specific attack surface running on model-influenced input, inside the component whose smallness is the security argument |
| LSP-derived scopes from a language server | introduces a long-lived external process with its own trust and version story; a stale index silently widens or narrows the permission |
| Explicit user-approved path plus symbol *assertion* | no inference; the model proposes, the contract declares, and a postcondition proves the untouched symbols are unchanged |

## Failure modes tested against

- **Stale index.** An LSP index that lags the workspace approves a scope that no longer exists.
- **Dynamic languages.** Reflection, monkey-patching, and code generation make "the reference closure of
  this symbol" undecidable in general, so a closure-based scope is an approximation presented as a bound.
- **Generated files.** A generated module has no meaningful author-level scope; its boundary is the
  generator, not the AST.

## Recommendation

**Reject** AST or LSP scope inference as a policy primitive. The cost is a language-specific parser in the
trusted core, and the benefit is an approximation that is wrong exactly in the cases (reflection,
generation, staleness) where an attacker would aim.

**Split out** the one piece that is cheap and exact: a declarative *unchanged-symbol assertion*. The
contract names symbols that must be byte-identical after the action; a postcondition compares their
extracted text before and after. That is a deterministic check on observed output rather than an inference
about intent, and it fails closed with no parser in the authorization path — the extraction runs in the
same bounded, sandboxed condition command as any other assertion.

The trust-boundary negative test for that split piece: *an action that rewrites a protected symbol while
leaving the file's byte count unchanged must fail the assertion and roll back.*

## Evidence status

No prototype. The split piece needs its own eval-first issue before implementation; it is not implied by
this note.
