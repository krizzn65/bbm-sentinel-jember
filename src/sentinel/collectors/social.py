"""Social-media listening intake (agent-fed).

The Python pipeline cannot call social platforms directly (no public
APIs for X/TikTok/IG search), so listening is split in two: an agent
(the 3-hourly alert worker, which has social search tools) sweeps
public posts about Jember SPBU queues and writes
alerts/social_signals.json; this collector ingests that file while it
is fresh (<=6h) as a local-layer signal and archives it in the
social_signals table. Only PUBLIC posts about the queues are used -
counts, timestamps, station names - never commenter identities or
private data. Stale or missing file = no signal (fail-soft), never
an error and never fabricated numbers.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SIGNALS_PATH = ROOT / "alerts" / "social_signals.json"
MAX_AGE_H = 6


def collect(store, run_id, cfg):
    if not SIGNALS_PATH.exists():
        return {"status": "no_signals_file"}
    try:
        data = json.loads(SIGNALS_PATH.read_text())
        ts = datetime.fromisoformat(data["ts"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
    except Exception:
        return {"status": "signals_unreadable"}
    if age_h > MAX_AGE_H:
        return {"status": "signals_stale", "age_h": round(age_h, 1)}
    queue_posts = int(data.get("queue_posts") or 0)
    store.observe(run_id, "lokal", "social-listening",
                  "social_queue_posts_24h", queue_posts)
    store.observe(run_id, "lokal", "social-listening",
                  "social_posts_found_24h", int(data.get("posts_found") or 0))
    store.conn.execute(
        "INSERT INTO social_signals(ts, platform, posts_found, queue_posts,"
        " stations_mentioned, detail) VALUES (?,?,?,?,?,?)",
        (data["ts"], data.get("platform", "campuran"),
         int(data.get("posts_found") or 0), queue_posts,
         json.dumps(data.get("stations_mentioned") or []),
         json.dumps(data.get("samples") or [], ensure_ascii=False)))
    store.conn.commit()
    return {"status": "ok", "queue_posts": queue_posts,
            "posts_found": int(data.get("posts_found") or 0),
            "stations_mentioned": data.get("stations_mentioned") or [],
            "age_h": round(age_h, 1)}
