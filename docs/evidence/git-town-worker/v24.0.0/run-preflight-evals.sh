#!/usr/bin/env bash
# Run the Git Town worker evals that need no GitHub credentials, inside the pinned profile.
#
# EVAL-GIT-LIVE-10, -11, and -12 were recorded `not_run` because the earlier bundle read them as needing a
# GitHub repository. They do not. A bare repository on local disk is a real `origin`, and every guard those
# evals exercise fires before any `gh` call. What still needs GitHub is EVAL-05 through -09, which assert
# PR lineage and remote races against a real forge.
#
# Usage, from a checkout of this repository:
#   docker run --rm --platform linux/amd64 \
#     -v "$PWD:/src:ro" -v "$PWD/out:/out" debian:12-slim \
#     bash /src/docs/evidence/git-town-worker/v24.0.0/run-preflight-evals.sh
#
# Two properties make the difference between a result and a coincidence, and the first run of this script
# had neither:
#
#   1. `common.sh` derives REPO_ROOT from the *script's own* directory, not from the caller's. A fixture
#      that copies the scripts outside a repository makes every case die at `require_repo` with
#      "not inside a Git repository" — non-zero, and completely unrelated to the guard under test. The
#      fixture therefore commits the scripts inside the fixture repository.
#   2. A non-zero exit alone proves nothing. Each case names the message its guard must produce, and a case
#      that stops for a different reason is reported `failed`, not `passed`.
#
# Every case also asserts that `git town undo` was never invoked: a guard that refuses after calling undo
# has already touched the repository, which is the outcome these evals exist to exclude.

set -Eeuo pipefail
IFS=$'\n\t'

SRC=${SRC:-/src}
OUT=${OUT:-/out}
FIXTURE=${FIXTURE:-/fixture}
CANARY="xtaegis-canary-$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')"
WORK="$FIXTURE/work"
SCRIPTS="scripts/git-town"

mkdir -p "$OUT/logs" "$FIXTURE"
RESULTS="$OUT/preflight-results.jsonl"
: >"$RESULTS"
ARGV_LOG="$OUT/git-town-argv.log"
: >"$ARGV_LOG"

log() { printf '%s\n' "$*" >&2; }

count_undo() {
  local n
  n="$(grep -c '^undo' "$ARGV_LOG" 2>/dev/null)" || n=0
  printf '%s' "${n:-0}"
}

# ---------------------------------------------------------------------------- toolchain

install_toolchain() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get -qq update >/dev/null
  apt-get -qq install -y --no-install-recommends \
    ca-certificates curl git jq shellcheck coreutils procps >/dev/null

  # shellcheck disable=SC1090,SC1091  # $SRC is a runtime mount point; the path cannot be resolved statically
  source "$SRC/scripts/git-town/git-town.lock"
  local url="https://github.com/git-town/git-town/releases/download/${GIT_TOWN_UPSTREAM_TAG}/${GIT_TOWN_LINUX_AMD64_PACKAGE}"
  curl -sfSL -o /tmp/git-town.deb "$url"
  local observed
  observed="$(sha256sum /tmp/git-town.deb | awk '{print $1}')"
  [[ "$observed" == "$GIT_TOWN_LINUX_AMD64_PACKAGE_SHA256" ]] || {
    log "FATAL: package digest mismatch: expected $GIT_TOWN_LINUX_AMD64_PACKAGE_SHA256 observed $observed"
    exit 1
  }
  dpkg -i /tmp/git-town.deb >/dev/null

  # A shim ahead of the real binary records every argv. `git town <verb>` dispatches through git to a
  # `git-town` executable on PATH, so this sees both spellings.
  mkdir -p /usr/local/bin
  cat >/usr/local/bin/git-town <<SHIM
#!/usr/bin/env bash
printf '%s\n' "\$*" >>"$ARGV_LOG"
exec /usr/bin/git-town "\$@"
SHIM
  chmod +x /usr/local/bin/git-town
  hash -r
}

# ---------------------------------------------------------------------------- fixture

write_manifest() {
  printf 'agent/child-a\tmain\t1\t1\tdocs/\tEVAL-X\n' >"$WORK/$SCRIPTS/stack.tsv"
  printf 'agent/child-b\tagent/child-a\t2\t2\tdocs/\tEVAL-X\n' >>"$WORK/$SCRIPTS/stack.tsv"
}

build_fixture() {
  git config --global user.email worker@example.invalid
  git config --global user.name "XT-Aegis Worker Fixture"
  git config --global init.defaultBranch main
  git config --global advice.detachedHead false
  git config --global --add safe.directory '*'

  rm -rf -- "${FIXTURE:?}/remote.git" "${FIXTURE:?}/work"
  git init --quiet --bare "$FIXTURE/remote.git"
  git init --quiet "$WORK"

  # The scripts live inside the fixture repository, because that is where common.sh looks for its root.
  mkdir -p "$WORK/$SCRIPTS"
  cp "$SRC"/scripts/git-town/*.sh "$SRC"/scripts/git-town/git-town.lock "$WORK/$SCRIPTS/"
  cp "$SRC/.git-town.toml" "$WORK/.git-town.toml"
  mkdir -p "$WORK/third_party/git-town"
  cp "$SRC/third_party/git-town/LICENSE" "$WORK/third_party/git-town/LICENSE"
  write_manifest
  printf 'base\n' >"$WORK/file.txt"

  (
    cd "$WORK"
    git add -A
    git commit --quiet -m "fixture base"
    git remote add origin "$FIXTURE/remote.git"
    git push --quiet -u origin main
    git switch --quiet -c agent/child-a
    printf 'a\n' >>file.txt
    git commit --quiet -am "child a"
    git push --quiet -u origin agent/child-a
    git switch --quiet -c agent/child-b
    printf 'b\n' >>file.txt
    git commit --quiet -am "child b"
    git push --quiet -u origin agent/child-b
    git switch --quiet main
  )
  BASELINE="$(cd "$WORK" && git rev-parse HEAD)"
  export BASELINE
}

reset_fixture() {
  (
    cd "$WORK"
    git rebase --quit >/dev/null 2>&1 || true
    rm -f -- .git/MERGE_HEAD .git/CHERRY_PICK_HEAD .git/REVERT_HEAD .git/BISECT_LOG
    rm -rf -- .git/rebase-merge .git/rebase-apply .git/xt-aegis-git-town.lock
    git switch --quiet main 2>/dev/null || true
    git reset --quiet --hard "$BASELINE"
    git clean -qfdx
    git remote set-url origin "$FIXTURE/remote.git"
  )
}

# ---------------------------------------------------------------------------- case runner

record() {
  local id=$1 case_name=$2 status=$3 exit_code=$4 argv=$5 detail=$6 evidence=$7
  jq -nc --arg id "$id" --arg case "$case_name" --arg status "$status" \
    --argjson exit_code "$exit_code" --arg argv "$argv" --arg detail "$detail" \
    --arg evidence "$evidence" \
    '{eval:$id, case:$case, status:$status, exit_code:$exit_code, argv:$argv,
      detail:$detail, evidence:$evidence}' >>"$RESULTS"
  printf '%-22s %-24s %-8s exit=%-4s %s\n' "$id" "$case_name" "$status" "$exit_code" "$detail"
}

# guard_case <eval-id> <case> <expected message substring> <command...>
guard_case() {
  local id=$1 case_name=$2 expected=$3
  shift 3
  local logfile="$OUT/logs/${case_name}.log"
  local undo_before undo_after
  undo_before="$(count_undo)"

  set +e
  ( cd "$WORK" && "$@" ) >"$logfile" 2>&1
  local rc=$?
  set -e
  undo_after="$(count_undo)"

  local status="passed"
  local detail="refused with the expected reason"
  if (( rc == 0 )); then
    status="failed"
    detail="guard did not refuse: exited 0"
  elif ! grep -qF -- "$expected" "$logfile"; then
    status="failed"
    detail="stopped for a different reason; expected to contain: ${expected}"
  elif [[ "$undo_before" != "$undo_after" ]]; then
    status="failed"
    detail="refused but invoked 'git town undo' first, so the repository was already touched"
  fi
  record "$id" "$case_name" "$status" "$rc" "$*" "$detail" "logs/${case_name}.log"
}

commit_all() { ( cd "$WORK" && git add -A && git commit --quiet -m "fixture case setup" ); }

# ---------------------------------------------------------------------------- EVAL-11

eval_11_preflight_isolation() {
  local W="$WORK/$SCRIPTS"

  # A control: with the fixture origin approved, the same command must succeed. Without it, every
  # "refused" below could be the guard chain refusing for an unrelated, permanent reason.
  reset_fixture
  local control="$OUT/logs/control-clean-bootstrap.log"
  set +e
  ( cd "$WORK" && XT_AEGIS_GIT_TOWN_EXPECTED_ORIGIN_URL="$FIXTURE/remote.git" bash "$W/bootstrap.sh" ) \
    >"$control" 2>&1
  local rc=$?
  set -e
  if (( rc == 0 )); then
    record EVAL-GIT-LIVE-11 control-clean-bootstrap passed 0 "bootstrap.sh" \
      "the clean fixture is accepted, so a refusal below is the named guard and not a broken fixture" \
      "logs/control-clean-bootstrap.log"
  else
    record EVAL-GIT-LIVE-11 control-clean-bootstrap failed "$rc" "bootstrap.sh" \
      "the clean fixture was refused; every other case in this eval is uninterpretable" \
      "logs/control-clean-bootstrap.log"
  fi

  export XT_AEGIS_GIT_TOWN_EXPECTED_ORIGIN_URL="$FIXTURE/remote.git"

  reset_fixture
  ( cd "$WORK" && git remote set-url origin "$FIXTURE/somewhere-else.git" )
  guard_case EVAL-GIT-LIVE-11 wrong-origin "origin mismatch" bash "$W/bootstrap.sh"

  reset_fixture
  printf 'dirty\n' >"$WORK/untracked.txt"
  guard_case EVAL-GIT-LIVE-11 dirty-worktree "working tree must be clean" bash "$W/bootstrap.sh"

  reset_fixture
  : >"$WORK/.git/MERGE_HEAD"
  guard_case EVAL-GIT-LIVE-11 suspended-operation "already suspended" bash "$W/bootstrap.sh"

  reset_fixture
  printf 'agent/does-not-exist\tmain\t9\t9\tdocs/\tEVAL-X\n' >"$W/stack.tsv"
  commit_all
  guard_case EVAL-GIT-LIVE-11 missing-local-branch "local branch required before bootstrap" \
    bash "$W/bootstrap.sh"

  reset_fixture
  printf 'agent/child-a\tmain\n' >"$W/stack.tsv"
  commit_all
  guard_case EVAL-GIT-LIVE-11 malformed-manifest-row "invalid stack manifest row" bash "$W/bootstrap.sh"

  reset_fixture
  # The worker takes the lock as a directory inside the git dir; a held lock must not be stealable.
  mkdir -p "$WORK/.git/xt-aegis-git-town.lock"
  printf '4242\n' >"$WORK/.git/xt-aegis-git-town.lock/pid"
  guard_case EVAL-GIT-LIVE-11 lock-contention "another Git Town worker holds" \
    bash "$W/bootstrap.sh" --apply

  reset_fixture
  sed -i 's/^GIT_TOWN_LINUX_AMD64_PACKAGE_SHA256=.*/GIT_TOWN_LINUX_AMD64_PACKAGE_SHA256=0000000000000000000000000000000000000000000000000000000000000000/' \
    "$W/git-town.lock"
  commit_all
  cp /tmp/git-town.deb "$WORK/git-town_linux_intel_64.deb"
  guard_case EVAL-GIT-LIVE-11 checksum-mismatch "SHA-256 mismatch" \
    bash "$W/verify-release-artifact.sh" "$WORK/git-town_linux_intel_64.deb"

  reset_fixture
  unset XT_AEGIS_GIT_TOWN_EXPECTED_ORIGIN_URL
}

# ---------------------------------------------------------------------------- EVAL-WORKER-05

eval_worker_05_contract_fixture() {
  # The no-network contract fixture, run against this checkout. It builds its own disposable repository
  # and a stub `git-town`, so it covers the flow; the accepting side of the real binary pin is covered by
  # EVAL-GIT-LIVE-02 below, with the genuine package.
  local logfile="$OUT/logs/test-fixture.log"
  local root="$FIXTURE/fixture-source"
  mkdir -p "$root"
  cp -R "$SRC"/scripts "$SRC"/third_party "$root/"
  cp "$SRC/.git-town.toml" "$root/"
  set +e
  ( cd "$root" && XT_AEGIS_FIXTURE_SOURCE_ROOT="$root" bash scripts/git-town/test-fixture.sh ) \
    >"$logfile" 2>&1
  local rc=$?
  set -e
  local status=passed detail="the contract fixture passed unchanged"
  if (( rc != 0 )); then
    status=failed
    detail="the contract fixture failed; see the log"
  fi
  record EVAL-WORKER-05 contract-fixture "$status" "$rc" "scripts/git-town/test-fixture.sh" "$detail" \
    "logs/test-fixture.log"
}

# ---------------------------------------------------------------------------- EVAL-02

eval_02_binary_identity() {
  reset_fixture
  local W="$WORK/$SCRIPTS"
  # Without /usr/local/bin the argv-recording shim is out of the way and `git-town` resolves to the real
  # installed binary.
  local clean_path=/usr/bin:/bin:/usr/sbin:/sbin

  local logfile="$OUT/logs/binary-pin-accepts.log"
  set +e
  ( cd "$WORK" && PATH="$clean_path" bash "$W/verify-license.sh" ) >"$logfile" 2>&1
  local rc=$?
  set -e
  if (( rc == 0 )) && grep -q "binary_sha256=" "$logfile"; then
    record EVAL-GIT-LIVE-02 binary-pin-accepts-real passed "$rc" "verify-license.sh" \
      "the genuine installed binary matches the digest pinned in git-town.lock" \
      "logs/binary-pin-accepts.log"
  else
    record EVAL-GIT-LIVE-02 binary-pin-accepts-real failed "$rc" "verify-license.sh" \
      "the real binary was refused; the pinned digest does not describe what the package installs" \
      "logs/binary-pin-accepts.log"
  fi

  # A wrapper earlier on PATH is a different binary. The argv-recording shim this script installs is
  # exactly that, so it doubles as the attack: `command -v` must resolve to it and the check must refuse.
  guard_case EVAL-GIT-LIVE-02 binary-pin-rejects-wrapper "installed git-town binary SHA-256 mismatch" \
    bash "$W/verify-license.sh"

  # And the expectation itself must be load-bearing: corrupt the pinned value and the same run must fail.
  reset_fixture
  sed -i 's/^GIT_TOWN_LINUX_AMD64_BINARY_SHA256=.*/GIT_TOWN_LINUX_AMD64_BINARY_SHA256="0000000000000000000000000000000000000000000000000000000000000000"/' \
    "$W/git-town.lock"
  commit_all
  local tampered="$OUT/logs/binary-pin-tampered.log"
  set +e
  ( cd "$WORK" && PATH="$clean_path" bash "$W/verify-license.sh" ) >"$tampered" 2>&1
  local trc=$?
  set -e
  if (( trc != 0 )) && grep -q "installed git-town binary SHA-256 mismatch" "$tampered"; then
    record EVAL-GIT-LIVE-02 binary-pin-rejects-tampered-lock passed "$trc" "verify-license.sh" \
      "a corrupted pinned digest refuses the genuine binary, so the comparison is real" \
      "logs/binary-pin-tampered.log"
  else
    record EVAL-GIT-LIVE-02 binary-pin-rejects-tampered-lock failed "$trc" "verify-license.sh" \
      "a corrupted pinned digest did not refuse, so the comparison proves nothing" \
      "logs/binary-pin-tampered.log"
  fi
  reset_fixture
}

# ---------------------------------------------------------------------------- EVAL-10

eval_10_timeout_and_bounds() {
  reset_fixture
  local W="$WORK/$SCRIPTS"

  # Two variants, because they answer different questions and only one of them is about the worker.
  #
  #   attached: a grandchild in the worker's own process group, which is what `git town sync` spawns.
  #             The deadline must kill it.
  #   detached: a grandchild that called `setsid` to leave the group. `timeout` signals the group, so it
  #             cannot reach one. Reported as a stated limit of the contract, not as a worker defect --
  #             but reported, because "the deadline terminates the process tree" is what EVAL-10 claims.
  local variant
  for variant in attached detached; do
    local logfile="$OUT/logs/timeout-${variant}.log"
    local pidfile="$FIXTURE/grandchild-${variant}.pid"
    rm -f -- "$pidfile"
    local inner='bash -c "sleep 120 & echo \$! >'"$pidfile"'; wait"'
    [[ "$variant" == "detached" ]] && inner="setsid $inner"
    set +e
    timeout --signal=TERM --kill-after=5s 3s bash -c "$inner" >"$logfile" 2>&1
    local rc=$?
    set -e
    sleep 1
    local grandchild alive=absent
    grandchild="$(cat "$pidfile" 2>/dev/null || true)"
    if [[ -n "$grandchild" ]] && kill -0 "$grandchild" 2>/dev/null; then
      alive=alive
      kill -9 "$grandchild" 2>/dev/null || true
    fi
    local status detail
    if (( rc == 0 )); then
      status=failed; detail="the hanging command exited 0"
    elif [[ "$variant" == "attached" && "$alive" == "alive" ]]; then
      status=failed; detail="deadline fired (exit ${rc}) but the in-group grandchild survived it"
    elif [[ "$variant" == "detached" && "$alive" == "alive" ]]; then
      status=failed
      detail="deadline fired (exit ${rc}); a setsid grandchild survived, which timeout cannot reach"
    else
      status=passed; detail="deadline fired (exit ${rc}); grandchild ${alive}"
    fi
    record EVAL-GIT-LIVE-10 "timeout-${variant}-grandchild" "$status" "$rc" \
      "timeout --signal=TERM --kill-after=5s 3s bash -c '${variant} sleep 120'" "$detail" \
      "logs/timeout-${variant}.log"
  done

  # Whether the detached case is reachable at all with the pinned toolchain is an empirical question, and
  # the answer decides how much the failure above means. Observed, not asserted.
  #
  # A process that leaves the session and then exits is harmless: the deadline exists to stop work that
  # hangs. The hazard is one that leaves the session and *survives*, so the observation looks for
  # survivors after the command has already returned.
  observe_strays() {
    local label=$1
    shift
    local own_sid orc
    own_sid="$(ps -o sid= -p $$ | tr -d ' ')"
    ps -eo pid= | tr -d ' ' | sort >"$OUT/logs/pids-before-${label}.txt"
    set +e
    "$@" >"$OUT/logs/session-${label}.log" 2>&1
    orc=$?
    set -e
    sleep 1
    ps -eo pid=,sid=,args= >"$OUT/logs/ps-after-${label}.txt"
    awk -v own="$own_sid" 'NR==FNR { seen[$1]=1; next }
                           { if (!($1 in seen) && $2 != own) print }' \
      "$OUT/logs/pids-before-${label}.txt" "$OUT/logs/ps-after-${label}.txt" \
      >"$OUT/logs/strays-${label}.txt"
    STRAY_COUNT="$(wc -l <"$OUT/logs/strays-${label}.txt" | tr -d ' ')"
    STRAY_RC="$orc"
  }

  # Control first. An observer that cannot see an escape is no evidence that nothing escaped.
  #
  # The escapee has to be backgrounded. A foreground `setsid sleep 60` runs to completion before the
  # observation happens, so the observer correctly reports nothing and the control silently becomes
  # vacuous -- which is exactly the shape of a check that always passes.
  observe_strays control bash -c 'setsid sleep 60 >/dev/null 2>&1 &'
  local control_strays=$STRAY_COUNT
  local stray_pid
  while read -r stray_pid _; do
    [[ -n "$stray_pid" ]] && kill -9 "$stray_pid" 2>/dev/null
  done <"$OUT/logs/strays-control.txt" || true
  if (( control_strays >= 1 )); then
    record EVAL-GIT-LIVE-10 session-observer-control passed 0 "setsid sleep 60" \
      "the observer saw ${control_strays} surviving process(es) outside the session, so a zero below means something" \
      "logs/strays-control.txt"
  else
    record EVAL-GIT-LIVE-10 session-observer-control failed 0 "setsid sleep 60" \
      "the observer saw no escape from a deliberate setsid, so it cannot support any claim below" \
      "logs/strays-control.txt"
  fi

  # The real worker path reachable without a forge: bootstrap.sh drives git and the pinned git-town binary.
  reset_fixture
  observe_strays toolchain env "XT_AEGIS_GIT_TOWN_EXPECTED_ORIGIN_URL=$FIXTURE/remote.git" \
    bash -c "cd '$WORK' && bash '$W/bootstrap.sh' --apply"
  local toolchain_strays=$STRAY_COUNT
  if (( control_strays >= 1 )) && (( toolchain_strays == 0 )); then
    record EVAL-GIT-LIVE-10 toolchain-stays-in-session passed "$STRAY_RC" \
      "bootstrap.sh --apply, observed for surviving processes outside the worker's session" \
      "the pinned toolchain left no surviving process outside the session, so a process-group kill reaches everything it started" \
      "logs/strays-toolchain.txt"
  else
    record EVAL-GIT-LIVE-10 toolchain-stays-in-session failed "$STRAY_RC" \
      "bootstrap.sh --apply, observed for surviving processes outside the worker's session" \
      "observed ${toolchain_strays} surviving process(es) outside the session; the control saw ${control_strays}" \
      "logs/strays-toolchain.txt"
  fi

  # The bound is applied by `bound_file`, so exercise that function rather than a copy of its rule.
  local flood="$OUT/logs/output-flood.log"
  head -c 4000000 /dev/zero | tr '\0' 'x' >"$flood"
  local before after
  before="$(wc -c <"$flood")"
  (
    cd "$WORK"
    export XT_AEGIS_GIT_TOWN_MAX_LOG_BYTES=65536
    # shellcheck disable=SC1090,SC1091  # $W points into the runtime fixture, not into this checkout
    source "$W/common.sh"
    bound_file "$flood"
  )
  after="$(wc -c <"$flood")"
  status=passed
  detail="bounded from ${before} to ${after} bytes against a 65536 limit"
  if (( after > 65536 )); then
    status=failed
    detail="NOT bounded: ${before} -> ${after} bytes"
  fi
  record EVAL-GIT-LIVE-10 output-bound "$status" 0 "bound_file from common.sh" "$detail" \
    "logs/output-flood.log"
  printf '[truncated in the committed evidence; only the byte count mattered]\n' >"$flood"
}

# ---------------------------------------------------------------------------- EVAL-12

eval_12_secret_canaries() {
  reset_fixture
  local W="$WORK/$SCRIPTS"
  local logfile="$OUT/logs/canary-run.log"

  set +e
  (
    cd "$WORK"
    export XT_AEGIS_GIT_TOWN_EXPECTED_ORIGIN_URL="$FIXTURE/remote.git"
    export GH_TOKEN="$CANARY" GITHUB_TOKEN="$CANARY"
    bash "$W/bootstrap.sh" --apply
  ) >"$logfile" 2>&1
  local rc=$?
  set -e

  local leaks=0 where=""
  if grep -rqF "$CANARY" "$WORK" 2>/dev/null; then
    leaks=$((leaks + 1)); where="${where}repository-files "
  fi
  if grep -rqF "$CANARY" "$OUT/logs" 2>/dev/null; then
    leaks=$((leaks + 1)); where="${where}logs "
  fi
  # Snapshot first, then search the file. Piping `ps` straight into `grep` lets the grep process — whose
  # own argv holds the canary — appear in the very output being searched, so the check reports itself.
  ps -eo args >"$OUT/logs/process-args.txt" 2>/dev/null || true
  if grep -qF "$CANARY" "$OUT/logs/process-args.txt"; then
    leaks=$((leaks + 1)); where="${where}process-args "
  fi
  if grep -qF "$CANARY" "$ARGV_LOG" 2>/dev/null; then
    leaks=$((leaks + 1)); where="${where}git-town-argv "
  fi

  local status=passed
  local detail="run exited ${rc}; no canary in repository files, logs, process arguments, or git-town argv"
  if (( rc != 0 )); then
    status=failed
    detail="the canary run did not complete (exit ${rc}), so absence of the canary proves nothing"
  elif (( leaks > 0 )); then
    status=failed
    detail="canary leaked into: ${where}"
  fi
  record EVAL-GIT-LIVE-12 credential-canary "$status" "$rc" \
    "bootstrap.sh --apply with GH_TOKEN and GITHUB_TOKEN set to a canary" "$detail" \
    "logs/canary-run.log"
}

# ---------------------------------------------------------------------------- environment

write_environment() {
  jq -n \
    --arg os "$(. /etc/os-release && printf '%s %s' "$NAME" "$VERSION")" \
    --arg debian "$(cat /etc/debian_version)" \
    --arg arch "$(uname -m)" \
    --arg kernel "$(uname -sr)" \
    --arg bash "$(bash --version | head -1)" \
    --arg git "$(git --version)" \
    --arg git_town "$(/usr/bin/git-town --version 2>&1 | head -1)" \
    --arg shellcheck "$(shellcheck --version | awk '/^version:/{print $2}')" \
    --arg jq "$(jq --version)" \
    --arg timeout "$(timeout --version | head -1)" \
    --arg note "Emulated x86_64 under Docker on an arm64 developer host. Recorded because it is not the deployment host and is not the immutable Worker image." \
    '{os:$os, debian_version:$debian, architecture:$arch, kernel:$kernel, bash:$bash, git:$git,
      git_town:$git_town, shellcheck:$shellcheck, jq:$jq, timeout:$timeout, note:$note}' \
    >"$OUT/preflight-environment.json"
}

# ---------------------------------------------------------------------------- main

# ---------------------------------------------------------------------------- EVAL-WORKER-04

eval_worker_04_shell_analysis() {
  # The committed invocation, not a remembered one. Every script here carries a `# shellcheck source=`
  # directive, and those directives are inert without `-x`; checking the files one at a time also hides
  # cross-file use. Run that way this directory reports fifteen findings, seven of them SC1091 "not
  # following" -- the linter reporting that it was invoked without permission to resolve what the scripts
  # already declare.
  local logfile="$OUT/logs/shellcheck.log"
  set +e
  bash "$SRC/scripts/git-town/lint.sh" >"$logfile" 2>&1
  local rc=$?
  set -e

  local selftest_log="$OUT/logs/shellcheck-selftest.log"
  set +e
  bash "$SRC/scripts/git-town/lint.sh" --selftest >"$selftest_log" 2>&1
  local src=$?
  set -e

  local status detail
  if (( rc == 0 && src == 0 )); then
    status=passed
    detail="no findings, and the checker's selftest proves it still rejects a planted defect"
  elif (( src != 0 )); then
    status=failed
    detail="the checker's selftest failed, so a clean result would not be evidence"
  else
    status=failed
    detail="shellcheck reported findings; see the log"
  fi
  record EVAL-WORKER-04 shellcheck-clean "$status" "$rc" "scripts/git-town/lint.sh" "$detail" \
    "logs/shellcheck.log"
}

install_toolchain
write_environment
eval_worker_04_shell_analysis
build_fixture
eval_02_binary_identity
eval_worker_05_contract_fixture
eval_11_preflight_isolation
eval_10_timeout_and_bounds
eval_12_secret_canaries

log ""
jq -s '{total: length,
        passed: [.[]|select(.status=="passed")]|length,
        failed: [.[]|select(.status=="failed")]|length}' "$RESULTS" >&2
# A failed case is a finding, not a reason to hide the run: the caller reads the JSON either way.
exit 0
