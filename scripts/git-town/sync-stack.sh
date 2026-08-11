#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

dry_run=false
case "${1:-}" in
  "") ;;
  --dry-run) dry_run=true ;;
  *) die "usage: $0 [--dry-run]" ;;
esac

require_repo
require_command git
require_command git-town
require_clean_worktree
require_no_suspended_operation
require_origin

mkdir -p -- "$STATE_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="${XT_AEGIS_GIT_TOWN_LOG_FILE:-$STATE_DIR/sync-$stamp.log}"
STATUS_FILE="${XT_AEGIS_GIT_TOWN_STATUS_FILE:-$STATE_DIR/sync-$stamp.status.env}"
pre_branch="$(git branch --show-current)"
pre_head="$(git rev-parse HEAD)"

cleanup() {
  release_repo_lock
}
trap cleanup EXIT

recover() {
  local rc=$1
  {
    printf 'sync failed with exit code %s\n' "$rc"
    git town status || true
    git town runlog || true
  } >>"$LOG_FILE" 2>&1

  if ! git town undo --non-interactive --verbose >>"$LOG_FILE" 2>&1; then
    git rebase --abort >>"$LOG_FILE" 2>&1 || true
    git merge --abort >>"$LOG_FILE" 2>&1 || true
    git cherry-pick --abort >>"$LOG_FILE" 2>&1 || true
  fi

  local recovered_branch recovered_head phase
  recovered_branch="$(git branch --show-current 2>/dev/null || true)"
  recovered_head="$(git rev-parse HEAD 2>/dev/null || true)"
  phase="failed_recoverable"
  if [[ "$recovered_branch" == "$pre_branch" && "$recovered_head" == "$pre_head" ]]; then
    phase="failed_restored"
  fi
  write_status "failure" "$phase"
  bounded_tail "$LOG_FILE" 200 >&2
  exit "$rc"
}

acquire_repo_lock
write_status "running" "license_preflight"
"$SCRIPT_DIR/verify-license.sh" >>"$LOG_FILE" 2>&1

write_status "running" "fetch"
git fetch --prune origin >>"$LOG_FILE" 2>&1 || recover $?

write_status "running" "stack_preflight"
"$SCRIPT_DIR/verify-stack.sh" >>"$LOG_FILE" 2>&1 || recover $?

export GIT_TOWN_INTERACTIVE=false
export GIT_EDITOR=true
export GIT_SEQUENCE_EDITOR=:
export GIT_MERGE_AUTOEDIT=no
export TERM=dumb

write_status "running" "dry_run"
git town sync --all --dry-run --non-interactive --no-push --verbose >>"$LOG_FILE" 2>&1 || recover $?

if [[ "$dry_run" == true ]]; then
  write_status "success" "dry_run_complete"
  printf 'dry-run complete: log=%s status=%s\n' "$LOG_FILE" "$STATUS_FILE"
  exit 0
fi

write_status "running" "sync"
git town sync --all --non-interactive --auto-resolve --push --verbose >>"$LOG_FILE" 2>&1 || recover $?

require_no_suspended_operation
require_clean_worktree
write_status "success" "sync_complete"
printf 'sync complete: log=%s status=%s\n' "$LOG_FILE" "$STATUS_FILE"
