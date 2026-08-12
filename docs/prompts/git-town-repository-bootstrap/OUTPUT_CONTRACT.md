# Git Town Bootstrap Output Contract

Every run returns a human-readable report and a bounded machine-readable result. Omit secrets and protected
repository content.

## Human-readable sections

1. **Repository assessment**
   - repository and forge identity;
   - default branch, merge methods, branch protection, required checks;
   - existing Git Town configuration, scripts, manifests, notices, issues, branches, and PRs;
   - write permissions and unresolved facts.

2. **Adoption decision**
   - `ADOPT`, `DEFER`, or `REJECT` for Git Town;
   - separate `ELIGIBLE`, `DEPLOYMENT_BLOCKED`, or `REJECT` for unattended sync;
   - reasons and alternatives.

3. **Authority and scope**
   - requested mode and write-authorization level;
   - owned and excluded paths;
   - operations performed and operations intentionally not performed.

4. **Issue and PR graph**
   - program and molecular issues;
   - branch, parent, PR base, merge order, path ownership, conflict owner;
   - parallel-safe siblings and shared integration paths.

5. **Artifact plan or changes**
   - exact file paths;
   - source-of-truth and generated/mirrored relationships;
   - version/license/config identities where available.

6. **Eval results**
   - one row per eval using `passed`, `failed`, `not_run`, or `not_applicable`;
   - procedure, observed result, evidence location, and limitation.

7. **Evidence level**
   - repository contract fixture;
   - exact-binary/static validation;
   - live conflict-free/conflict/race/secret-canary acceptance;
   - claim boundary for each level.

8. **Blockers and residual risks**
   - missing facts, tools, permission, checks, binary, environment, or conflict owner;
   - legal, supply-chain, forge, Git-history, credential, and operational limits.

9. **Next safe state**
   - current branch/PR/issue state;
   - whether the active manifest is empty;
   - whether unattended sync is authorized;
   - exact next safe action without promising background work.

## Machine-readable result

Use this schema as a YAML or JSON block:

```yaml
git_town_bootstrap_result:
  schema_version: 1
  prompt_id: "git-town-repository-bootstrap"
  prompt_version: "1.0.0"

  repository: "{{OWNER/NAME_OR_URL}}"
  forge: "{{FORGE_OR_UNRESOLVED}}"
  default_branch: "{{BRANCH_OR_UNRESOLVED}}"

  requested_mode: "{{MODE}}"
  write_authorization: "{{LEVEL}}"
  adoption_decision: "{{ADOPT|DEFER|REJECT}}"
  unattended_sync_decision: "{{ELIGIBLE|DEPLOYMENT_BLOCKED|REJECT}}"

  writes_performed: false
  issues_created_or_updated: []
  branches_created_or_updated: []
  pull_requests_created_or_updated: []
  merged_pull_requests: []
  changed_paths: []

  git_town:
    exact_version: "{{VERSION_OR_UNRESOLVED}}"
    source_commit: "{{SHA_OR_UNRESOLVED}}"
    license_id: "{{SPDX_OR_UNRESOLVED}}"
    license_identity_verified: false
    package_identity_verified: false
    binary_identity_verified: false
    config_schema_verified: false

  stack:
    active_manifest_rows: 0
    lineage_verified: false
    dedicated_checkout_required: true
    semantic_conflict_owner: "{{OWNER_OR_UNRESOLVED}}"

  evidence:
    repository_fixture: "{{passed|failed|not_run|not_applicable}}"
    exact_binary: "{{passed|failed|not_run|not_applicable}}"
    live_worker: "{{passed|failed|not_run|not_applicable}}"
    paths: []

  evals:
    passed: []
    failed: []
    not_run: []
    not_applicable: []

  blockers: []
  residual_risks: []
  next_safe_action: "{{ACTION_OR_NONE}}"
```

Do not include credentials, hidden chain-of-thought, private prompts, authorization headers, or unrestricted
raw logs in this block.
