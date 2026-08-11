#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

SYNC_MODE="sync"
if [[ "${1:-}" == "--dry-run" ]]; then
  SYNC_MODE="dry-run"
elif [[ $# -ne 0 ]]; then
  die "usage: $0 [--dry-run]"
fi

require_repo
require_command git
require_command git-town
require_command gh
require_command timeout
require_clean_worktree
require_no_suspended_operation
require_origin

export GIT_TOWN_INTERACTIVE=false
export GIT_TERMINAL_PROMPT=0
export GH_PROMPT_DISABLED=1
export GIT_EDITOR=true
export GIT_SEQUENCE_EDITOR=:
export GIT_MERGE_AUTOEDIT=no
export TERM=dumb

ensure_state_dir
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="${XT_AEGIS_GIT_TOWN_LOG_FILE:-$STATE_DIR/sync-$stamp.log}"
STATUS_FILE="${XT_AEGIS_GIT_TOWN_STATUS_FILE:-$STATE_DIR/sync-$stamp.status.env}"
validate_output_path "$LOG_FILE"
validate_output_path "$STATUS_FILE"
: >"$LOG_FILE"
chmod 600 "$LOG_FILE"

PRE_STATE_FILE="$(mktemp "$STATE_DIR/pre-state.XXXXXX")"
POST_STATE_FILE="$(mktemp "$STATE_DIR/post-state.XXXXXX")"
PRE_RUNLOG_FILE="$(mktemp "$STATE_DIR/pre-runlog.XXXXXX")"
POST_RUNLOG_FILE="$(mktemp "$STATE_DIR/post-runlog.XXXXXX")"
REF_DIFF_FILE="$(mktemp "$STATE_DIR/ref-diff.XXXXXX")"

cleanup() {
  rm -f -- "$PRE_STATE_FILE" "$POST_STATE_FILE" "$PRE_RUNLOG_FILE" "$POST_RUNLOG_FILE" "$REF_DIFF_FILE"
  release_repo_lock
}
trap cleanup EXIT

preflight_fail() {
  local rc=$1
  local phase=$2
  printf 'preflight failed: phase=%s exit_code=%s\n' "$phase" "$rc" >>"$LOG_FILE"
  bound_file "$LOG_FILE"
  FAILURE_EXIT_CODE="$rc"
  write_status "failure" "preflight_$phase"
  bounded_tail "$LOG_FILE" 200 >&2
  exit "$rc"
}

capture_runlog() {
  git town runlog >"$1" 2>&1 || true
  chmod 600 "$1" 2>/dev/null || true
}

post_sync_inconclusive() {
  local rc=$1
  local phase=$2
  FAILURE_EXIT_CODE="$rc"
  snapshot_repository_state >"$POST_STATE_FILE"
  REFS_AFTER_SHA256="$(sha256_file "$POST_STATE_FILE")"
  {
    printf 'post-sync verification failed: phase=%s exit_code=%s\n' "$phase" "$rc"
    printf 'the mutating sync command returned success; automatic undo is intentionally disabled\n'
    printf 'manual owner must reconcile local and remote refs before another worker runs\n'
  } >>"$LOG_FILE"
  bound_file "$LOG_FILE"
  write_status "failure" "post_sync_unverified_$phase"
  bounded_tail "$LOG_FILE" 200 >&2
  exit "$rc"
}

recover_after_sync() {
  local rc=$1
  local phase=$2
  FAILURE_EXIT_CODE="$rc"
  {
    printf 'mutating sync failed: phase=%s exit_code=%s\n' "$phase" "$rc"
    git town status || true
    git town runlog || true
  } >>"$LOG_FILE" 2>&1
  bound_file "$LOG_FILE"

  capture_runlog "$POST_RUNLOG_FILE"
  local runlog_changed=false
  if ! cmp -s -- "$PRE_RUNLOG_FILE" "$POST_RUNLOG_FILE"; then
    runlog_changed=true
  fi

  # Undo is allowed only after the mutating sync command started and only when
  # Git Town recorded a new run or Git itself reports a suspended operation.
  if [[ "$runlog_changed" == true ]] || has_suspended_operation; then
    run_logged timeout --signal=TERM --kill-after=30s "${GIT_TOWN_TIMEOUT_SECONDS}s" \
      git town undo --non-interactive --no-auto-resolve --verbose || true
  else
    printf 'undo skipped: no new Git Town runlog and no suspended Git operation\n' >>"$LOG_FILE"
  fi
  abort_git_operations

  # Refresh tracking refs before comparing local and remote state. A failed
  # fetch is evidence that restoration cannot be proven, not a reason to claim success.
  local refresh_ok=true
  if ! run_logged timeout --signal=TERM --kill-after=30s "${GIT_TOWN_TIMEOUT_SECONDS}s" \
    git fetch --prune origin; then
    refresh_ok=false
  fi

  snapshot_repository_state >"$POST_STATE_FILE"
  REFS_BEFORE_SHA256="$(sha256_file "$PRE_STATE_FILE")"
  REFS_AFTER_SHA256="$(sha256_file "$POST_STATE_FILE")"

  local recovery_phase="failed_recoverable"
  if [[ "$refresh_ok" == true ]] && cmp -s -- "$PRE_STATE_FILE" "$POST_STATE_FILE" && \
    ! has_suspended_operation && [[ -z "$(git status --porcelain=v1 --untracked-files=normal)" ]]; then
    recovery_phase="failed_restored"
  else
    diff -u -- "$PRE_STATE_FILE" "$POST_STATE_FILE" >"$REF_DIFF_FILE" || true
    {
      printf 'repository state was not proven restored; manual owner required\n'
      cat -- "$REF_DIFF_FILE"
    } >>"$LOG_FILE"
    bound_file "$LOG_FILE"
  fi

  write_status "failure" "$recovery_phase"
  bounded_tail "$LOG_FILE" 200 >&2
  exit "$rc"
}

acquire_repo_lock
write_status "running" "license_preflight"
run_logged timeout --signal=TERM --kill-after=30s "${GIT_TOWN_TIMEOUT_SECONDS}s" \
  "$SCRIPT_DIR/verify-license.sh" || preflight_fail $? "license"

write_status "running" "fetch"
run_logged timeout --signal=TERM --kill-after=30s "${GIT_TOWN_TIMEOUT_SECONDS}s" \
  git fetch --prune origin || preflight_fail $? "fetch"

write_status "running" "stack_preflight"
run_logged timeout --signal=TERM --kill-after=30s "${GIT_TOWN_TIMEOUT_SECONDS}s" \
  "$SCRIPT_DIR/verify-stack.sh" || preflight_fail $? "stack"

if [[ "$SYNC_MODE" == "dry-run" ]]; then
  write_status "success" "dry_run_complete"
  printf 'dry-run complete: log=%s status=%s\n' "$LOG_FILE" "$STATUS_FILE"
  exit 0
fi

snapshot_repository_state >"$PRE_STATE_FILE"
capture_runlog "$PRE_RUNLOG_FILE"
REFS_BEFORE_SHA256="$(sha256_file "$PRE_STATE_FILE")"
write_status "running" "sync"

run_logged timeout --signal=TERM --kill-after=30s "${GIT_TOWN_TIMEOUT_SECONDS}s" \
  git town sync --all --non-interactive --no-auto-resolve --verbose || recover_after_sync $? "sync"

if has_suspended_operation; then
  recover_after_sync 1 "post_sync_suspended_operation"
fi
if [[ -n "$(git status --porcelain=v1 --untracked-files=normal)" ]]; then
  recover_after_sync 1 "post_sync_dirty_worktree"
fi

# Refresh from the forge and prove that the local and tracking refs are stable
# after Git Town reports success.
run_logged timeout --signal=TERM --kill-after=30s "${GIT_TOWN_TIMEOUT_SECONDS}s" \
  git fetch --prune origin || post_sync_inconclusive $? "fetch"
snapshot_repository_state >"$POST_STATE_FILE"
REFS_AFTER_SHA256="$(sha256_file "$POST_STATE_FILE")"
write_status "success" "sync_complete"
printf 'sync complete: log=%s status=%s\n' "$LOG_FILE" "$STATUS_FILE"
