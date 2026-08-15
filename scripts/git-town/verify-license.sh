#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

require_repo
require_command git
require_command git-town
require_command timeout

LICENSE_PATH="$REPO_ROOT/third_party/git-town/LICENSE"
[[ -f "$LICENSE_PATH" && ! -L "$LICENSE_PATH" ]] || die "missing regular copied Git Town license"

actual_license_sha="$(sha256_file "$LICENSE_PATH")"
[[ "$actual_license_sha" == "$GIT_TOWN_LICENSE_SHA256" ]] ||
  die "Git Town license SHA-256 mismatch"

if ! version_output="$(timeout --signal=TERM --kill-after=5s 30s git town --version 2>&1)"; then
  die "Git Town version command failed or timed out"
fi
actual_version="$(printf '%s\n' "$version_output" | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 || true)"
[[ "$actual_version" == "$GIT_TOWN_REQUIRED_VERSION" ]] ||
  die "Git Town version mismatch: expected $GIT_TOWN_REQUIRED_VERSION, observed ${actual_version:-unknown}"

# `command -v`, deliberately: the property worth checking is the identity of the binary this worker will
# actually run, not the identity of a file the package happens to own. A wrapper earlier on PATH is a
# different binary and must fail here.
binary_path="$(command -v git-town)"
[[ -f "$binary_path" ]] || die "resolved git-town command is not a regular file"

# The expectation comes from the lock, not from the caller. Reading it from the environment let whoever
# started the worker declare what the binary should hash to, which verifies the run against its own claim.
expected_binary_sha="$GIT_TOWN_LINUX_AMD64_BINARY_SHA256"
[[ "$expected_binary_sha" =~ ^[a-f0-9]{64}$ ]] ||
  die "GIT_TOWN_LINUX_AMD64_BINARY_SHA256 must be a lowercase SHA-256 value in the lock"

actual_binary_sha="$(sha256_file "$binary_path")"
[[ "$actual_binary_sha" == "$expected_binary_sha" ]] ||
  die "installed git-town binary SHA-256 mismatch: expected $expected_binary_sha, observed $actual_binary_sha at $binary_path"

printf 'git-town version=%s binary_sha256=%s license=%s license_sha256=%s tag=%s release_commit=%s license_blob_sha=%s\n' \
  "$actual_version" "$actual_binary_sha" "$GIT_TOWN_LICENSE_ID" "$actual_license_sha" \
  "$GIT_TOWN_UPSTREAM_TAG" "$GIT_TOWN_RELEASE_COMMIT" "$GIT_TOWN_LICENSE_BLOB_SHA"
