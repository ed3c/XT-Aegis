#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

if (( BASH_VERSINFO[0] < 4 )); then
  printf 'error: Bash 4 or newer is required; observed %s\n' "$BASH_VERSION" >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
GIT_DIR="$(git -C "$SCRIPT_DIR" rev-parse --absolute-git-dir 2>/dev/null || true)"
LOCK_FILE="$SCRIPT_DIR/git-town.lock"
MANIFEST_FILE="$SCRIPT_DIR/stack.tsv"
STATE_DIR="${XT_AEGIS_GIT_TOWN_STATE_DIR:-${GIT_DIR:-$SCRIPT_DIR}/xt-aegis/git-town}"
LOCK_DIR=""
MAX_LOG_BYTES="${XT_AEGIS_GIT_TOWN_MAX_LOG_BYTES:-1048576}"
GIT_TOWN_TIMEOUT_SECONDS="${XT_AEGIS_GIT_TOWN_TIMEOUT_SECONDS:-1800}"

[[ -r "$LOCK_FILE" ]] || {
  printf 'error: missing Git Town lock file: %s\n' "$LOCK_FILE" >&2
  exit 1
}
# shellcheck source=git-town.lock
source "$LOCK_FILE"

[[ "$MAX_LOG_BYTES" =~ ^[0-9]+$ ]] && (( MAX_LOG_BYTES >= 65536 && MAX_LOG_BYTES <= 8388608 )) || {
  printf 'error: XT_AEGIS_GIT_TOWN_MAX_LOG_BYTES must be between 65536 and 8388608\n' >&2
  exit 1
}
[[ "$GIT_TOWN_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] && (( GIT_TOWN_TIMEOUT_SECONDS >= 1 && GIT_TOWN_TIMEOUT_SECONDS <= 7200 )) || {
  printf 'error: XT_AEGIS_GIT_TOWN_TIMEOUT_SECONDS must be between 1 and 7200\n' >&2
  exit 1
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

note() {
  printf '%s\n' "$*" >&2
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

require_repo() {
  [[ -n "$REPO_ROOT" ]] || die "not inside a Git repository"
  cd -- "$REPO_ROOT"
  [[ -f ".git-town.toml" ]] || die "missing .git-town.toml"
}

git_path_exists() {
  local relative=$1
  local path
  path="$(git rev-parse --git-path "$relative")"
  [[ -e "$path" ]]
}

require_no_suspended_operation() {
  local markers=(rebase-merge rebase-apply MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD BISECT_LOG)
  local marker
  for marker in "${markers[@]}"; do
    if git_path_exists "$marker"; then
      die "Git operation is already suspended: $marker"
    fi
  done
}

has_suspended_operation() {
  local markers=(rebase-merge rebase-apply MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD BISECT_LOG)
  local marker
  for marker in "${markers[@]}"; do
    if git_path_exists "$marker"; then
      return 0
    fi
  done
  return 1
}

require_clean_worktree() {
  [[ -z "$(git status --porcelain=v1 --untracked-files=normal)" ]] ||
    die "working tree must be clean, including untracked files"
}

require_origin() {
  local origin_url expected_override
  origin_url="$(git remote get-url origin 2>/dev/null || true)"
  [[ -n "$origin_url" ]] || die "origin remote is required"

  expected_override="${XT_AEGIS_GIT_TOWN_EXPECTED_ORIGIN_URL:-}"
  if [[ -n "$expected_override" ]]; then
    [[ "$origin_url" == "$expected_override" ]] ||
      die "origin mismatch: expected $expected_override, observed $origin_url"
    return
  fi

  case "$origin_url" in
    "https://github.com/$GIT_TOWN_EXPECTED_REPOSITORY"|\
    "https://github.com/$GIT_TOWN_EXPECTED_REPOSITORY.git"|\
    "git@github.com:$GIT_TOWN_EXPECTED_REPOSITORY.git"|\
    "ssh://git@github.com/$GIT_TOWN_EXPECTED_REPOSITORY.git") ;;
    *) die "origin must be the approved repository without embedded credentials: $GIT_TOWN_EXPECTED_REPOSITORY" ;;
  esac
}

ensure_state_dir() {
  [[ -n "$STATE_DIR" ]] || die "state directory is empty"
  [[ ! -L "$STATE_DIR" ]] || die "state directory cannot be a symlink: $STATE_DIR"
  mkdir -p -- "$STATE_DIR"
  [[ -d "$STATE_DIR" && ! -L "$STATE_DIR" ]] || die "invalid state directory: $STATE_DIR"
  chmod 700 -- "$STATE_DIR"
}

validate_output_path() {
  local path=$1
  [[ -n "$path" ]] || die "output path is empty"
  [[ ! -L "$path" ]] || die "output path cannot be a symlink: $path"
  local parent
  parent="$(dirname -- "$path")"
  [[ ! -L "$parent" ]] || die "output parent cannot be a symlink: $parent"
  mkdir -p -- "$parent"
  [[ -d "$parent" ]] || die "output parent is not a directory: $parent"
}

sha256_file() {
  local path=$1
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -- "$path" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 -- "$path" | awk '{print $1}'
  else
    die "sha256sum or shasum is required"
  fi
}

git_town_parent_key() {
  printf 'git-town-branch.%s.parent' "$1"
}

configured_parent() {
  git config --local --get "$(git_town_parent_key "$1")" 2>/dev/null || true
}

snapshot_repository_state() {
  {
    printf 'CURRENT_BRANCH\t%s\n' "$(git branch --show-current 2>/dev/null || true)"
    printf 'HEAD\t%s\n' "$(git rev-parse HEAD 2>/dev/null || true)"
    git for-each-ref \
      --format='REF\t%(refname)\t%(objectname)' \
      refs/heads refs/remotes/origin
    git config --local --get-regexp '^git-town-branch\..*\.parent$' 2>/dev/null | \
      sed 's/^/PARENT\t/' || true
  } | LC_ALL=C sort
}

acquire_repo_lock() {
  ensure_state_dir
  local git_dir
  git_dir="$(git rev-parse --absolute-git-dir)"
  LOCK_DIR="$git_dir/xt-aegis-git-town.lock"
  if ! mkdir -- "$LOCK_DIR" 2>/dev/null; then
    local owner="unknown"
    [[ -f "$LOCK_DIR/pid" ]] && owner="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
    die "another Git Town worker holds $LOCK_DIR (pid=${owner:-unknown})"
  fi
  printf '%s\n' "$$" >"$LOCK_DIR/pid"
}

release_repo_lock() {
  if [[ -n "$LOCK_DIR" && -d "$LOCK_DIR" ]]; then
    rm -f -- "$LOCK_DIR/pid"
    rmdir -- "$LOCK_DIR" 2>/dev/null || true
  fi
}

write_status() {
  local result=$1
  local phase=$2
  local status_path="${STATUS_FILE:-$STATE_DIR/status.env}"
  local status_dir temporary
  status_dir="$(dirname -- "$status_path")"
  mkdir -p -- "$status_dir"
  temporary="$(mktemp "$status_dir/.status.XXXXXX")"
  {
    printf 'RESULT=%q\n' "$result"
    printf 'PHASE=%q\n' "$phase"
    printf 'MODE=%q\n' "${SYNC_MODE:-unknown}"
    printf 'UTC=%q\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'BRANCH=%q\n' "$(git branch --show-current 2>/dev/null || true)"
    printf 'HEAD=%q\n' "$(git rev-parse HEAD 2>/dev/null || true)"
    printf 'PID=%q\n' "$$"
    printf 'EXIT_CODE=%q\n' "${FAILURE_EXIT_CODE:-0}"
    printf 'REFS_BEFORE_SHA256=%q\n' "${REFS_BEFORE_SHA256:-}"
    printf 'REFS_AFTER_SHA256=%q\n' "${REFS_AFTER_SHA256:-}"
  } >"$temporary"
  mv -f -- "$temporary" "$status_path"
}

bound_file() {
  local path=$1
  [[ -f "$path" ]] || return 0
  local size temporary keep
  size="$(wc -c <"$path")"
  if (( size <= MAX_LOG_BYTES )); then
    return 0
  fi
  keep=$((MAX_LOG_BYTES - 96))
  temporary="$(mktemp "$(dirname -- "$path")/.bounded.XXXXXX")"
  printf '[earlier output truncated; retained final %s bytes]\n' "$keep" >"$temporary"
  tail -c "$keep" -- "$path" >>"$temporary"
  mv -f -- "$temporary" "$path"
}

run_logged() {
  local rc
  if "$@" >>"$LOG_FILE" 2>&1; then
    rc=0
  else
    rc=$?
  fi
  bound_file "$LOG_FILE"
  return "$rc"
}

bounded_tail() {
  local path=$1
  local lines=${2:-200}
  [[ -f "$path" ]] && tail -n "$lines" -- "$path" || true
}

abort_git_operations() {
  git rebase --abort >>"$LOG_FILE" 2>&1 || true
  git merge --abort >>"$LOG_FILE" 2>&1 || true
  git cherry-pick --abort >>"$LOG_FILE" 2>&1 || true
  bound_file "$LOG_FILE"
}
