#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

mode=()
if [[ "${1:-}" == "--dry-run" ]]; then
  mode=(--dry-run)
elif [[ $# -ne 0 ]]; then
  die "usage: $0 [--dry-run]"
fi

require_repo
require_command nohup
require_clean_worktree
require_no_suspended_operation
require_origin
ensure_state_dir

# The child acquires the authoritative repository lock. Refuse an already-held
# lock here as an immediate signal, while still relying on the child for race safety.
prospective_lock="$(git rev-parse --absolute-git-dir)/xt-aegis-git-town.lock"
[[ ! -d "$prospective_lock" ]] || die "another Git Town worker holds $prospective_lock"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
wrapper_log="$STATE_DIR/background-$stamp.log"
pid_file="$STATE_DIR/background-$stamp.pid"
launch_file="$STATE_DIR/background-$stamp.launch.env"
validate_output_path "$wrapper_log"
validate_output_path "$pid_file"
validate_output_path "$launch_file"

nohup "$SCRIPT_DIR/sync-stack.sh" "${mode[@]}" >"$wrapper_log" 2>&1 < /dev/null &
pid=$!
printf '%s\n' "$pid" >"$pid_file"
chmod 600 "$wrapper_log" "$pid_file"
{
  printf 'PID=%q\n' "$pid"
  printf 'MODE=%q\n' "${mode[*]:-sync}"
  printf 'UTC=%q\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'WRAPPER_LOG=%q\n' "$wrapper_log"
  printf 'PID_FILE=%q\n' "$pid_file"
} >"$launch_file"
chmod 600 "$launch_file"

printf 'started pid=%s log=%s pid_file=%s launch=%s\n' "$pid" "$wrapper_log" "$pid_file" "$launch_file"
