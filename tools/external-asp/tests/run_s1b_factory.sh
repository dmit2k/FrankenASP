#!/usr/bin/env bash
# Test-only overlay; do not create/change any file inside the pinned TECHO5 tree.
set -euo pipefail
D=$(cd "$(dirname "$0")" && pwd)
: "${TECHO5_S1B_ROOT:?}" "${ASP2_BUILD_DIR:?}" "${GO:?Use pinned offline Go}" "${GOMODCACHE:?}"
PIN=${TECHO5_R1_PIN:?Set the R1 Go commit}
[[ $(git -C "$TECHO5_S1B_ROOT" rev-parse HEAD) == "$PIN" ]]
[[ -z $(git -C "$TECHO5_S1B_ROOT" status --porcelain=v1) ]]
export GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off GOWORK=off GOMAXPROCS=2
export F1A_OVERLAY_SOURCE="$D/s1b_factory_integration_test.go"
python3 - <<'PY'
import json,os
from pathlib import Path
build=Path(os.environ["ASP2_BUILD_DIR"])
root=Path(os.environ["TECHO5_S1B_ROOT"])
(build/"s1b-factory-overlay.json").write_text(json.dumps({"Replace":{
 str(root/"echod/internal/hardware/mic/f1b_overlay_test.go"):os.environ["F1A_OVERLAY_SOURCE"]
}},indent=2)+"\n")
PY
cd "$TECHO5_S1B_ROOT/echod"
"$GO" test -overlay="$ASP2_BUILD_DIR/s1b-factory-overlay.json" -p 1 -count=1 -v -run '^TestF1B' ./internal/hardware/mic
"$GO" test -overlay="$ASP2_BUILD_DIR/s1b-factory-overlay.json" -p 1 -race -count=3 -v -run '^TestF1B' ./internal/hardware/mic
[[ $(git rev-parse HEAD) == "$PIN" ]]
[[ -z $(git status --porcelain=v1) ]]
echo "PASS: pinned S1-B Go host to F1-B factory mock C child; TECHO5 checkout unchanged"
