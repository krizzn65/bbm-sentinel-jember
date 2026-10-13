#!/bin/sh
# One full pipeline run. Used by the systemd timer and by manual checks.
# Prefers the repo venv (onnxruntime for the vision layer lives there).
set -e
cd "$(dirname "$0")/.."
if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
else
  PY=python3
fi
PYTHONPATH=src exec "$PY" -m sentinel.main "$@"
