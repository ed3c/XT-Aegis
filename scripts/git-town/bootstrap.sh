#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

apply=false
if [[ "${1:-}" == "--apply" ]]; then
  apply=true
elif [[ $# -ne 0 ]]; then
  die "usage: $0 [--apply]"
fi

require_repo
require_command git
require_command git-town
require_clean_worktree
require_no_suspended_operation
require_origin
[[ -f "$MANIFEST_FILE" ]] || die "missing stack manifest"

cleanup() {
  release_repo_lock
}
trap cleanup EXIT

if [[ "$apply" == true ]]; then
  acquire_repo_lock
fi

while IFS=$'\t' read -r branch parent issue pr owned_paths evals; do
  [[ -z "${branch:-}" || "${branch:0:1}" == "#" ]] && continue
  [[ -n "$parent" && -n "$issue" && -n "$pr" && -n "$owned_paths" && -n "$evals" ]] ||
    die "invalid stack manifest row"
  git show-ref --verify --quiet "refs/heads/$branch" ||
    die "local branch required before bootstrap: $branch"
  git show-ref --verify --quiet "refs/heads/$parent" ||
    die "local parent required before bootstrap: $parent"

  parent_key="$(git_town_parent_key "$branch")"
  printf 'branch=%s parent=%s issue=%s pr=%s\n' "$branch" "$parent" "$issue" "$pr"
  if [[ "$apply" == true ]]; then
    git config --local "$parent_key" "$parent"
    actual_parent="$(git town config get-parent "$branch" 2>/dev/null || true)"
    [[ "$actual_parent" == "$parent" ]] ||
      die "Git Town parent mismatch after bootstrap: $branch expected $parent observed ${actual_parent:-unset}"
  else
    printf '  git config --local %q %q\n' "$parent_key" "$parent"
  fi
done <"$MANIFEST_FILE"

require_no_suspended_operation
require_clean_worktree
if [[ "$apply" == true ]]; then
  note "parent metadata applied without rebasing; run verify-stack.sh before sync"
fi
