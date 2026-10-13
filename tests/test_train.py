import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sentinel import train
from sentinel.store import Store


def _mk_store(tmp_path):
    return Store(str(tmp_path / "t.db"))


def _add_snapshot(store, days_ago, layers=None):
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    store.conn.execute(
        "INSERT INTO risk_scores (run_id, ts, risk_index, level, layer_scores, "
        "features) VALUES (1, ?, 50, 'KUNING', ?, '{}')",
        (ts, json.dumps(layers or {"global": 10, "regional": 20,
                                   "nasional": 15, "lokal": 30})))
    store.conn.commit()


def test_snapshot_labelling_ages_and_windows(tmp_path):
    store = _mk_store(tmp_path)
    crisis_start = (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat()
    crisis_end = (datetime.now(timezone.utc) - timedelta(days=8)).date().isoformat()
    store.conn.execute(
        "INSERT INTO labels(start, end, outcome, label, triggers) VALUES (?,?,1,'uji','{}')",
        (crisis_start, crisis_end))
    store.conn.commit()
    _add_snapshot(store, 9)    # inside crisis, old enough -> positive
    _add_snapshot(store, 20)   # long before crisis -> negative
    _add_snapshot(store, 1)    # too young: outcome window not observable
    X, y = train._snapshot_examples(store)
    assert len(X) == 2 and sorted(y) == [0, 1], (X, y)


def test_maintain_labels_opens_and_closes(tmp_path):
    store = _mk_store(tmp_path)
    assert train.maintain_labels(store, crisis_active=True) == "opened"
    assert train.maintain_labels(store, crisis_active=True) is None  # no double
    # Simulate: last crisis run 4 days ago, now calm -> closes.
    old = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
    store.conn.execute(
        "INSERT INTO runs(started_at, finished_at, status, summary) "
        "VALUES (?, ?, 'ok', 'risk=85 level=MERAH crisis=True')", (old, old))
    store.conn.commit()
    assert train.maintain_labels(store, crisis_active=False) == "closed"
    row = store.conn.execute("SELECT end FROM labels").fetchone()
    assert row[0] is not None


def test_maintain_labels_keeps_open_when_recent(tmp_path):
    store = _mk_store(tmp_path)
    assert train.maintain_labels(store, crisis_active=True) == "opened"
    recent = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    store.conn.execute(
        "INSERT INTO runs(started_at, finished_at, status, summary) "
        "VALUES (?, ?, 'ok', 'risk=60 level=ORANYE crisis=True')", (recent, recent))
    store.conn.commit()
    assert train.maintain_labels(store, crisis_active=False) is None
