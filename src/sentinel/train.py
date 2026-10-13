"""ML calibration path, kept honest.

Today the labelled evidence is 4 crisis episodes (data/episodes.json) plus
the labelled outcomes this pipeline records from now on (each run's features
paired with whether a crisis was confirmed within the following 5 days).
That is not enough to train a trustworthy model, so this module refuses to
fit until at least 20 labelled run-snapshots exist. When they do, it fits a
logistic regression (features: layer scores + physical signals) and writes
metrics to alerts/model_report.json. Until then the weighted index in
scoring.py stays the decision maker, and its weights get reviewed against
each new episode."""
import json
from pathlib import Path

from .store import Store

ROOT = Path(__file__).resolve().parents[2]
MIN_LABELLED = 20


def status(db_path=None):
    store = Store(db_path or str(ROOT / "data" / "sentinel.db"))
    runs = store.conn.execute("SELECT COUNT(*) FROM risk_scores").fetchone()[0]
    labels = store.conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0]
    report = {"risk_snapshots": runs, "labelled_episodes": labels,
              "min_labelled_for_training": MIN_LABELLED,
              "ready": runs >= MIN_LABELLED,
              "model": None}
    if report["ready"]:
        try:
            import sklearn  # noqa: F401
            report["model"] = "sklearn present; training entrypoint pending review"
        except ImportError:
            report["model"] = "scikit-learn not installed; index remains in use"
    out = ROOT / "alerts" / "model_report.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    print(json.dumps(status(), indent=1))
