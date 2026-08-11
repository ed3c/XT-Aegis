#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
STATE_DIR="${XT_AEGIS_GIT_TOWN_STATE_DIR:-$REPO_ROOT/.xt-aegis/git-town}"
mkdir -p -- "$STATE_DIR"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
wrapper_log="$STATE_DIR/background-$stamp.log"
pid_file="$STATE_DIR/background-$stamp.pid"

case "${1:-}" in
  ""|--dry-run) ;;
  *) printf 'usage: %s [--dry-run]\n' "$0" >&2; exit 2 ;;
esac

nohup "$SCRIPT_DIR/sync-stack.sh" "${1:-}" >"$wrapper_log" 2>&1 < /dev/null &
pid=$!
printf '%s\n' "$pid" >"$pid_file"

printf 'started pid=%s log=%s pid_file=%s\n' "$pid" "$wrapper_log" "$pid_file"
