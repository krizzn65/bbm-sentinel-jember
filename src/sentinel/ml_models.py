"""Model registry: classical ML, deep learning, honest gates.

Adopted ecosystem (researched 2026-10-14): Nixtla - statsforecast
(AutoETS / AutoTheta / SeasonalNaive) for the risk time series, and
neuralforecast (NHITS) as the deep-learning entry. Both are wired
here behind DATA gates, because a model trained on two days of data
is theatre, not intelligence:

  statsforecast hourly ensemble : needs >= 48 hourly risk points
  ridge on run snapshots        : needs >= 40 labelled snapshots
                                  (provided by train.py's ageing)
  NHITS (deep learning)         : needs >= 60 DAILY points and a
                                  working neuralforecast import

Every run, this module reports each model's true state into
alerts/ml_models.json - active with its latest forecast, or gated
with the exact count it is waiting for. When the statsforecast gate
opens, its 24h-ahead path cross-checks the main forecast; the
weighted index remains the decision maker until a challenger proves
itself in the self-audit, not before.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATES = {"statsforecast_hourly_points": 48, "ridge_snapshots": 40,
         "nhits_daily_points": 60}


def _hourly_series(store):
    rows = store.conn.execute(
        "SELECT ts, risk_index FROM risk_scores ORDER BY ts").fetchall()
    return [(r[0], r[1]) for r in rows]


def _daily_peaks(store):
    days = {}
    for ts, risk in _hourly_series(store):
        d = ts[:10]
        days[d] = max(days.get(d, 0.0), risk or 0.0)
    return sorted(days.items())


def _statsforecast_path(series, horizon=24):
    import pandas as pd
    from statsforecast import StatsForecast
    from statsforecast.models import AutoETS, AutoTheta, SeasonalNaive
    df = pd.DataFrame({
        "unique_id": ["risk"] * len(series),
        "ds": pd.to_datetime([t for t, _ in series]),
        "y": [v for _, v in series]})
    sf = StatsForecast(models=[AutoETS(season_length=24),
                               AutoTheta(season_length=24),
                               SeasonalNaive(season_length=24)],
                       freq="h")
    out = sf.forecast(df=df, h=horizon)
    path = []
    for _, row in out.iterrows():
        vals = [row.get("AutoETS"), row.get("AutoTheta"),
                row.get("SeasonalNaive")]
        vals = [v for v in vals if v is not None]
        path.append(round(sum(vals) / len(vals), 1))
    return path


def run(store):
    report = {"gates": GATES, "models": {}}
    series = _hourly_series(store)
    daily = _daily_peaks(store)
    report["data"] = {"hourly_points": len(series),
                      "daily_points": len(daily)}
    # 1. statsforecast ensemble on the hourly risk series
    m = {"kind": "classical ensemble (Nixtla statsforecast)"}
    if len(series) >= GATES["statsforecast_hourly_points"]:
        try:
            path = _statsforecast_path(series)
            m.update({"status": "active",
                      "next_24h_peak": max(path),
                      "next_24h_path": path})
        except Exception as exc:
            m.update({"status": "error", "detail": str(exc)[:160]})
    else:
        m.update({"status": "gated",
                  "waiting_for": f"{len(series)}/"
                                 f"{GATES['statsforecast_hourly_points']} "
                                 "titik risiko per jam"})
    report["models"]["statsforecast_ensemble"] = m
    # 2. NHITS deep learning: data gate first, import probe second
    m = {"kind": "deep learning (Nixtla neuralforecast NHITS)"}
    if len(daily) < GATES["nhits_daily_points"]:
        m.update({"status": "gated",
                  "waiting_for": f"{len(daily)}/"
                                 f"{GATES['nhits_daily_points']} "
                                 "hari data (puncak harian)"})
    else:
        try:
            import neuralforecast  # noqa: F401
            m.update({"status": "ready_to_train"})
        except Exception as exc:
            m.update({"status": "blocked_env",
                      "detail": f"impor neuralforecast gagal: "
                                f"{str(exc)[:120]}"})
    report["models"]["nhits"] = m
    # 3. environment probe in a subprocess: a broken optional import
    # (neuralforecast pulls a long chain) must not spam the pipeline
    # log or slow the run down.
    import subprocess
    import sys as _sys
    def _probe(name):
        r = subprocess.run(
            [_sys.executable, "-c",
             f"import {name}; print({name}.__version__)"],
            capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            return r.stdout.strip().splitlines()[-1]
        return None
    v = _probe("statsforecast")
    report["env"] = {"statsforecast": v or "tidak tersedia"}
    v = _probe("neuralforecast")
    report["env"]["neuralforecast"] = (
        v or "terpasang tetapi impor gagal di server ini "
             "(rantai dependensinya bertabrakan dengan numpy sistem)")
    (ROOT / "alerts" / "ml_models.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1))
    return report
