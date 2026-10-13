import json
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, started_at TEXT, finished_at TEXT, status TEXT, summary TEXT
);
CREATE TABLE IF NOT EXISTS observations (
  id INTEGER PRIMARY KEY, run_id INTEGER, ts TEXT, layer TEXT, source TEXT,
  metric TEXT, value REAL, unit TEXT, meta TEXT
);
CREATE INDEX IF NOT EXISTS idx_obs_metric_ts ON observations(metric, ts);
CREATE TABLE IF NOT EXISTS risk_scores (
  id INTEGER PRIMARY KEY, run_id INTEGER, ts TEXT, risk_index REAL, level TEXT,
  layer_scores TEXT, features TEXT
);
CREATE TABLE IF NOT EXISTS station_scores (
  id INTEGER PRIMARY KEY, run_id INTEGER, ts TEXT, station_code TEXT,
  crisis_score REAL, confidence REAL, detail TEXT
);
CREATE TABLE IF NOT EXISTS ground_reports (
  id INTEGER PRIMARY KEY, ts TEXT, station_code TEXT, fuel_type TEXT,
  status TEXT, queue_note TEXT, reporter TEXT
);
CREATE TABLE IF NOT EXISTS labels (
  id INTEGER PRIMARY KEY, start TEXT, end TEXT, outcome INTEGER, label TEXT, triggers TEXT
);
CREATE TABLE IF NOT EXISTS vision_corrections (
  id INTEGER PRIMARY KEY, ts TEXT, image_path TEXT, station_code TEXT,
  model_counts TEXT, corrected_counts TEXT, note TEXT, source TEXT
);
CREATE TABLE IF NOT EXISTS social_signals (
  id INTEGER PRIMARY KEY, ts TEXT, platform TEXT, posts_found INTEGER,
  queue_posts INTEGER, stations_mentioned TEXT, detail TEXT
);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def start_run(self):
        cur = self.conn.execute(
            "INSERT INTO runs(started_at, status) VALUES (?, 'running')", (now_iso(),)
        )
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id, status, summary):
        self.conn.execute(
            "UPDATE runs SET finished_at=?, status=?, summary=? WHERE id=?",
            (now_iso(), status, summary, run_id),
        )
        self.conn.commit()

    def observe(self, run_id, layer, source, metric, value, unit="", meta=None):
        self.conn.execute(
            "INSERT INTO observations(run_id, ts, layer, source, metric, value, unit, meta)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (run_id, now_iso(), layer, source, metric, value, unit,
             json.dumps(meta or {}, ensure_ascii=False)),
        )
        self.conn.commit()

    def latest(self, metric):
        row = self.conn.execute(
            "SELECT value, ts, meta FROM observations WHERE metric=? ORDER BY id DESC LIMIT 1",
            (metric,),
        ).fetchone()
        if not row:
            return None
        return {"value": row[0], "ts": row[1], "meta": json.loads(row[2] or "{}")}

    def history(self, metric, limit=500):
        rows = self.conn.execute(
            "SELECT ts, value FROM observations WHERE metric=? ORDER BY id DESC LIMIT ?",
            (metric, limit),
        ).fetchall()
        return [{"ts": t, "value": v} for t, v in rows]

    def baseline(self, metric, min_samples=8):
        vals = [r["value"] for r in self.history(metric, limit=200)]
        if len(vals) < min_samples:
            return None
        vals.sort()
        n = len(vals)
        mean = sum(vals) / n
        var = sum((v - mean) ** 2 for v in vals) / n
        return {"mean": mean, "std": var ** 0.5, "median": vals[n // 2], "n": n}

    def save_risk(self, run_id, risk_index, level, layer_scores, features):
        self.conn.execute(
            "INSERT INTO risk_scores(run_id, ts, risk_index, level, layer_scores, features)"
            " VALUES (?,?,?,?,?,?)",
            (run_id, now_iso(), risk_index, level,
             json.dumps(layer_scores), json.dumps(features)),
        )
        self.conn.commit()

    def last_risk(self):
        row = self.conn.execute(
            "SELECT risk_index, level, ts FROM risk_scores ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return {"risk_index": row[0], "level": row[1], "ts": row[2]} if row else None

    def save_station(self, run_id, code, score, confidence, detail):
        self.conn.execute(
            "INSERT INTO station_scores(run_id, ts, station_code, crisis_score, confidence, detail)"
            " VALUES (?,?,?,?,?,?)",
            (run_id, now_iso(), code, score, confidence,
             json.dumps(detail, ensure_ascii=False)),
        )
        self.conn.commit()

    def ground_reports(self, station_code=None, limit=50):
        if station_code:
            rows = self.conn.execute(
                "SELECT ts, fuel_type, status, queue_note FROM ground_reports"
                " WHERE station_code=? ORDER BY id DESC LIMIT ?",
                (station_code, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT ts, fuel_type, status, queue_note FROM ground_reports"
                " ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [{"ts": r[0], "fuel_type": r[1], "status": r[2], "queue_note": r[3]}
                for r in rows]
