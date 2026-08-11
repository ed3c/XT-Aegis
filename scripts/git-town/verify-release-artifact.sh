#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"
# shellcheck source=git-town.lock
source "$LOCK_FILE"

[[ $# -eq 1 ]] || die "usage: $0 /path/to/$GIT_TOWN_LINUX_AMD64_PACKAGE"
artifact=$1
[[ -f "$artifact" && ! -L "$artifact" ]] || die "artifact must be a regular non-symlink file"
[[ "$(basename -- "$artifact")" == "$GIT_TOWN_LINUX_AMD64_PACKAGE" ]] ||
  die "unexpected artifact name: $(basename -- "$artifact")"

actual_sha="$(sha256_file "$artifact")"
[[ "$actual_sha" == "$GIT_TOWN_LINUX_AMD64_PACKAGE_SHA256" ]] ||
  die "Git Town release artifact SHA-256 mismatch"

if command -v dpkg-deb >/dev/null 2>&1; then
  package_version="$(dpkg-deb -f "$artifact" Version 2>/dev/null || true)"
  [[ "$package_version" == "$GIT_TOWN_REQUIRED_VERSION" ]] ||
    die "package version mismatch: expected $GIT_TOWN_REQUIRED_VERSION, observed ${package_version:-unknown}"
fi

printf 'verified artifact=%s sha256=%s version=%s release_commit=%s\n' \
  "$GIT_TOWN_LINUX_AMD64_PACKAGE" "$actual_sha" "$GIT_TOWN_REQUIRED_VERSION" "$GIT_TOWN_RELEASE_COMMIT"
