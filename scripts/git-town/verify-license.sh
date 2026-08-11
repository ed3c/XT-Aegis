#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"
# shellcheck source=git-town.lock
source "$LOCK_FILE"

require_repo
require_command git
require_command git-town

LICENSE_PATH="$REPO_ROOT/third_party/git-town/LICENSE"
[[ -f "$LICENSE_PATH" ]] || die "missing copied Git Town license"

actual_license_sha="$(sha256_file "$LICENSE_PATH")"
[[ "$actual_license_sha" == "$GIT_TOWN_LICENSE_SHA256" ]] ||
  die "Git Town license SHA-256 mismatch"

version_output="$(git town --version 2>&1)"
actual_version="$(printf '%s\n' "$version_output" | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 || true)"
[[ "$actual_version" == "$GIT_TOWN_REQUIRED_VERSION" ]] ||
  die "Git Town version mismatch: expected $GIT_TOWN_REQUIRED_VERSION, observed ${actual_version:-unknown}"

binary_path="$(command -v git-town)"
expected_binary_sha="${GIT_TOWN_BINARY_SHA256:-}"
[[ -n "$expected_binary_sha" && "$expected_binary_sha" != "UNSET" ]] ||
  die "GIT_TOWN_BINARY_SHA256 must contain the approved worker-image checksum"
[[ "$expected_binary_sha" =~ ^[a-f0-9]{64}$ ]] ||
  die "GIT_TOWN_BINARY_SHA256 must be a lowercase SHA-256 value"

actual_binary_sha="$(sha256_file "$binary_path")"
[[ "$actual_binary_sha" == "$expected_binary_sha" ]] ||
  die "installed git-town binary SHA-256 mismatch"

printf 'git-town version=%s binary_sha256=%s license=%s license_sha256=%s tag=%s license_blob_sha=%s\n' \
  "$actual_version" "$actual_binary_sha" "$GIT_TOWN_LICENSE_ID" "$actual_license_sha" \
  "$GIT_TOWN_UPSTREAM_TAG" "$GIT_TOWN_LICENSE_BLOB_SHA"
