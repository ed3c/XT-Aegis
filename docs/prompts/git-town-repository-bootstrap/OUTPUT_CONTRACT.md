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

  repository: "{{OUTPUT_REPOSITORY}}"
  forge: "{{OUTPUT_FORGE}}"
  default_branch: "{{OUTPUT_DEFAULT_BRANCH}}"

  requested_mode: "{{OUTPUT_REQUESTED_MODE}}"
  write_authorization: "{{OUTPUT_WRITE_AUTHORIZATION}}"
  adoption_decision: "{{OUTPUT_ADOPTION_DECISION}}"
  unattended_sync_decision: "{{OUTPUT_UNATTENDED_SYNC_DECISION}}"

  writes_performed: false
  issues_created_or_updated: []
  branches_created_or_updated: []
  pull_requests_created_or_updated: []
  merged_pull_requests: []
  changed_paths: []

  git_town:
    exact_version: "{{OUTPUT_GIT_TOWN_VERSION}}"
    source_commit: "{{OUTPUT_SOURCE_COMMIT}}"
    license_id: "{{OUTPUT_LICENSE_ID}}"
    license_identity_verified: false
    package_identity_verified: false
    binary_identity_verified: false
    config_schema_verified: false

  stack:
    active_manifest_rows: 0
    lineage_verified: false
    dedicated_checkout_required: true
    semantic_conflict_owner: "{{OUTPUT_CONFLICT_OWNER}}"

  evidence:
    repository_fixture: "{{OUTPUT_REPOSITORY_FIXTURE_STATUS}}"
    exact_binary: "{{OUTPUT_EXACT_BINARY_STATUS}}"
    live_worker: "{{OUTPUT_LIVE_WORKER_STATUS}}"
    paths: []

  evals:
    passed: []
    failed: []
    not_run: []
    not_applicable: []

  blockers: []
  residual_risks: []
  next_safe_action: "{{OUTPUT_NEXT_SAFE_ACTION}}"
```

## Output-value slots

Double-brace values in the machine-readable example are output slots, not user inputs. Resolve them from
discovered facts or set them to `UNRESOLVED`.

| Slot | Meaning or allowed values |
|---|---|
| `{{OUTPUT_REPOSITORY}}` | Exact repository identity or URL |
| `{{OUTPUT_FORGE}}` | Forge name or `UNRESOLVED` |
| `{{OUTPUT_DEFAULT_BRANCH}}` | Exact default branch or `UNRESOLVED` |
| `{{OUTPUT_REQUESTED_MODE}}` | Effective requested mode |
| `{{OUTPUT_WRITE_AUTHORIZATION}}` | Effective write-authorization level |
| `{{OUTPUT_ADOPTION_DECISION}}` | `ADOPT`, `DEFER`, or `REJECT` |
| `{{OUTPUT_UNATTENDED_SYNC_DECISION}}` | `ELIGIBLE`, `DEPLOYMENT_BLOCKED`, or `REJECT` |
| `{{OUTPUT_GIT_TOWN_VERSION}}` | Exact version or `UNRESOLVED` |
| `{{OUTPUT_SOURCE_COMMIT}}` | Exact upstream commit or `UNRESOLVED` |
| `{{OUTPUT_LICENSE_ID}}` | SPDX identifier or `UNRESOLVED` |
| `{{OUTPUT_CONFLICT_OWNER}}` | Named owner/team or `UNRESOLVED` |
| `{{OUTPUT_REPOSITORY_FIXTURE_STATUS}}` | `passed`, `failed`, `not_run`, or `not_applicable` |
| `{{OUTPUT_EXACT_BINARY_STATUS}}` | `passed`, `failed`, `not_run`, or `not_applicable` |
| `{{OUTPUT_LIVE_WORKER_STATUS}}` | `passed`, `failed`, `not_run`, or `not_applicable` |
| `{{OUTPUT_NEXT_SAFE_ACTION}}` | Exact next safe action or `NONE` |

Do not include credentials, hidden chain-of-thought, private prompts, authorization headers, or unrestricted
raw logs in this block.
