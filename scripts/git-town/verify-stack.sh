#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

require_repo
require_command git
require_command git-town
require_command gh
require_clean_worktree
require_no_suspended_operation
require_origin
[[ -f "$MANIFEST_FILE" ]] || die "missing stack manifest"
config_sha="$(sha256_file "$REPO_ROOT/.git-town.toml")"
[[ "$config_sha" == "$GIT_TOWN_CONFIG_SHA256" ]] || die "Git Town config SHA-256 mismatch"

export GIT_TOWN_INTERACTIVE=false
export GIT_EDITOR=true
export GIT_SEQUENCE_EDITOR=:
export GIT_MERGE_AUTOEDIT=no
export TERM=dumb

repo_name="$(gh repo view --json nameWithOwner --jq '.nameWithOwner')"
[[ "$repo_name" == "$GIT_TOWN_EXPECTED_REPOSITORY" ]] ||
  die "GitHub repository mismatch: expected $GIT_TOWN_EXPECTED_REPOSITORY, observed ${repo_name:-unknown}"

declare -A seen_branch=()
declare -A seen_issue=()
declare -A seen_pr=()
declare -A allowed_local=()
line_no=0
while IFS=$'\t' read -r branch parent issue pr owned_paths evals; do
  line_no=$((line_no + 1))
  [[ -z "${branch:-}" || "${branch:0:1}" == "#" ]] && continue
  [[ -n "$parent" && -n "$issue" && -n "$pr" && -n "$owned_paths" && -n "$evals" ]] ||
    die "invalid manifest row $line_no"
  [[ "$issue" =~ ^[0-9]+$ ]] || die "issue must be numeric on row $line_no"
  [[ "$pr" =~ ^[0-9]+$ ]] || die "PR must be numeric on row $line_no"
  [[ -z "${seen_branch[$branch]+x}" ]] || die "duplicate branch in manifest: $branch"
  [[ -z "${seen_issue[$issue]+x}" ]] || die "duplicate issue in manifest: $issue"
  [[ -z "${seen_pr[$pr]+x}" ]] || die "duplicate PR in manifest: $pr"
  seen_branch["$branch"]=1
  seen_issue["$issue"]=1
  seen_pr["$pr"]=1
  allowed_local["$branch"]=1
  allowed_local["$parent"]=1
  [[ "$branch" =~ ^[A-Za-z0-9._/-]+$ ]] || die "unsafe branch name: $branch"
  [[ "$parent" =~ ^[A-Za-z0-9._/-]+$ ]] || die "unsafe parent name: $parent"

  git show-ref --verify --quiet "refs/heads/$branch" ||
    die "manifest branch is not checked out locally: $branch"
  git show-ref --verify --quiet "refs/heads/$parent" ||
    die "manifest parent is not checked out locally: $parent"
  git show-ref --verify --quiet "refs/remotes/origin/$branch" ||
    die "manifest branch is missing from origin tracking refs: $branch"
  git show-ref --verify --quiet "refs/remotes/origin/$parent" ||
    die "manifest parent is missing from origin tracking refs: $parent"
  git merge-base "$parent" "$branch" >/dev/null ||
    die "manifest branches do not share history: $parent -> $branch"

  actual_upstream="$(git for-each-ref --format='%(upstream:short)' "refs/heads/$branch")"
  [[ "$actual_upstream" == "origin/$branch" ]] ||
    die "branch upstream mismatch: $branch expected origin/$branch observed ${actual_upstream:-unset}"

  manifest_parent="$(configured_parent "$branch")"
  [[ "$manifest_parent" == "$parent" ]] ||
    die "Git Town parent metadata mismatch: $branch expected $parent observed ${manifest_parent:-unset}; run bootstrap.sh --apply"
  git_town_parent="$(git town config get-parent "$branch" 2>/dev/null || true)"
  [[ "$git_town_parent" == "$parent" ]] ||
    die "Git Town resolved parent mismatch: $branch expected $parent observed ${git_town_parent:-unset}"

  pr_metadata="$(gh pr view "$pr" --repo "$repo_name" \
    --json headRefName,baseRefName,state \
    --jq '[.headRefName,.baseRefName,.state] | @tsv')"
  IFS=$'\t' read -r actual_head actual_base actual_state <<<"$pr_metadata"
  [[ "$actual_head" == "$branch" ]] ||
    die "PR #$pr head mismatch: expected $branch, observed $actual_head"
  [[ "$actual_base" == "$parent" ]] ||
    die "PR #$pr base mismatch: expected $parent, observed $actual_base"
  [[ "$actual_state" == "OPEN" ]] || die "PR #$pr is not open: $actual_state"
done <"$MANIFEST_FILE"

(( ${#seen_branch[@]} > 0 )) ||
  die "stack manifest has no active rows; no unattended sync is authorized"

while IFS= read -r local_branch; do
  [[ -n "${allowed_local[$local_branch]+x}" ]] ||
    die "undeclared local branch would be included by git town sync --all: $local_branch"
done < <(git for-each-ref --format='%(refname:short)' refs/heads/)

require_command timeout
timeout --signal=TERM --kill-after=30s "${GIT_TOWN_TIMEOUT_SECONDS}s" git town config >/dev/null
timeout --signal=TERM --kill-after=30s "${GIT_TOWN_TIMEOUT_SECONDS}s" \
  git town sync --all --dry-run --non-interactive --no-auto-resolve --no-push --verbose

printf 'validated %s stack rows, explicit parents, PR lineage, local-branch allowlist, and Git Town dry run\n' \
  "${#seen_branch[@]}"
