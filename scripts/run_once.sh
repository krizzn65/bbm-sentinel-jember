#!/bin/sh
# One full pipeline run. Scheduling lives in the Muse cron layer
# (runtime-managed, restored after VM replacement) - NOT in systemd:
# the guest VM is replaced periodically and /etc units do not survive
# (proven 2026-10-13 23:57 WIB, when the timer vanished mid-crisis).
# A lock + freshness guard make overlapping invocations harmless.
set -e
cd "$(dirname "$0")/.."
./scripts/ensure_runtime.sh || true
exec 9>data/.run.lock
if ! flock -n 9; then
  echo "another run is in progress; skipping"
  exit 0
fi
FORCE=0
if [ "$1" = "--force" ]; then FORCE=1; shift; fi
if [ "$FORCE" != "1" ] && [ -f alerts/latest_run.json ]; then
  AGE=$(( $(date +%s) - $(stat -c %Y alerts/latest_run.json) ))
  if [ "$AGE" -lt 2700 ]; then
    echo "last run ${AGE}s ago (<45m); skipping (use --force to override)"
    exit 0
  fi
fi
if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
else
  PY=python3
fi
PYTHONPATH=src exec "$PY" -m sentinel.main "$@"
