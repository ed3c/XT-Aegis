# Git Town v24.0.0 — partial acceptance evidence

**This does not authorize an unattended Worker.** Issue #44's deployment gate stays closed. Five of the
seventeen evals in #43 and #44 ran here; two failed; ten could not run at all.

## What this is

A developer-host `linux/amd64` container that installed the exact pinned Git Town release and ran the
repository's own verification scripts against it. It answers the questions that need only the real
toolchain and the committed contract, and it answers none of the questions that need a remote, real pull
requests, or credentials.

## Result

| Eval | Status | What it establishes |
|---|---|---|
| `EVAL-GIT-LIVE-01` release package identity | passed | the release `checksums.txt`, its entry for the package, and the downloaded package all match the pinned lock; DEB reports `24.0.0` / `amd64` |
| `EVAL-GIT-LIVE-02` installed identity | passed | the installed binary reports `24.0.0` and the copied MIT text matches the pinned digest |
| `EVAL-GIT-LIVE-03` shell analysis | passed | all 15 ShellCheck findings preserved with the tool version |
| `EVAL-GIT-LIVE-04` pinned config parse | passed | the real binary parsed `.git-town.toml` and reported the intended sync strategies and push behavior |
| `EVAL-WORKER-05` committed fixture | passed | `test-fixture.sh` passed unchanged inside the image |
| `EVAL-WORKER-01` immutable environment | **failed** | the image is a general base with tools installed at run time, not a purpose-built pinned Worker image |
| `EVAL-WORKER-04` shell analysis passes | **failed** | ShellCheck exits non-zero because findings exist |
| ten remaining live evals | not run | each needs a disposable remote, real PR metadata, a GitHub CLI session, or a worker credential mechanism |

`eval-results.json` records the argv, exit code, and evidence path for each.

## The two failures, stated plainly

**`EVAL-WORKER-04`.** `bash -n` passes on every file. ShellCheck 0.9.0 exits 1 because 15 findings exist:
11 notes and 4 warnings, no error-severity finding. Eight are `SC1091` "not following: common.sh was not
specified as input", which appear because the scripts were checked individually rather than with
`shellcheck -x`. The rest are `SC2034` unused variables in `common.sh` and `sync-stack.sh`, three `SC2015`
`A && B || C` notes, and one `SC2153` possible misspelling. Changing either the scripts or the ShellCheck
invocation is outside this evidence PR's path ownership, so the finding is recorded rather than fixed.

**`EVAL-WORKER-01`.** The environment is fully recorded and reproducible, but #43 requires an immutable
Worker image built without package-channel installation. This container installs `git`, `curl`, and
`shellcheck` from Debian at run time, so it cannot satisfy that eval however complete its manifest is.

## One gap this run exposed

`scripts/git-town/git-town.lock` pins the release artifact, the license blob, and the config digest, but it
does **not** pin `GIT_TOWN_BINARY_SHA256`. `verify-license.sh` reads that value from the environment and
accepts the run when it is unset, so the installed-binary identity is currently unpinned. This run observed:

```text
dbaba38145246f602940e7261190f394cb4cd6dbc0d079233e3a15c42a11f461  /usr/bin/git-town
```

That value came from a package whose digest matches the pinned lock, so it is a defensible candidate to
pin. Pinning it belongs to a change that owns `scripts/git-town/**`, not to this evidence bundle.

## Reproduction

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
    GIT_TOWN_BINARY_SHA256="$(sha256sum "$(command -v git-town)" | cut -d" " -f1)" \
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

Everything marked `not_run` in `eval-results.json`: a disposable remote with synthetic pull requests, a real
`sync --all` in parent-before-child order, a real semantic conflict, partial-mutation detection, a
remote-update race, timeout and output bounds, the eleven preflight refusals, and secret canaries injected
through a real worker credential mechanism. Those need a dedicated GitHub test repository and an authorized
worker environment, neither of which exists here.

## Reviewer sign-off

Not signed off. No reviewer has verified these digests independently, and the two failures above are open.
