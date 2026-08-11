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

repo_name="$(gh repo view --json nameWithOwner --jq '.nameWithOwner')"
[[ "$repo_name" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] ||
  die "cannot resolve GitHub repository identity"

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
  git merge-base --is-ancestor "$parent" "$branch" ||
    die "parent is not an ancestor: $parent -> $branch"

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

while IFS= read -r local_branch; do
  [[ -n "${allowed_local[$local_branch]+x}" ]] ||
    die "undeclared local branch would be included by git town sync --all: $local_branch"
done < <(git for-each-ref --format='%(refname:short)' refs/heads/)

git town config >/dev/null
git town sync --all --dry-run --non-interactive --no-push --verbose

printf 'validated %s stack rows, PR lineage, local-branch allowlist, and Git Town dry-run configuration\n' \
  "${#seen_branch[@]}"
