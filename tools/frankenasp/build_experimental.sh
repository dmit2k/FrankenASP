#!/usr/bin/env bash
# Build the owner-specific AArch64 experimental TECHO5 with a HA-rankable
# version. The release baseline MUST be specified explicitly; no "dev".
set -euo pipefail
if (( $# != 2 )); then
    echo "Usage: $0 vMAJOR.MINOR.PATCH /path/to/output/techo5-experimental" >&2
    exit 2
fi
BASE="$1"
OUT="$2"
[[ "$BASE" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
    echo "Expected official base release vX.Y.Z (e.g. v1.6.0)" >&2; exit 2;
}
# The daemon now belongs to the *separate* TECHO5 adapter checkout.
# No fallback to an unrelated TECHO5 checkout: explicit origin is safer.
if [[ -z "${TECHO5_ADAPTER_ROOT:-}" ]]; then
    echo "Set TECHO5_ADAPTER_ROOT to a checkout of dmit2k/techo5 (frankenasp-adapter)" >&2
    exit 2
fi
DIR="$(cd "$TECHO5_ADAPTER_ROOT/echod" && pwd)"
[[ -f "$DIR/internal/hardware/mic/factory_asp_athena.go" ]] || {
    echo "Not a FrankenASP-enabled TECHO5 adapter checkout: $DIR" >&2; exit 2;
}
command -v go >/dev/null || { echo "Go 1.26 toolchain required" >&2; exit 2; }
command -v git >/dev/null || { echo "git is required" >&2; exit 2; }
COMMIT="$(git -C "$DIR" rev-parse --short=10 HEAD)"
ROOT="$(git -C "$DIR" rev-parse --show-toplevel)"
DIRTY=
if [[ -n "$(git -C "$DIR" status --porcelain --untracked-files=normal)" ]]; then
    # A plain .dirty would give DIFFERENT experimental binaries identical
    # advertised versions. Include a short digest of the current source
    # changes and untracked owner-authored code; nothing is sent anywhere.
    CHANGE_HASH="$(
      {
        git -C "$ROOT" diff --binary -- echod
        git -C "$ROOT" ls-files --others --exclude-standard -- echod |
          LC_ALL=C sort |
          while IFS= read -r path; do sha256sum "$ROOT/$path"; done
      } | sha256sum | cut -c1-12
    )"
    DIRTY=".dirty.${CHANGE_HASH}"
    echo "WARNING: uncommitted sources included in experimental version digest ${CHANGE_HASH}" >&2
fi
# '_' is stripped for HA's version rank; normal newer upstream releases
# remain visible. A normal latest stable or dev rootfs has no FrankenASP.
VERSION="${BASE}_frankenasp.${COMMIT}${DIRTY}"
NOW="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
PKG="github.com/HuskerMinion/techo5/echod/internal/layout"
mkdir -p "$(dirname "$OUT")"
OUT="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"
(cd "$DIR" && CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath \
    -ldflags "-s -w -X ${PKG}.Version=${VERSION} -X ${PKG}.GitCommit=${COMMIT} -X ${PKG}.BuildDate=${NOW}" \
    -o "$OUT" ./cmd/echod)
echo "Built owner-local experimental TECHO5: $OUT"
echo "Staged software version: $VERSION"
echo "This build is NOT an official upstream TECHO5 release."
