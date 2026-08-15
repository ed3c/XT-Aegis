#!/usr/bin/env bash
# The one committed way to lint these scripts.
#
# The flags are load-bearing, which is why this file exists instead of a line in a document. Every script
# here carries a `# shellcheck source=` directive, and those directives do nothing without `-x`: ShellCheck
# refuses to follow a source it was not told to follow. Checking the files one at a time also hides
# cross-file usage, so a variable defined in common.sh and read by bootstrap.sh reads as unused.
#
# Run without `-x`, this directory reports fifteen findings. Seven of them are `SC1091` "not following",
# which is not a defect in the scripts — it is the linter saying it was invoked without permission to
# resolve what the scripts already declare.
#
# Usage:
#   scripts/git-town/lint.sh            # fail on any finding
#   scripts/git-town/lint.sh --selftest # prove the checker itself still reports a real defect

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

selftest=false
if [[ "${1:-}" == "--selftest" ]]; then
  selftest=true
elif [[ $# -ne 0 ]]; then
  printf 'usage: %s [--selftest]\n' "$0" >&2
  exit 2
fi

command -v shellcheck >/dev/null 2>&1 || {
  printf 'error: shellcheck is not installed\n' >&2
  exit 127
}

check() {
  local target_dir=$1
  local rc=0
  local file
  for file in "$target_dir"/*.sh; do
    bash -n -- "$file" || rc=1
  done
  # One invocation with every file, so cross-file usage is visible; -x so the source= directives apply.
  ( cd -- "$target_dir" && shellcheck -x --format=gcc ./*.sh ) || rc=1
  return "$rc"
}

if [[ "$selftest" == true ]]; then
  # A linter that cannot go red is not evidence. Plant one real defect in a copy and require a failure.
  scratch="$(mktemp -d)"
  trap 'rm -rf -- "$scratch"' EXIT
  cp -- "$SCRIPT_DIR"/*.sh "$SCRIPT_DIR"/git-town.lock "$scratch/"
  # A quoted heredoc, so this is literal data rather than code the linter tries to read.
  cat >>"$scratch/common.sh" <<'PLANTED_DEFECT'

unquoted_expansion() {
  local path=$1
  ls $path
}
PLANTED_DEFECT
  if check "$scratch" >/dev/null 2>&1; then
    printf 'selftest FAILED: the checker accepted a deliberately unquoted expansion\n' >&2
    exit 1
  fi
  printf 'selftest passed: the checker rejects a deliberately unquoted expansion\n'
  exit 0
fi

check "$SCRIPT_DIR"
printf 'shellcheck -x: no findings in %s\n' "$SCRIPT_DIR"
