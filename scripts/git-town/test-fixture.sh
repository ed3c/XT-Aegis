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
for required_path in \
  .git-town.toml \
  scripts/git-town/common.sh \
  scripts/git-town/bootstrap.sh \
  scripts/git-town/verify-stack.sh \
  scripts/git-town/sync-stack.sh \
  scripts/git-town/sync-background.sh \
  third_party/git-town/LICENSE; do
  [[ -f "$REPO_ROOT/$required_path" ]] || {
    printf 'error: fixture source root is missing %s\n' "$required_path" >&2
    exit 1
  }
done
for command_name in git sha256sum timeout; do
  command -v "$command_name" >/dev/null 2>&1 || {
    printf 'error: %s is required for this Linux fixture\n' "$command_name" >&2
    exit 1
  }
done

TMP_ROOT="$(mktemp -d)"
cleanup() {
  rm -rf -- "$TMP_ROOT"
}
trap cleanup EXIT

BARE="$TMP_ROOT/origin.git"
FIXTURE="$TMP_ROOT/repo"
BIN="$TMP_ROOT/bin"
FAKE_STATE="$TMP_ROOT/fake-git-town"
mkdir -p -- "$BIN" "$FAKE_STATE"
git init --bare -q "$BARE"
git init -q -b main "$FIXTURE"
cd -- "$FIXTURE"
git config user.name fixture
git config user.email fixture@example.invalid
printf 'root\n' >root.txt
git add .
git commit -qm root
git remote add origin "$BARE"
git push -q -u origin main

for branch in \
  agent/docs-directory-guides \
  agent/docs-harness-contract \
  agent/git-town-unattended-stack \
  agent/docs-eval-first-templates; do
  git switch -qc "$branch" main
  printf '%s\n' "$branch" >"${branch##*/}.txt"
  git add .
  git commit -qm "$branch"
  git push -q -u origin "$branch"
done

# Advance main after children exist. Verification must accept this normal
# pre-sync condition because parent/child only need shared history before rebase.
git switch -q main
printf 'main-advanced\n' >>root.txt
git add root.txt
git commit -qm 'advance main'
git push -q
git switch -q agent/git-town-unattended-stack

cp -R -- "$REPO_ROOT/scripts" .
cp -R -- "$REPO_ROOT/third_party" .
cp -- "$REPO_ROOT/.git-town.toml" .
# The repository manifest is intentionally empty when no real stack is active.
# Populate a synthetic active topology only inside this disposable fixture.
cat >scripts/git-town/stack.tsv <<'FIXTURE_STACK'
# branch	parent	issue	pr	owned_paths	evals
agent/docs-directory-guides	main	34	39	**/README.md,**/AGENTS.md(directory-scoped-only)	EVAL-DIR-*
agent/docs-harness-contract	main	35	40	docs/CODING_AGENT_HARNESS.md,docs/HARNESS_EVALS.md,docs/adr/0005-trusted-harness-orchestration.md	EVAL-HARNESS-*
agent/git-town-unattended-stack	main	36	41	.git-town.toml,docs/STACKED_PRS.md,docs/GIT_TOWN_LICENSE.md,scripts/git-town/**,third_party/**	EVAL-GIT-*
agent/docs-eval-first-templates	main	37	42	.github/ISSUE_TEMPLATE/work_slice.yml,.github/pull_request_template.md,docs/ISSUE_PR_CONTRACT.md	EVAL-META-*
FIXTURE_STACK
git add .
git commit -qm 'add worker files'
git push -q

cat >"$BIN/git-town" <<'FAKE_GIT_TOWN'
#!/usr/bin/env bash
set -Eeuo pipefail
command_name=${1:-}
shift || true
state=${FAKE_GIT_TOWN_STATE:?}
case "$command_name" in
  --version)
    if [[ "${FAKE_GIT_TOWN_BAD_VERSION:-0}" == 1 ]]; then
      echo 'Git Town 23.0.0'
    else
      echo 'Git Town 24.0.0'
    fi
    ;;
  config)
    if [[ "${1:-}" == get-parent ]]; then
      branch=${2:-$(git branch --show-current)}
      git config --local --get "git-town-branch.$branch.parent"
    else
      exit 0
    fi
    ;;
  sync)
    dry_run=false
    for argument in "$@"; do
      [[ "$argument" == --dry-run ]] && dry_run=true
    done
    if [[ "$dry_run" == true ]]; then
      exit 0
    fi
    printf 'run-%s\n' "$(date +%s%N)" >"$state/runlog"
    spam_bytes=${FAKE_GIT_TOWN_SPAM_BYTES:-0}
    if [[ "$spam_bytes" =~ ^[0-9]+$ ]] && (( spam_bytes > 0 )); then
      head -c "$spam_bytes" /dev/zero | tr '\0' x
      printf '\n'
    fi
    sleep_seconds=${FAKE_GIT_TOWN_SYNC_SLEEP:-0}
    if [[ "$sleep_seconds" =~ ^[0-9]+$ ]] && (( sleep_seconds > 0 )); then
      sleep "$sleep_seconds"
    fi
    if [[ "${FAKE_GIT_TOWN_PARTIAL_MUTATION:-0}" == 1 ]]; then
      git rev-parse refs/heads/agent/docs-directory-guides >"$state/before-partial-ref"
      git update-ref refs/heads/agent/docs-directory-guides refs/heads/main
    fi
    if [[ "${FAKE_GIT_TOWN_SYNC_FAIL:-0}" == 1 ]]; then
      exit 7
    fi
    ;;
  status)
    echo 'fixture status'
    ;;
  runlog)
    [[ -f "$state/runlog" ]] && cat "$state/runlog"
    ;;
  undo)
    : >"$state/undo-called"
    if [[ "${FAKE_GIT_TOWN_UNDO_RESTORE:-0}" == 1 && -f "$state/before-partial-ref" ]]; then
      git update-ref refs/heads/agent/docs-directory-guides "$(cat "$state/before-partial-ref")"
    fi
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
set -Eeuo pipefail
if [[ "${1:-}" == repo && "${2:-}" == view ]]; then
  if [[ "${FAKE_GH_WRONG_REPO:-0}" == 1 ]]; then
    echo 'attacker/wrong-repo'
  else
    echo 'ed3c/XT-Aegis'
  fi
  exit 0
fi
if [[ "${1:-}" == pr && "${2:-}" == view ]]; then
  pr=${3:?}
  case "$pr" in
    39) printf 'agent/docs-directory-guides\tmain\tOPEN\n' ;;
    40)
      if [[ "${FAKE_GH_BAD_BASE:-0}" == 1 ]]; then
        printf 'agent/docs-harness-contract\tagent/docs-directory-guides\tOPEN\n'
      else
        printf 'agent/docs-harness-contract\tmain\tOPEN\n'
      fi
      ;;
    41) printf 'agent/git-town-unattended-stack\tmain\tOPEN\n' ;;
    42) printf 'agent/docs-eval-first-templates\tmain\tOPEN\n' ;;
    *) printf 'unknown PR: %s\n' "$pr" >&2; exit 2 ;;
  esac
  exit 0
fi
printf 'unexpected gh invocation\n' >&2
exit 64
FAKE_GH
chmod +x "$BIN/gh"

export PATH="$BIN:$PATH"
export FAKE_GIT_TOWN_STATE="$FAKE_STATE"
export XT_AEGIS_GIT_TOWN_EXPECTED_ORIGIN_URL="$BARE"
export GIT_TOWN_BINARY_SHA256
GIT_TOWN_BINARY_SHA256="$(sha256sum "$BIN/git-town" | awk '{print $1}')"

# Establish explicit local parent metadata without rebasing or switching branches.
scripts/git-town/bootstrap.sh --apply >/dev/null
scripts/git-town/verify-license.sh >/dev/null
scripts/git-town/verify-stack.sh >/dev/null
scripts/git-town/sync-stack.sh --dry-run >/dev/null
scripts/git-town/sync-stack.sh >/dev/null

# An empty live manifest is an explicit no-active-stack state and must block.
# Commit the fixture-only transition so the clean-worktree precondition remains true.
cp scripts/git-town/stack.tsv "$TMP_ROOT/synthetic-stack.tsv"
printf '# branch\tparent\tissue\tpr\towned_paths\tevals\n' >scripts/git-town/stack.tsv
git add scripts/git-town/stack.tsv
git commit -qm 'fixture: disable active stack'
set +e
output="$(scripts/git-town/verify-stack.sh 2>&1)"
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -q 'stack manifest has no active rows' <<<"$output"
cp "$TMP_ROOT/synthetic-stack.tsv" scripts/git-town/stack.tsv
git add scripts/git-town/stack.tsv
git commit -qm 'fixture: restore synthetic stack'

# Unknown local branches must never be swept into sync --all.
git branch agent/undeclared-fixture
set +e
output="$(scripts/git-town/verify-stack.sh 2>&1)"
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -q 'undeclared local branch would be included' <<<"$output"
git branch -D agent/undeclared-fixture >/dev/null

# Missing manifest branches and incorrect parent metadata are terminal.
missing_ref="$(git rev-parse refs/heads/agent/docs-directory-guides)"
git branch -D agent/docs-directory-guides >/dev/null
set +e
output="$(scripts/git-town/verify-stack.sh 2>&1)"
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -q 'manifest branch is not checked out locally' <<<"$output"
git branch agent/docs-directory-guides "$missing_ref"
git branch --set-upstream-to=origin/agent/docs-directory-guides agent/docs-directory-guides >/dev/null

git config --local git-town-branch.agent/docs-harness-contract.parent agent/docs-directory-guides
set +e
output="$(scripts/git-town/verify-stack.sh 2>&1)"
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -q 'Git Town parent metadata mismatch' <<<"$output"
scripts/git-town/bootstrap.sh --apply >/dev/null

# Manifest PR lineage and repository identity are checked against GitHub metadata.
set +e
output="$(FAKE_GH_BAD_BASE=1 scripts/git-town/verify-stack.sh 2>&1)"
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -q 'PR #40 base mismatch' <<<"$output"
set +e
output="$(FAKE_GH_WRONG_REPO=1 scripts/git-town/verify-stack.sh 2>&1)"
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -q 'GitHub repository mismatch' <<<"$output"

# Version, binary identity, config identity, and release artifact mismatches fail closed.
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

cp .git-town.toml "$TMP_ROOT/git-town.toml"
printf '\n# tampered\n' >>.git-town.toml
git add .git-town.toml
git commit -qm 'tamper config for negative eval'
set +e
output="$(scripts/git-town/verify-stack.sh 2>&1)"
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -q 'Git Town config SHA-256 mismatch' <<<"$output"
cp "$TMP_ROOT/git-town.toml" .git-town.toml
git add .git-town.toml
git commit -qm 'restore config after negative eval'

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

# Preflight failures never call undo, preventing rollback of an unrelated older run.
rm -f -- "$FAKE_STATE/undo-called"
preflight_status="$TMP_ROOT/preflight.status"
preflight_log="$TMP_ROOT/preflight.log"
set +e
FAKE_GH_BAD_BASE=1 \
XT_AEGIS_GIT_TOWN_STATUS_FILE="$preflight_status" \
XT_AEGIS_GIT_TOWN_LOG_FILE="$preflight_log" \
scripts/git-town/sync-stack.sh --dry-run >/dev/null 2>&1
rc=$?
set -e
[[ $rc -ne 0 ]]
[[ ! -e "$FAKE_STATE/undo-called" ]]
grep -q '^PHASE=preflight_stack$' "$preflight_status"

# Repository lock contention blocks a second worker.
lock_dir="$(git rev-parse --absolute-git-dir)/xt-aegis-git-town.lock"
mkdir -- "$lock_dir"
printf '999999\n' >"$lock_dir/pid"
set +e
output="$(scripts/git-town/sync-stack.sh --dry-run 2>&1)"
rc=$?
set -e
[[ $rc -ne 0 ]]
grep -q 'another Git Town worker holds' <<<"$output"
rm -rf -- "$lock_dir"

# Semantic sync failure is non-zero and only calls undo for the current run.
rm -f -- "$FAKE_STATE/undo-called" "$FAKE_STATE/runlog"
failure_status="$TMP_ROOT/failure.status"
failure_log="$TMP_ROOT/failure.log"
set +e
FAKE_GIT_TOWN_SYNC_FAIL=1 \
XT_AEGIS_GIT_TOWN_STATUS_FILE="$failure_status" \
XT_AEGIS_GIT_TOWN_LOG_FILE="$failure_log" \
scripts/git-town/sync-stack.sh >/dev/null 2>&1
rc=$?
set -e
[[ $rc -eq 7 ]]
[[ -e "$FAKE_STATE/undo-called" ]]
grep -q '^RESULT=failure$' "$failure_status"
grep -q '^PHASE=failed_restored$' "$failure_status"

# A sibling-branch mutation that undo does not restore must never be called restored.
original_sibling_ref="$(git rev-parse refs/heads/agent/docs-directory-guides)"
partial_status="$TMP_ROOT/partial.status"
partial_log="$TMP_ROOT/partial.log"
set +e
FAKE_GIT_TOWN_SYNC_FAIL=1 \
FAKE_GIT_TOWN_PARTIAL_MUTATION=1 \
XT_AEGIS_GIT_TOWN_STATUS_FILE="$partial_status" \
XT_AEGIS_GIT_TOWN_LOG_FILE="$partial_log" \
scripts/git-town/sync-stack.sh >/dev/null 2>&1
rc=$?
set -e
[[ $rc -eq 7 ]]
grep -q '^PHASE=failed_recoverable$' "$partial_status"
git update-ref refs/heads/agent/docs-directory-guides "$original_sibling_ref"
rm -f -- "$FAKE_STATE/before-partial-ref"

# Timeouts terminate the current command, trigger bounded recovery, and remain non-zero.
timeout_status="$TMP_ROOT/timeout.status"
timeout_log="$TMP_ROOT/timeout.log"
set +e
FAKE_GIT_TOWN_SYNC_SLEEP=5 \
XT_AEGIS_GIT_TOWN_TIMEOUT_SECONDS=1 \
XT_AEGIS_GIT_TOWN_STATUS_FILE="$timeout_status" \
XT_AEGIS_GIT_TOWN_LOG_FILE="$timeout_log" \
scripts/git-town/sync-stack.sh >/dev/null 2>&1
rc=$?
set -e
[[ $rc -eq 124 ]]
grep -q '^RESULT=failure$' "$timeout_status"

# Log size is bounded even when a failed tool emits excessive output.
bounded_status="$TMP_ROOT/bounded.status"
bounded_log="$TMP_ROOT/bounded.log"
set +e
FAKE_GIT_TOWN_SYNC_FAIL=1 \
FAKE_GIT_TOWN_SPAM_BYTES=100000 \
XT_AEGIS_GIT_TOWN_MAX_LOG_BYTES=65536 \
XT_AEGIS_GIT_TOWN_STATUS_FILE="$bounded_status" \
XT_AEGIS_GIT_TOWN_LOG_FILE="$bounded_log" \
scripts/git-town/sync-stack.sh >/dev/null 2>&1
rc=$?
set -e
[[ $rc -eq 7 ]]
(( $(wc -c <"$bounded_log") <= 65536 ))

# Background dry-run is observable through PID, wrapper log, launch metadata, and child status output.
background_state="$TMP_ROOT/background-state"
launch_output="$(XT_AEGIS_GIT_TOWN_STATE_DIR="$background_state" scripts/git-town/sync-background.sh --dry-run)"
pid="$(sed -n 's/^started pid=\([0-9][0-9]*\).*/\1/p' <<<"$launch_output")"
wrapper_log="$(sed -n 's/.* log=\([^ ]*\) pid_file=.*/\1/p' <<<"$launch_output")"
[[ -n "$pid" && -n "$wrapper_log" ]]
for _ in $(seq 1 100); do
  grep -q 'dry-run complete:' "$wrapper_log" 2>/dev/null && break
  sleep 0.05
done
grep -q 'dry-run complete:' "$wrapper_log"
compgen -G "$background_state/*.launch.env" >/dev/null
compgen -G "$background_state/*.pid" >/dev/null

printf 'Git Town worker fixture passed\n'
