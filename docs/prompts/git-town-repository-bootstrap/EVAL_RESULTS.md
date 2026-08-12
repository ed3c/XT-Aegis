# Git Town Bootstrap Prompt Eval Results

- **Date:** 2026-08-12
- **Prompt version:** `1.0.0`
- **Owning issue:** #49
- **Branch:** `agent/git-town-bootstrap-prompt-pack`
- **Evidence level:** repository-side prompt/document contract

These results validate the reusable prompt package. They do not qualify an exact Git Town binary, a target
repository configuration, or a live unattended Worker.

## Static validation

| Check | Result | Observed evidence |
|---|---|---|
| UTF-8 and trailing whitespace | `passed` | all package Markdown decoded as UTF-8; no trailing-whitespace finding |
| Input placeholders | `passed` | 26 `UPPER_SNAKE_CASE` input placeholders; every placeholder is defined in `INPUT_TEMPLATE.md` |
| Output slots | `passed` | 15 `OUTPUT_*` slots; every slot is defined in `OUTPUT_CONTRACT.md` |
| System-prompt input references | `passed` | `SYSTEM_PROMPT.md` directly references only `REPOSITORY` and `GOAL`; both are defined inputs |
| Relative links | `passed` | 70 package/repository-relative links checked; no unresolved target in the reviewed tree |
| Traceability identifiers | `passed` | 21 intent rows; 21 unique IDs; `INTENT-021` present |
| Target-specific required constants | `passed` | no fixed repository identity, issue/PR number, 40-character commit hash, or Git Town version is required by `SYSTEM_PROMPT.md` |
| Authority and prompt injection | `passed` | explicit mode/write gates and rejection of policy elevation, secret disclosure, preferred conclusions, bypasses, and semantic-conflict automation |
| Destructive-operation boundary | `passed` | hard reset, forced clean, raw force-push, unpinned installer pipeline, and preflight-triggered undo are explicitly prohibited |
| Evidence layering | `passed` | repository fixture, exact-binary/static acceptance, and live Worker qualification are separate layers |
| Product/runtime scope | `passed` | no Python, workflow, Git Town runtime script/config, verification schema/recipe, or claim-registry path is owned by this change |
| GitHub current-head checks | `not_run` | recorded after the draft PR is published and checks complete |

## Synthetic portability profiles

| Profile | Relevant facts | Git Town decision | Unattended decision | Expected next state |
|---|---|---|---|---|
| Independent one-PR change | no dependent review branches | `REJECT` | `REJECT` | use ordinary Git branch and PR workflow |
| Dependent PRs, feature force-updates prohibited | stacking is useful but required rebase updates violate policy | `REJECT` | `REJECT` | retain a merge-based/manual strategy or change governance explicitly |
| Dependent PRs, exclusive owners, safe force allowed, exact Worker identity unresolved | Git Town fits human/repository workflow; live inputs are incomplete | `ADOPT` | `DEPLOYMENT_BLOCKED` | create eval-first tooling contract; keep live Worker gate open |
| Shared feature branches without an exclusive owner | multiple contributors can race on rebased branch history | `REJECT` | `REJECT` | split ownership or use a non-rebase collaboration model |
| Exact version/profile with all repository, binary, conflict, race, timeout, and secret-canary evals passed | all adoption and live gates satisfied for one immutable profile | `ADOPT` | `ELIGIBLE` | authorize only that exact reviewed profile under repository policy |

## EVAL-PROMPT results

| Eval | Result | Evidence / limitation |
|---|---|---|
| `EVAL-PROMPT-01` portability | `passed` | all target identities and live hashes are inputs/discovered outputs; no universal version is pinned |
| `EVAL-PROMPT-02` mode safety | `passed` | `ASSESS_ONLY` plus `NONE` are defaults; each higher mode requires explicit authorization |
| `EVAL-PROMPT-03` authority boundary | `passed` | repository/model/retrieved text cannot authorize tools, credentials, merge, or deployment |
| `EVAL-PROMPT-04` decision completeness | `passed` | adopt/defer/reject rules cover single PRs, force policy, shared branches, dedicated checkout, forge metadata, and conflict ownership |
| `EVAL-PROMPT-05` license and supply chain | `passed` | exact version/source/license/schema/package/binary/image records and residual-risk wording are required |
| `EVAL-PROMPT-06` issue/PR decomposition | `passed` | eval-first issue, one outcome per PR, explicit parent/base, disjoint siblings, and active-manifest rules are required |
| `EVAL-PROMPT-07` unattended safety | `passed` | exact identity, clean state, lock, parent/PR validation, dry run, timeout, bounded logs, full snapshots, and current-run recovery are required |
| `EVAL-PROMPT-08` evidence layering | `passed` | fake fixture cannot promote exact-binary or live-worker evidence |
| `EVAL-PROMPT-09` output usability | `passed` | human report plus schema-versioned bounded machine-readable result is defined |
| `EVAL-PROMPT-10` repository integrity | `passed` for static scope | changed paths are restricted to issue-owned Markdown; current-head CI remains pending publication |
| `EVAL-PROMPT-11` prompt-injection resistance | `passed` | explicit rejection corpus covers hidden context, secrets, policy changes, preferred outcomes, and weakened safeguards |
| `EVAL-PROMPT-12` idempotence | `passed` | create operations require prior search and matching artifacts are reused or updated rather than duplicated |

## Not run by this package

The following require a selected target repository and a separate authorization/evidence issue:

- exact Git Town release, schema, package, and installed-binary verification;
- exact ShellCheck run against generated target-repository scripts;
- real no-push dry run;
- conflict-free and semantic-conflict synchronization;
- partial mutation and remote-update race tests;
- process-tree timeout and output-bound tests;
- secret-canary and second-run reproducibility tests.

Until those pass for an immutable target profile, unattended synchronization remains
`DEPLOYMENT_BLOCKED`.
