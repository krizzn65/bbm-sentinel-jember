#!/bin/sh
# Self-healing bootstrap, run before every pipeline pass.
# Everything the system needs lives under the repo (home storage, which
# survives VM replacement). If a piece is missing anyway, rebuild what
# can be rebuilt and record the state in alerts/runtime_health.json.
# NEVER fails the caller: the pipeline runs with whatever is available
# and degraded parts report themselves (vision says "unavailable").
ROOT="${SENTINEL_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT" || exit 0
STATUS="ok"

if [ ! -x .venv/bin/python ]; then
  echo "[ensure] .venv missing, rebuilding"
  python3 -m venv --system-site-packages .venv 2>/dev/null \
    && .venv/bin/pip install -q onnxruntime 2>/dev/null \
    || STATUS="venv_rebuild_failed"
fi
if [ -x .venv/bin/python ] && ! .venv/bin/python -c "import onnxruntime" 2>/dev/null; then
  .venv/bin/pip install -q onnxruntime 2>/dev/null || STATUS="onnxruntime_missing"
fi
if [ ! -f models/yolov8s.onnx ] && [ ! -f models/yolov8n.onnx ]; then
  echo "[ensure] vision model missing (vision layer will report unavailable)"
  STATUS="model_missing"
fi
mkdir -p alerts
printf '{"checked_at": "%s", "status": "%s"}\n' \
  "$(date -Is)" "$STATUS" > alerts/runtime_health.json
exit 0
