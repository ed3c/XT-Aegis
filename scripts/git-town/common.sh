#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
LOCK_FILE="$SCRIPT_DIR/git-town.lock"
MANIFEST_FILE="$SCRIPT_DIR/stack.tsv"
STATE_DIR="${XT_AEGIS_GIT_TOWN_STATE_DIR:-${REPO_ROOT:-$SCRIPT_DIR}/.xt-aegis/git-town}"
LOCK_DIR=""

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

require_clean_worktree() {
  [[ -z "$(git status --porcelain=v1 --untracked-files=normal)" ]] ||
    die "working tree must be clean, including untracked files"
}

require_origin() {
  git remote get-url origin >/dev/null 2>&1 || die "origin remote is required"
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

acquire_repo_lock() {
  mkdir -p -- "$STATE_DIR"
  local git_dir
  git_dir="$(git rev-parse --absolute-git-dir)"
  LOCK_DIR="$git_dir/xt-aegis-git-town.lock"
  if ! mkdir -- "$LOCK_DIR" 2>/dev/null; then
    die "another Git Town worker holds $LOCK_DIR"
  fi
  printf '%s\n' "$$" >"$LOCK_DIR/pid"
}

release_repo_lock() {
  if [[ -n "$LOCK_DIR" && -d "$LOCK_DIR" ]]; then
    rm -rf -- "$LOCK_DIR"
  fi
}

write_status() {
  local result=$1
  local phase=$2
  local status_path="${STATUS_FILE:-$STATE_DIR/status.env}"
  mkdir -p -- "$(dirname -- "$status_path")"
  {
    printf 'RESULT=%q\n' "$result"
    printf 'PHASE=%q\n' "$phase"
    printf 'UTC=%q\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'BRANCH=%q\n' "$(git branch --show-current 2>/dev/null || true)"
    printf 'HEAD=%q\n' "$(git rev-parse HEAD 2>/dev/null || true)"
    printf 'PID=%q\n' "$$"
  } >"$status_path"
}

bounded_tail() {
  local path=$1
  local lines=${2:-200}
  [[ -f "$path" ]] && tail -n "$lines" -- "$path" || true
}
