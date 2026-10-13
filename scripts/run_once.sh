#!/bin/sh
# One full pipeline run. Used by the systemd timer and by manual checks.
set -e
cd "$(dirname "$0")/.."
PYTHONPATH=src exec python3 -m sentinel.main "$@"
