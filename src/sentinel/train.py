"""ML calibration path, kept honest - but the history is a teacher now.

Training material comes from three sources:
1. Historical episodes (data/historical_episodes.json): every documented
   Jember crisis, coded into trigger vectors + duration/peak-offset
   priors. These already drive the analog layer in history.py today.
2. Archival windows (data/historical_windows.json): daily Brent/FX/rain/
   wave series around each episode, backfilled by
   scripts/backfill_history.py, so pre-crisis conditions are on record.
3. Live snapshots: every pipeline run's layer scores, labelled once they
   are 5+ days old by whether a documented crisis overlapped the
   following 5 days.

A pure-Python logistic regression (no sklearn dependency) is fitted per
feature space once that space has >=20 labelled examples; until then the
weighted index + analog layer decide, and this module reports exactly
what is missing instead of pretending a model exists."""
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import history
from .store import Store

ROOT = Path(__file__).resolve().parents[2]
MIN_LABELLED = 20


def _fit_logistic(X, y, epochs=800, lr=0.08, l2=0.01):
    n, d = len(X), len(X[0])
    means = [sum(r[i] for r in X) / n for i in range(d)]
    stds = []
    for i in range(d):
        var = sum((r[i] - means[i]) ** 2 for r in X) / n
        stds.append(var ** 0.5 or 1.0)
    Z = [[(r[i] - means[i]) / stds[i] for i in range(d)] for r in X]
    w = [0.0] * d
    b = 0.0
    for _ in range(epochs):
        gw = [0.0] * d
        gb = 0.0
        for row, target in zip(Z, y):
            z = b + sum(wi * xi for wi, xi in zip(w, row))
            p = 1 / (1 + math.exp(-max(-30, min(30, z))))
            err = p - target
            for i in range(d):
                gw[i] += err * row[i]
            gb += err
        for i in range(d):
            w[i] -= lr * (gw[i] / n + l2 * w[i])
        b -= lr * gb / n
    correct = loss = 0
    for row, target in zip(Z, y):
        z = b + sum(wi * xi for wi, xi in zip(w, row))
        p = min(1 - 1e-9, max(1e-9, 1 / (1 + math.exp(-max(-30, min(30, z))))))
        correct += int((p >= 0.5) == bool(target))
        loss += -(target * math.log(p) + (1 - target) * math.log(1 - p))
    return {"weights": [round(v, 4) for v in w], "bias": round(b, 4),
            "means": [round(v, 3) for v in means], "stds": [round(v, 3) for v in stds],
            "train_accuracy": round(correct / n, 3),
            "train_logloss": round(loss / n, 3), "n": n}


def _episode_examples():
    eps = [e for e in history.load_episodes() if e["status"] == "closed"]
    X = [[float(e["triggers"].get(k, 0)) for k in history.TRIGGER_KEYS] for e in eps]
    y = [int(e["outcome"]) for e in eps]
    return X, y, [e["id"] for e in eps]


def _snapshot_examples(store):
    rows = store.conn.execute(
        "SELECT ts, layer_scores FROM risk_scores ORDER BY ts").fetchall()
    labels = store.conn.execute("SELECT start, end FROM labels").fetchall()
    spans = []
    for s, e in labels:
        start = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        end = (datetime.fromisoformat(e).replace(tzinfo=timezone.utc)
               if e else datetime.now(timezone.utc))
        spans.append((start, end))
    now = datetime.now(timezone.utc)
    X, y = [], []
    for ts, layers_json in rows:
        t = datetime.fromisoformat(ts)
        if (now - t) < timedelta(days=5):
            continue  # outcome window not observable yet
        layers = json.loads(layers_json or "{}")
        X.append([float(layers.get(k) or 0) for k in ("global", "regional", "nasional", "lokal")])
        y.append(1 if any(s <= t + timedelta(days=5) and e >= t for s, e in spans) else 0)
    return X, y


def _windows_coverage():
    p = ROOT / "data" / "historical_windows.json"
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    cov = {}
    for w in data["windows"]:
        days = w["days"]
        cov[w["episode_id"]] = {
            "days": len(days),
            "brent_days": sum(1 for d in days if d.get("brent_close") is not None),
            "fx_days": sum(1 for d in days if d.get("usdidr") is not None),
            "rain_days": sum(1 for d in days if d.get("rain_gumitir_mm") is not None),
            "wave_days": sum(1 for d in days if d.get("wave_ketapang_max_m") is not None),
        }
    return cov


def status(db_path=None):
    store = Store(db_path or str(ROOT / "data" / "sentinel.db"))
    Xe, ye, ids = _episode_examples()
    Xs, ys = _snapshot_examples(store)
    report = {
        "historical_episodes": {
            "closed_examples": len(Xe), "episode_ids": ids,
            "features": history.TRIGGER_KEYS,
            "priors": history.priors(),
            "archival_windows": _windows_coverage(),
        },
        "live_snapshots": {"labelled": len(Xs),
                           "positives": sum(ys), "negatives": len(ys) - sum(ys),
                           "features": ["global", "regional", "nasional", "lokal"]},
        "min_labelled_for_training": MIN_LABELLED,
        "models": {},
    }
    for name, X, y in (("episode_trigger_model", Xe, ye),
                       ("live_snapshot_model", Xs, ys)):
        if len(X) >= MIN_LABELLED and 0 < sum(y) < len(y):
            report["models"][name] = _fit_logistic(X, y)
        else:
            report["models"][name] = {
                "status": "not_fitted",
                "reason": (f"{len(X)} contoh berlabel "
                           f"({sum(y)} positif / {len(y) - sum(y)} negatif); "
                           f"perlu >= {MIN_LABELLED} dan kedua kelas terisi")}
    report["decision_maker"] = ("weighted index + historical analog layer "
                                 "(models are reported, not yet promoted)")
    out = ROOT / "alerts" / "model_report.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    return report


if __name__ == "__main__":
    print(json.dumps(status(), ensure_ascii=False, indent=1))
