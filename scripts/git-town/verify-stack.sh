#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

require_repo
require_command git
require_command git-town
require_clean_worktree
require_no_suspended_operation
require_origin
[[ -f "$MANIFEST_FILE" ]] || die "missing stack manifest"

declare -A seen_branch=()
line_no=0
while IFS=$'\t' read -r branch parent issue pr owned_paths evals; do
  line_no=$((line_no + 1))
  [[ -z "${branch:-}" || "${branch:0:1}" == "#" ]] && continue
  [[ -n "$parent" && -n "$issue" && -n "$pr" && -n "$owned_paths" && -n "$evals" ]] ||
    die "invalid manifest row $line_no"
  [[ -z "${seen_branch[$branch]+x}" ]] || die "duplicate branch in manifest: $branch"
  seen_branch["$branch"]=1
  [[ "$branch" =~ ^[A-Za-z0-9._/-]+$ ]] || die "unsafe branch name: $branch"
  [[ "$parent" =~ ^[A-Za-z0-9._/-]+$ ]] || die "unsafe parent name: $parent"

  if git show-ref --verify --quiet "refs/heads/$branch"; then
    if git show-ref --verify --quiet "refs/heads/$parent"; then
      git merge-base --is-ancestor "$parent" "$branch" ||
        die "parent is not an ancestor: $parent -> $branch"
    elif git show-ref --verify --quiet "refs/remotes/origin/$parent"; then
      git merge-base --is-ancestor "origin/$parent" "$branch" ||
        die "remote parent is not an ancestor: origin/$parent -> $branch"
    else
      die "parent branch is unavailable: $parent"
    fi
  fi
done <"$MANIFEST_FILE"

git town config >/dev/null
git town sync --all --dry-run --non-interactive --no-push --verbose

printf 'validated %s stack rows and Git Town dry-run configuration\n' "${#seen_branch[@]}"
