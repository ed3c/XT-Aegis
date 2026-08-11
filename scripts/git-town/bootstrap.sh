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
original_branch="$(git branch --show-current)"
[[ -n "$original_branch" ]] || die "bootstrap requires an attached branch"

restore_branch() {
  if [[ "$(git branch --show-current 2>/dev/null || true)" != "$original_branch" ]]; then
    git switch --quiet "$original_branch" || true
  fi
}
trap restore_branch EXIT

while IFS=$'\t' read -r branch parent issue pr owned_paths evals; do
  [[ -z "${branch:-}" || "${branch:0:1}" == "#" ]] && continue
  printf 'branch=%s parent=%s issue=%s pr=%s\n' "$branch" "$parent" "$issue" "$pr"

  if [[ "$apply" == true ]]; then
    git show-ref --verify --quiet "refs/heads/$branch" ||
      die "local branch required before --apply: $branch"
    git show-ref --verify --quiet "refs/heads/$parent" ||
      die "local parent required before --apply: $parent"
    git switch --quiet "$branch"
    git town set-parent "$parent" --non-interactive --no-auto-resolve
    require_no_suspended_operation
    require_clean_worktree
  else
    printf '  git switch %q && git town set-parent %q --non-interactive --no-auto-resolve\n' "$branch" "$parent"
  fi
done <"$MANIFEST_FILE"

if [[ "$apply" == true ]]; then
  note "parent relationships applied; run verify-stack.sh and a no-push sync dry run"
fi
