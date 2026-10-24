#!/usr/bin/env bash
# Build experimental AArch64 TECHO5 with an HA-rankable upstream prefix
# and complete FrankenASP/adapter source provenance.
set -euo pipefail
if (( $# != 2 )); then
    echo "Usage: $0 vMAJOR.MINOR.PATCH /path/to/output/techo5-experimental" >&2
    exit 2
fi
BASE="$1"
OUT="$2"
[[ "$BASE" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
    echo "Expected official TECHO5 base vX.Y.Z (e.g. v1.6.0)" >&2; exit 2;
}
if [[ -z "\${TECHO5_ADAPTER_ROOT:-}" ]]; then
    echo "Set TECHO5_ADAPTER_ROOT to dmit2k/techo5 (frankenasp-adapter)" >&2
    exit 2
fi
command -v git >/dev/null || { echo "git is required" >&2; exit 2; }
command -v go >/dev/null || { echo "Go 1.26 toolchain required" >&2; exit 2; }
TOOL_DIR="$(cd "$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
FRANKEN_ROOT="$(cd "$TOOL_DIR/../.." && pwd)"
ADAPTER_ROOT="$(cd "$TECHO5_ADAPTER_ROOT" && pwd)"
DIR="$ADAPTER_ROOT/echod"
[[ -f "$DIR/internal/hardware/mic/factory_asp_athena.go" ]] || {
    echo "Not a FrankenASP-enabled TECHO5 adapter checkout: $DIR" >&2; exit 2;
}
[[ "$(git -C "$FRANKEN_ROOT" rev-parse --show-toplevel)" == "$FRANKEN_ROOT" ]] || {
    echo "FrankenASP must be a standalone Git checkout" >&2; exit 2;
}
[[ "$(git -C "$ADAPTER_ROOT" rev-parse --show-toplevel)" == "$ADAPTER_ROOT" ]] || {
    echo "TECHO5 adapter must be a separate Git checkout" >&2; exit 2;
}
FRANKEN_SHA="$(git -C "$FRANKEN_ROOT" rev-parse --verify HEAD)"
ADAPTER_SHA="$(git -C "$ADAPTER_ROOT" rev-parse --verify HEAD)"
FRANKEN_SHORT="\${FRANKEN_SHA:0:10}"
ADAPTER_SHORT="\${ADAPTER_SHA:0:10}"

# Exact version tag => release version. Untagged commits after a release
# are marked nextN; a checkout with no reachable version tag is "dev".
DESCRIBE="$(git -C "$FRANKEN_ROOT" describe --tags --long --abbrev=10 --match 'v[0-9]*' HEAD 2>/dev/null || true)"
FRANKEN_VERSION="dev"
if [[ "$DESCRIBE" =~ ^v([0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?)-([0-9]+)-g([0-9a-f]+)$ ]]; then
    FRANKEN_VERSION="\${BASH_REMATCH[1]}"
    AHEAD="\${BASH_REMATCH[3]}"
    if (( AHEAD > 0 )); then
        FRANKEN_VERSION="\${FRANKEN_VERSION}.next\${AHEAD}"
    fi
fi

# Dirty content in EITHER repository must not have the same identity as its
# pristine commit. Hash tracked and untracked changes without printing files.
dirty_suffix() {
    local root="$1" prefix="$2" hash
    if [[ -z "$(git -C "$root" status --porcelain --untracked-files=normal)" ]]; then
        return
    fi
    hash="$(
        {
            git -C "$root" diff HEAD --binary -- .
            git -C "$root" ls-files --others --exclude-standard -z |
                LC_ALL=C sort -z |
                while IFS= read -r -d '' file; do
                    sha256sum "$root/$file"
                done
        } | sha256sum | cut -c1-12
    )"
    printf '.%s%s' "$prefix" "$hash"
}
FRANKEN_DIRTY="$(dirty_suffix "$FRANKEN_ROOT" fd)"
ADAPTER_DIRTY="$(dirty_suffix "$ADAPTER_ROOT" ad)"
if [[ -n "$FRANKEN_DIRTY$ADAPTER_DIRTY" ]]; then
    echo "WARNING: uncommitted FrankenASP/adapter content is recorded in the version" >&2
fi

# The portion before '_' is the owner-selected TECHO5 baseline.
# Home Assistant drops the build detail after '_' for version ranking.
VERSION="\${BASE}_frankenasp-\${FRANKEN_VERSION}.f\${FRANKEN_SHORT}.a\${ADAPTER_SHORT}\${FRANKEN_DIRTY}\${ADAPTER_DIRTY}"
NOW="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
PKG="github.com/HuskerMinion/techo5/echod/internal/layout"
# The adapter only reads GitCommit for --version; retain both full SHAs.
SOURCE_ID="frankenasp=\${FRANKEN_SHA},adapter=\${ADAPTER_SHA}"
mkdir -p "$(dirname "$OUT")"
OUT="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"
(cd "$DIR" && CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath \
    -ldflags "-s -w -X \${PKG}.Version=\${VERSION} -X \${PKG}.GitCommit=\${SOURCE_ID} -X \${PKG}.BuildDate=\${NOW}" \
    -o "$OUT" ./cmd/echod)
echo "Built owner-local experimental TECHO5: $OUT"
echo "Staged software version: $VERSION"
echo "FrankenASP source: $FRANKEN_SHA ($FRANKEN_VERSION)"
echo "TECHO5 adapter source: $ADAPTER_SHA"
echo "TECHO5 base supplied by owner: $BASE (not an ABI-compatibility guarantee)"
echo "This build is NOT an official upstream TECHO5 release."
