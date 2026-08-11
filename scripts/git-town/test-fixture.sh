#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="${XT_AEGIS_FIXTURE_SOURCE_ROOT:-$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)}"
[[ -n "$REPO_ROOT" ]] || { printf 'error: run from a repository checkout or set XT_AEGIS_FIXTURE_SOURCE_ROOT\n' >&2; exit 1; }
REPO_ROOT="$(cd -- "$REPO_ROOT" 2>/dev/null && pwd -P)" || {
  printf 'error: invalid fixture source root\n' >&2
  exit 1
}
for required_path in .git-town.toml scripts/git-town/common.sh third_party/git-town/LICENSE; do
  [[ -f "$REPO_ROOT/$required_path" ]] || {
    printf 'error: fixture source root is missing %s\n' "$required_path" >&2
    exit 1
  }
done
command -v git >/dev/null 2>&1 || { printf 'error: git is required\n' >&2; exit 1; }
command -v sha256sum >/dev/null 2>&1 || { printf 'error: sha256sum is required for this Linux fixture\n' >&2; exit 1; }

TMP_ROOT="$(mktemp -d)"
cleanup() {
  rm -rf -- "$TMP_ROOT"
}
trap cleanup EXIT

BARE="$TMP_ROOT/origin.git"
FIXTURE="$TMP_ROOT/repo"
BIN="$TMP_ROOT/bin"
mkdir -p -- "$BIN"
git init --bare -q "$BARE"
git init -q -b main "$FIXTURE"
cd -- "$FIXTURE"
git config user.name fixture
git config user.email fixture@example.invalid
printf '.xt-aegis/\n' >.gitignore
printf 'root\n' >root.txt
git add .
git commit -qm root
git remote add origin "$BARE"
git push -q -u origin main

git switch -qc agent/docs-agent-contract main
printf 'foundation\n' >foundation.txt
git add .
git commit -qm foundation
git push -q -u origin agent/docs-agent-contract
for branch in \
  agent/docs-directory-guides \
  agent/docs-harness-contract \
  agent/git-town-unattended-stack \
  agent/docs-eval-first-templates; do
  git switch -qc "$branch" agent/docs-agent-contract
  printf '%s\n' "$branch" >"${branch##*/}.txt"
  git add .
  git commit -qm "$branch"
  git push -q -u origin "$branch"
done
git switch -q agent/git-town-unattended-stack

cp -R -- "$REPO_ROOT/scripts" .
cp -R -- "$REPO_ROOT/third_party" .
cp -- "$REPO_ROOT/.git-town.toml" .
git add .
git commit -qm 'add worker files'
git push -q

cat >"$BIN/git-town" <<'FAKE_GIT_TOWN'
#!/usr/bin/env bash
set -euo pipefail
command_name=${1:-}
shift || true
case "$command_name" in
  --version)
    if [[ "${FAKE_GIT_TOWN_BAD_VERSION:-0}" == 1 ]]; then
      echo 'Git Town 23.0.0'
    else
      echo 'Git Town 24.0.0'
    fi
    ;;
  config)
    exit 0
    ;;
  sync)
    dry_run=false
    for argument in "$@"; do
      [[ "$argument" == --dry-run ]] && dry_run=true
    done
    if [[ "$dry_run" == false && "${FAKE_GIT_TOWN_SYNC_FAIL:-0}" == 1 ]]; then
      exit 7
    fi
    ;;
  status)
    echo 'fixture status'
    ;;
  runlog)
    echo 'fixture runlog'
    ;;
  undo|set-parent)
    exit 0
    ;;
  *)
    printf 'unexpected git-town command: %s\n' "$command_name" >&2
    exit 64
    ;;
esac
FAKE_GIT_TOWN
chmod +x "$BIN/git-town"

cat >"$BIN/gh" <<'FAKE_GH'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == repo && "${2:-}" == view ]]; then
  echo 'ed3c/XT-Aegis'
  exit 0
fi
if [[ "${1:-}" == pr && "${2:-}" == view ]]; then
  pr=${3:?}
  case "$pr" in
    38) printf 'agent/docs-agent-contract\tmain\tOPEN\n' ;;
    39) printf 'agent/docs-directory-guides\tagent/docs-agent-contract\tOPEN\n' ;;
    40)
      if [[ "${FAKE_GH_BAD_BASE:-0}" == 1 ]]; then
        printf 'agent/docs-harness-contract\tmain\tOPEN\n'
      else
        printf 'agent/docs-harness-contract\tagent/docs-agent-contract\tOPEN\n'
      fi
      ;;
    41) printf 'agent/git-town-unattended-stack\tagent/docs-agent-contract\tOPEN\n' ;;
    42) printf 'agent/docs-eval-first-templates\tagent/docs-agent-contract\tOPEN\n' ;;
    *) printf 'unknown PR: %s\n' "$pr" >&2; exit 2 ;;
  esac
  exit 0
fi
printf 'unexpected gh invocation\n' >&2
exit 64
FAKE_GH
chmod +x "$BIN/gh"

export PATH="$BIN:$PATH"
export GIT_TOWN_BINARY_SHA256
GIT_TOWN_BINARY_SHA256="$(sha256sum "$BIN/git-town" | awk '{print $1}')"

scripts/git-town/verify-license.sh >/dev/null
scripts/git-town/verify-stack.sh >/dev/null
scripts/git-town/sync-stack.sh --dry-run >/dev/null
scripts/git-town/sync-stack.sh >/dev/null

# Unknown local branches must never be swept into sync --all.
git branch agent/undeclared-fixture
set +e
output="$(scripts/git-town/verify-stack.sh 2>&1)"
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -q 'undeclared local branch would be included' <<<"$output"
git branch -D agent/undeclared-fixture >/dev/null

# Manifest PR lineage is checked against GitHub metadata.
set +e
output="$(FAKE_GH_BAD_BASE=1 scripts/git-town/verify-stack.sh 2>&1)"
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -q 'PR #40 base mismatch' <<<"$output"

# Version and binary identity mismatches fail closed.
set +e
output="$(FAKE_GIT_TOWN_BAD_VERSION=1 scripts/git-town/verify-license.sh 2>&1)"
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -q 'Git Town version mismatch' <<<"$output"

approved_sha="$GIT_TOWN_BINARY_SHA256"
GIT_TOWN_BINARY_SHA256="$(printf '0%.0s' {1..64})"
set +e
output="$(scripts/git-town/verify-license.sh 2>&1)"
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -q 'installed git-town binary SHA-256 mismatch' <<<"$output"
GIT_TOWN_BINARY_SHA256="$approved_sha"

# Artifact mismatch is rejected without installation.
printf 'not a release package\n' >"$TMP_ROOT/git-town_linux_intel_64.deb"
set +e
output="$(scripts/git-town/verify-release-artifact.sh "$TMP_ROOT/git-town_linux_intel_64.deb" 2>&1)"
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -q 'release artifact SHA-256 mismatch' <<<"$output"

# Dirty and suspended repositories are rejected.
printf 'dirty\n' >dirty.txt
set +e
output="$(scripts/git-town/verify-stack.sh 2>&1)"
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -q 'working tree must be clean' <<<"$output"
rm -- dirty.txt

touch "$(git rev-parse --git-path MERGE_HEAD)"
set +e
output="$(scripts/git-town/verify-stack.sh 2>&1)"
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -Eq 'Git operation is already suspended|working tree must be clean' <<<"$output"
rm -- "$(git rev-parse --git-path MERGE_HEAD)"

# Repository lock contention blocks a second worker.
lock_dir="$(git rev-parse --absolute-git-dir)/xt-aegis-git-town.lock"
mkdir -- "$lock_dir"
set +e
output="$(scripts/git-town/sync-stack.sh --dry-run 2>&1)"
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -q 'another Git Town worker holds' <<<"$output"
rm -rf -- "$lock_dir"

# Semantic sync failure is non-zero and restores the pre-sync branch/HEAD in this fixture.
STATUS_FILE="$TMP_ROOT/failure.status"
LOG_FILE="$TMP_ROOT/failure.log"
set +e
FAKE_GIT_TOWN_SYNC_FAIL=1 \
XT_AEGIS_GIT_TOWN_STATUS_FILE="$STATUS_FILE" \
XT_AEGIS_GIT_TOWN_LOG_FILE="$LOG_FILE" \
scripts/git-town/sync-stack.sh >/dev/null 2>&1
rc=$?
set -e
[[ $rc -eq 7 ]]
grep -q '^RESULT=failure$' "$STATUS_FILE"
grep -q '^PHASE=failed_restored$' "$STATUS_FILE"

printf 'Git Town worker fixture passed\n'
