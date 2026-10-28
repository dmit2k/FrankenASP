#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
: "${GO:=/home/gptlab/dev/techo5-asp-p3-4a-arm32-build-20261027/toolchains/go1.26.9/bin/go}"
: "${OUT:?Set OUT to a private output directory outside the source tree}"
export GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off GOMAXPROCS=2
test "$("$GO" env GOVERSION)" = go1.26.9 || { echo "Go1.26.9 required" >&2; exit 2; }
mkdir -p "$OUT"
revision="$(git rev-parse HEAD)"
if test -n "$(git status --porcelain)"; then revision="$revision-dirty"; fi
GOOS=linux GOARCH=arm GOARM=7 CGO_ENABLED=0 "$GO" build -p 1 -mod=readonly -buildvcs=false -trimpath \
  -ldflags="-s -w -X main.sourceRevision=$revision" -o "$OUT/asp2-install-arm32" .
chmod 0500 "$OUT/asp2-install-arm32"
"$GO" version -m "$OUT/asp2-install-arm32"
sha256sum "$OUT/asp2-install-arm32"
