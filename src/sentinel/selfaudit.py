"""Self-audit: the system grades its own yesterday, in public numbers.

Every crisis bulletin names stations to avoid and stations that are
still fine. The next day those claims can be checked against the
newest station scores:

  - precision of the avoid list: share of yesterday's "hindari"
    stations whose score today is still >= 30 (the warning held)
  - stability of the fine list: share of yesterday's "lancar"
    stations still < 30 today (they really were safe)

A station that recovered overnight does not make yesterday's
warning a lie - fuel arrives, queues clear - so the metric is
reported as what it is (how long warnings stayed true), alongside
the dated-forecast MAE from forecast_checks. The rolling result
lands in alerts/self_audit.json where anyone can read how honest
the machine has been.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "alerts" / "bulletin_log.jsonl"


def append_bulletin_log(day_iso, avoid, queueing, fine, fuels_empty):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    row = {"date": day_iso, "avoid": avoid, "queueing": queueing,
           "fine": fine, "fuels_empty": fuels_empty,
           "logged_at": datetime.now(timezone.utc).isoformat()}
    with LOG.open("a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _log_by_date():
    if not LOG.exists():
        return {}
    out = {}
    for line in LOG.read_text().splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        out[row["date"]] = row  # last entry of the day wins
    return out


def _name_to_code(name):
    from .collectors.stations import load_stations
    for st in load_stations():
        plain = st["name"].replace("SPBU ", "")
        if plain in name or name.replace(" (laporan warga)", "") == plain:
            return st["code"]
    return None


def grade_yesterday(store, today_iso):
    """Grade the most recent logged day strictly before today."""
    logs = _log_by_date()
    past = sorted(d for d in logs if d < today_iso)
    if not past:
        return {"status": "belum ada buletin kemarin untuk dinilai"}
    day = past[-1]
    entry = logs[day]
    scores = {}
    for code, score, _d in store.conn.execute(
            "SELECT station_code, crisis_score, detail FROM "
            "station_scores WHERE id IN (SELECT MAX(id) FROM "
            "station_scores GROUP BY station_code)"):
        scores[code] = score
    def verdict(names, still_bad):
        hits = total = 0
        detail = {}
        for n in names:
            code = _name_to_code(n)
            if code is None or code not in scores:
                continue
            total += 1
            bad = scores[code] >= 30
            detail[n] = scores[code]
            if bad == still_bad:
                hits += 1
        return hits, total, detail
    ah, at, ad = verdict(entry.get("avoid", []), True)
    fh, ft, fd = verdict(entry.get("fine", []), False)
    result = {
        "graded_date": day,
        "avoid_precision": (round(ah / at, 2) if at else None),
        "avoid_detail": ad,
        "fine_stability": (round(fh / ft, 2) if ft else None),
        "fine_detail": fd,
        "note": ("Sebuah SPBU yang pulih semalam tidak membuat "
                 "peringatan kemarin salah; angka ini mengukur "
                 "berapa lama peringatan itu tetap benar."),
    }
    store.conn.execute(
        "INSERT INTO self_audit(ts, graded_date, avoid_precision,"
        " fine_stability, detail) VALUES (?,?,?,?,?)",
        (datetime.now(timezone.utc).isoformat(), day,
         result["avoid_precision"], result["fine_stability"],
         json.dumps(result, ensure_ascii=False)))
    store.conn.commit()
    return result


def run(store, cfg):
    tz = ZoneInfo(cfg.get("timezone", "Asia/Jakarta"))
    today = datetime.now(tz).date().isoformat()
    graded = None
    latest_graded = store.conn.execute(
        "SELECT MAX(graded_date) FROM self_audit").fetchone()[0]
    logs = _log_by_date()
    past = sorted(d for d in logs if d < today)
    if past and past[-1] != latest_graded:
        graded = grade_yesterday(store, today)
    rows = store.conn.execute(
        "SELECT graded_date, avoid_precision, fine_stability "
        "FROM self_audit ORDER BY graded_date").fetchall()
    try:
        mae = store.conn.execute(
            "SELECT AVG(abs(predicted_peak - actual_peak)), COUNT(*) "
            "FROM forecast_checks").fetchone()
    except Exception:
        mae = (None, 0)  # forecast module has not created it yet
    report = {
        "graded_days": len(rows),
        "history": [{"date": d, "avoid_precision": ap,
                     "fine_stability": fs} for d, ap, fs in rows],
        "mean_avoid_precision": (round(sum(r[1] for r in rows if r[1]
                                           is not None)
                                       / max(1, sum(1 for r in rows
                                                    if r[1] is not None)), 2)
                                 if rows else None),
        "mean_fine_stability": (round(sum(r[2] for r in rows if r[2]
                                          is not None)
                                      / max(1, sum(1 for r in rows
                                                   if r[2] is not None)), 2)
                                if rows else None),
        "forecast_peak_mae": (round(mae[0], 1) if mae and mae[0]
                              is not None else None),
        "forecast_checks_done": (mae[1] if mae else 0),
        "latest_grade": graded,
    }
    (ROOT / "alerts" / "self_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1))
    return report
