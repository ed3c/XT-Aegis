# Git Town v24.0.0 — partial acceptance evidence

**This does not authorize an unattended Worker.** Issue #44's deployment gate stays closed. Ten of the
seventeen evals in #43 and #44 have now run; one failed; seven still cannot run here.

## What this is

A developer-host `linux/amd64` container that installed the exact pinned Git Town release and ran the
repository's own verification scripts against it. It answers the questions that need only the real
toolchain and the committed contract, and it answers none of the questions that need a remote, real pull
requests, or credentials.

## Result

| Eval | Status | What it establishes |
|---|---|---|
| `EVAL-GIT-LIVE-01` release package identity | passed | the release `checksums.txt`, its entry for the package, and the downloaded package all match the pinned lock; DEB reports `24.0.0` / `amd64` |
| `EVAL-GIT-LIVE-02` installed identity | passed | the installed binary reports `24.0.0`, the copied MIT text matches, and the binary digest is now pinned in the lock — accepted for the genuine binary, refused for a `PATH` wrapper and for a corrupted pin |
| `EVAL-GIT-LIVE-03` shell analysis | passed | all 15 ShellCheck findings preserved with the tool version |
| `EVAL-GIT-LIVE-04` pinned config parse | passed | the real binary parsed `.git-town.toml` and reported the intended sync strategies and push behavior |
| `EVAL-WORKER-05` committed fixture | passed | `test-fixture.sh` passed unchanged inside the image |
| `EVAL-WORKER-01` immutable environment | **failed** | the image is a general base with tools installed at run time, not a purpose-built pinned Worker image |
| `EVAL-WORKER-04` shell analysis passes | passed | `shellcheck -x` over the directory in one call reports nothing, and the checker's selftest proves it still rejects a planted defect |
| `EVAL-GIT-LIVE-11` preflight isolation | passed | seven refusals, each asserting its own guard message, plus a clean control |
| `EVAL-GIT-LIVE-12` secret canaries | passed | an injected credential appears in no repository file, log, process argument, or `git town` argv |
| `EVAL-GIT-LIVE-10` timeout and output bounds | passed, contract narrowed | the deadline kills the worker's process group and the log bound holds; a `setsid` escape is retained as a stated residual risk |
| five remaining live evals | not run | `EVAL-GIT-LIVE-05` through `-09` need real pull requests, PR lineage, and a remote race |
| `EVAL-WORKER-06`, `-07` | not run | worker credential mechanism and immutable image |

`eval-results.json` records the argv, exit code, and evidence path for each.

## The one remaining failure, stated plainly

**`EVAL-WORKER-01`.** The environment is fully recorded and reproducible, but #43 requires an immutable
Worker image built without package-channel installation. This container installs `git`, `curl`, and
`shellcheck` from Debian at run time, so it cannot satisfy that eval however complete its manifest is.

## `EVAL-WORKER-04`: the invocation was wrong, not the scripts

The earlier bundle recorded this as failed with 15 findings. Counting them again with `--format=gcc`, one
line per finding, gives a different breakdown than the first pass reported: **7** `SC1091`, 4 `SC2034`,
3 `SC2015`, 1 `SC2153`. The first count was inflated because ShellCheck prints each code twice — once
inline and once in the wiki footer — and the tally was taken with `grep -c`.

Ten of those fifteen were manufactured by how the linter was run. Every script here carries a
`# shellcheck source=` directive, and **those directives do nothing without `-x`**: ShellCheck refuses to
follow a source it was not told to follow. Checking the files one at a time also hides cross-file use, so a
variable defined in `common.sh` and read by `bootstrap.sh` reads as unused. Running `shellcheck -x` once
over the whole directory leaves **5**.

Those five were real, and all five are now fixed in `scripts/git-town/common.sh`:

| Finding | What it was pointing at |
|---|---|
| `SC2034` `MANIFEST_FILE` unused | consumed by the sourcing entry points, which ShellCheck cannot see while analysing this file alone — now a targeted disable with the reason |
| `SC2015` ×3, `A && B \|\| C` | correct as written, but the pattern that hides a bug when `B` fails after `A` succeeded — rewritten as an explicit negated condition |
| `SC2153` `LOG_FILE` | a genuine fragility: `common.sh` read a variable only `sync-stack.sh` assigned. Any future entry point that forgot would crash under `set -u` with an unhelpful message. `LOG_FILE` is now declared in `common.sh` and asserted in `run_logged`, so forgetting is caught by name at the one shared exit |

The invocation is now committed as `scripts/git-town/lint.sh` rather than remembered, wired into
`make lint`, and it carries `--selftest`: it plants an unquoted expansion in a copy and requires the check
to fail. A linter that cannot go red is not evidence.

## The three evals added by the second run

The earlier bundle recorded `EVAL-GIT-LIVE-10`, `-11`, and `-12` as `not_run` on the reading that they need
a GitHub repository. They do not. A bare repository on local disk is a real `origin`, and every guard those
evals exercise fires before any `gh` call. `run-preflight-evals.sh` runs them in the same pinned profile.

**`EVAL-GIT-LIVE-11` — seven refusals, each for its own reason.** Wrong origin, dirty worktree, suspended
Git operation, a manifest naming a branch that does not exist, a malformed manifest row, a held repository
lock, and a tampered artifact checksum. Every case asserts three things: a non-zero exit, the specific
message that guard produces, and that `git town undo` was never invoked — a guard that refuses *after*
calling undo has already touched the repository.

The first attempt at this eval produced seven false passes and is worth recording, because the failure mode
is generic. `common.sh` derives `REPO_ROOT` from the **script's own** directory, not from the caller's, so a
fixture that copied the scripts outside a repository made every case die at `require_repo` with "not inside
a Git repository" — non-zero, and unrelated to the guard under test. Two changes fixed it: the fixture now
commits the scripts inside the fixture repository, and every case names the message it expects. A
`control-clean-bootstrap` case runs the same command on an untouched fixture and must succeed, so a
refusal below it is the named guard rather than a broken fixture.

**`EVAL-GIT-LIVE-12` — the canary is clean, and the check no longer sees itself.** A synthetic credential
passed through `GH_TOKEN` and `GITHUB_TOKEN` appears in no repository file, no log, no process argument,
and no recorded `git town` argv. The first run reported a leak into process arguments; that was the check
detecting its own `grep`, whose argv held the canary, because `ps` was piped straight into it. The
snapshot is now taken to a file first.

**`EVAL-GIT-LIVE-10` — the contract was narrowed, deliberately, and the gap is still measured.**
`bound_file` truncated a 4,000,000 byte log to 65,495 bytes against a 65,536 limit, exercising the
repository's own function rather than a restatement of its rule. The deadline terminated a grandchild in
the worker's process group.

A grandchild that calls `setsid` survives it, because `timeout` signals the process group and a new session
is no longer in it. **No `timeout`-based implementation can pass the requirement as it was written**, so the
requirement was unsatisfiable rather than unmet. #44 now reads "process group", and the escape is recorded
as a residual risk instead of deleted.

That narrowing rests on an observation, not on an assumption that the toolchain behaves:

- `session-observer-control` backgrounds a deliberate `setsid sleep 60` and requires the observer to see a
  surviving process outside the session. It saw one.
- `toolchain-stays-in-session` then runs a real `bootstrap.sh --apply` and requires **zero** survivors
  outside the worker's session. It saw zero.

The control earned its place on the first attempt, when it failed. A *foreground* `setsid sleep 60` runs to
completion before the observation happens, so the observer correctly reported nothing — and the check would
have passed vacuously while proving nothing. Backgrounding the escapee fixed it. Both cases stay in the
suite, and `timeout-detached-grandchild` still runs and still reports the escape.

Closing the residual risk needs a pid namespace or a cgroup kill, not a different `timeout` invocation.

## The gap this run exposed, now closed

An earlier version of this document said `verify-license.sh` "accepts the run when the value is unset".
**That was wrong** — it always died with `GIT_TOWN_BINARY_SHA256 must contain the approved worker-image
checksum`. The real gap was narrower and different: the expectation was read from the **environment**, so
whoever started the worker declared what the binary should hash to. The run verified itself against its own
claim.

`GIT_TOWN_LINUX_AMD64_BINARY_SHA256` is now pinned in `git-town.lock` and the environment is no longer
consulted. The value is a **derived constant of the already-pinned package**, not an observation of one
host — three independent arrivals agree:

| Arrival | Result |
|---|---|
| `dpkg-deb -x` on the digest-verified package | `dbaba381…` |
| `command -v git-town` after `dpkg -i` | `dbaba381…` |
| the path `dpkg -L git-town` reports it owns | `dbaba381…` |

Three cases prove the pin bites, in both directions:

- **accepts the genuine binary** — `verify-license.sh` exits 0 and prints the full identity line.
- **refuses a `PATH` wrapper** — this suite's own argv-recording shim sits earlier on `PATH`, so it doubles
  as the attack. `command -v` resolves to it and the check refuses, naming both digests and the resolved
  path. That is deliberate: the property worth checking is the identity of the binary the worker will
  actually run, not of a file the package happens to own.
- **refuses a corrupted pin** — with the lock's value zeroed, the genuine binary is refused, so the
  comparison is real rather than a constant `true`.

The same change removed a self-certification in `test-fixture.sh`. It hashed its own stub `git-town` at run
time and fed the result back in as the approved value, so the accepting case could never fail — it proved
that `sha256sum` is deterministic. The stub's digest is now a **committed constant**, verified two ways: a
corrupted constant is rejected, and a single changed byte inside the stub is rejected with the corrected
value printed.

## Reproduction

### The preflight evals (`-10`, `-11`, `-12`)

```bash
mkdir -p out
docker run --rm --platform linux/amd64 \
  -v "$(git rev-parse --show-toplevel):/src:ro" -v "$PWD/out:/out" debian:12-slim \
  bash /src/docs/evidence/git-town-worker/v24.0.0/run-preflight-evals.sh
```

Writes `out/preflight-results.jsonl`, `out/preflight-environment.json`, and one log per case. The script
exits 0 whether or not a case failed: the caller reads the JSON, so a failing guard is a finding rather
than something that disappears into an exit code.

### The identity and contract evals (`-01` through `-04`)

Requires Docker and network access to the GitHub release assets. The whole run takes a few minutes, most of
it emulation overhead on an arm64 host.

```bash
docker run --rm --platform linux/amd64 \
  -v "$(git rev-parse --show-toplevel):/repo" \
  debian:bookworm-slim bash -c '
    set -Eeuo pipefail
    apt-get -qq update && apt-get -qq install -y curl ca-certificates git shellcheck coreutils
    curl -sSL --fail -o /tmp/git-town_linux_intel_64.deb \
      https://github.com/git-town/git-town/releases/download/v24.0.0/git-town_linux_intel_64.deb
    cd /repo
    git config --global --add safe.directory /repo
    bash scripts/git-town/verify-release-artifact.sh /tmp/git-town_linux_intel_64.deb
    dpkg -i /tmp/git-town_linux_intel_64.deb
      bash scripts/git-town/verify-license.sh
    for s in scripts/git-town/*.sh; do bash -n "$s"; done
    shellcheck --format=gcc scripts/git-town/*.sh || true
    git town config
    bash scripts/git-town/test-fixture.sh
  '
```

The environment identity, including the base image digest, is in `environment.json`; the artifact hashes
and their provenance chain are in `artifact-manifest.json`.

## What is required before any Worker is authorized

Everything still marked `not_run` in `eval-results.json` — `EVAL-GIT-LIVE-05` through `-09`, which need a
disposable remote with synthetic pull requests, a real
`sync --all` in parent-before-child order, a real semantic conflict, partial-mutation detection, a
remote-update race, timeout and output bounds, the eleven preflight refusals, and secret canaries injected
through a real worker credential mechanism. Those need a dedicated GitHub test repository and an authorized
worker environment, neither of which exists here.

## Reviewer sign-off

Not signed off. No reviewer has verified these digests independently, and the two failures above are open.
