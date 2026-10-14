"""Dated crisis forecast: "krisis diperkirakan memuncak hari X, tanggal Y".

Method (all deterministic and auditable; the ML layer in train.py takes
over weight calibration once enough labelled days exist):
1. Robust base: the median of the newest five risk readings, so one
   rate-limited or unusually complete run cannot jerk the forecast.
2. Trend: least-squares slope of the hourly risk index over the last 72h,
   damped with horizon and pulled back toward the robust historical
   median (mean reversion), because Jember episodes spike and resolve.
   The slope is multiplied by a data-trust factor based on the actual
   time span observed: a handful of runs over a few minutes carries
   almost no trend information and must not be extrapolated for a week.
3. Fast-signal momentum: slope of the lokal+regional layer scores over
   the same window, weighted heavier for the first 3 days and subject
   to the same trust factor and hard contribution caps.
3. Calendar: Indonesian holidays (data/holidays_id.json; fixed dates
   verified via Nager.Date, movable feasts estimated) inside a
   [H-2, H+1] window add a travel-surge boost, major feasts more;
   weekends add a small boost; operator-known events from config
   (e.g. a scheduled Gumitir closure) add their configured impact.
4. Every daily forecast is stored. Each new run verifies yesterday's
   forecast against the day's actual peak risk and keeps a running MAE,
   which is reported with the forecast so its precision is measured,
   not claimed."""
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import history

ROOT = Path(__file__).resolve().parents[2]
WEEKDAYS_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
MONTHS_ID = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
             "Agustus", "September", "Oktober", "November", "Desember"]


def _ols_slope(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den else 0.0


def _level(v):
    if v >= 80:
        return "MERAH"
    if v >= 60:
        return "ORANYE"
    if v >= 40:
        return "KUNING"
    return "HIJAU"


def fmt_date_id(d):
    return f"{WEEKDAYS_ID[d.weekday()]}, {d.day} {MONTHS_ID[d.month - 1]} {d.year}"


def _load_holidays():
    p = ROOT / "data" / "holidays_id.json"
    if p.exists():
        return json.loads(p.read_text())
    return {}


def _calendar_boost(day, holidays, cfg):
    fc = cfg.get("forecast", {})
    boost = 0.0
    reasons = []
    for delta in range(-1, 3):  # holiday in [day-2, day+1] window
        h = holidays.get((day + timedelta(days=delta)).isoformat())
        if h:
            b = fc.get("holiday_major_boost", 10) if h.get("major") else fc.get("holiday_minor_boost", 5)
            if b > boost:
                boost = b
                reasons = [f"libur {h['name']}"]
            break
    if day.weekday() >= 5:
        boost += fc.get("weekend_boost", 3)
        reasons.append("akhir pekan")
    for ev in cfg.get("known_events", []):
        try:
            ev_day = datetime.fromisoformat(ev["date"]).date()
        except Exception:
            continue
        if abs((ev_day - day).days) <= 1:
            boost += float(ev.get("impact", 10))
            reasons.append(ev.get("name", "kejadian terjadwal"))
    # Local demand pulse (payday window, pasaran market cycle,
    # harvest seasons, campus terms) - see calendar_id.py; capped
    # inside demand_factors so it can tilt a day, never manufacture
    # a crisis on its own.
    from .calendar_id import demand_factors
    d_boost, d_reasons = demand_factors(day)
    boost += d_boost
    reasons += d_reasons
    return boost, reasons


def ensure_tables(store):
    store.conn.execute(
        "CREATE TABLE IF NOT EXISTS forecasts (id INTEGER PRIMARY KEY, "
        "made_at TEXT, target_date TEXT, pred_index REAL, low REAL, "
        "high REAL, crisis_prob REAL, reasons TEXT)")
    store.conn.execute(
        "CREATE TABLE IF NOT EXISTS forecast_checks (id INTEGER PRIMARY KEY, "
        "checked_at TEXT, target_date TEXT, pred_index REAL, actual_peak REAL, "
        "abs_error REAL)")
    store.conn.commit()


def verify_past(store, tz):
    """Compare the newest forecast made before each past target date with
    that date's actual peak risk. Returns running MAE over checked days."""
    ensure_tables(store)
    rows = store.conn.execute(
        "SELECT target_date, pred_index FROM forecasts ORDER BY made_at").fetchall()
    by_date = {}
    for target, pred in rows:
        by_date[target] = pred  # keep the last forecast made for the date
    today = datetime.now(tz).date()
    checked = {r[0] for r in store.conn.execute("SELECT target_date FROM forecast_checks")}
    for target, pred in by_date.items():
        d = datetime.fromisoformat(target).date()
        if d >= today or target in checked:
            continue
        day_rows = store.conn.execute(
            "SELECT risk_index FROM risk_scores WHERE substr(ts,1,10)=?",
            (target,)).fetchall()
        if not day_rows:
            continue
        actual = max(r[0] for r in day_rows)
        store.conn.execute(
            "INSERT INTO forecast_checks (checked_at, target_date, pred_index,"
            " actual_peak, abs_error) VALUES (?,?,?,?,?)",
            (datetime.now(tz).isoformat(timespec="seconds"), target, pred,
             actual, abs(pred - actual)))
    store.conn.commit()
    errs = [r[0] for r in store.conn.execute("SELECT abs_error FROM forecast_checks")]
    return {"checked_days": len(errs),
            "mae": round(sum(errs) / len(errs), 1) if errs else None}


def build_forecast(store, cfg, current_risk, out_path=None):
    tz = ZoneInfo(cfg.get("timezone", "Asia/Jakarta"))
    ensure_tables(store)
    now = datetime.now(tz)
    rows = store.conn.execute(
        "SELECT ts, risk_index, layer_scores FROM risk_scores "
        "ORDER BY ts DESC LIMIT 504").fetchall()
    rows = list(reversed(rows))
    series = [(datetime.fromisoformat(r[0]), r[1],
               json.loads(r[2] or "{}")) for r in rows]
    if not series:
        return None
    def _median(vals):
        vals = sorted(vals)
        n = len(vals)
        return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2

    baseline = _median([s[1] for s in series])
    robust_base = _median([s[1] for s in series[-5:]])
    recent = [s for s in series if (now - s[0]).total_seconds() <= 72 * 3600]
    if len(recent) < 3:
        recent = series[-min(len(series), 12):]
    span_hours = max(0.0, (recent[-1][0] - recent[0][0]).total_seconds() / 3600)
    # Full trust needs three days of hourly observations. The floor keeps
    # the model responsive without pretending minutes of data prove a
    # week-long trajectory.
    trust = max(0.08, min(1.0, span_hours / 72.0))
    xs = [(s[0] - recent[0][0]).total_seconds() / 86400 for s in recent]
    raw_slope_day = _ols_slope(xs, [s[1] for s in recent])
    slope_day = max(-15.0, min(15.0, raw_slope_day)) * trust
    fast = [0.6 * (s[2].get("lokal") or 0) + 0.4 * (s[2].get("regional") or 0)
            for s in recent]
    fast_now = fast[-1] if fast else 0.0
    raw_fast_slope = _ols_slope(xs, fast) if len(fast) >= 3 else 0.0
    fast_slope = max(-25.0, min(25.0, raw_fast_slope)) * trust
    holidays = _load_holidays()
    analog = None
    try:
        analog = history.analog_forecast(store, cfg)
    except Exception:
        analog = None
    analog_boost_by_date = {}
    if analog and analog.get("analogue") and analog.get("similarity", 0) >= 0.25 \
            and analog.get("episode_start"):
        start_d = date.fromisoformat(analog["episode_start"])
        offset = analog["analogue"]["peak_offset_days"] or 0
        for h in range(1, int(cfg.get("forecast", {}).get("horizon_days", 7)) + 1):
            d = (now + timedelta(days=h)).date()
            dist = (d - start_d).days - offset
            analog_boost_by_date[d.isoformat()] = (
                14.0 * analog["similarity"] * math.exp(-(dist ** 2) / (2 * 1.6 ** 2)))
    horizon = int(cfg.get("forecast", {}).get("horizon_days", 7))
    days = []
    for h in range(1, horizon + 1):
        day = (now + timedelta(days=h)).date()
        damp = 0.92 ** h
        trend = max(-12.0, min(12.0, slope_day * h * damp))
        momentum = max(-8.0, min(8.0, fast_slope * min(h, 3) * 0.35 * damp))
        reversion = (baseline - robust_base) * (1 - 0.88 ** h)
        boost, reasons = _calendar_boost(day, holidays, cfg)
        ab = analog_boost_by_date.get(day.isoformat(), 0.0)
        if ab >= 4:
            reasons = reasons + [f"pola mirip episode {analog['analogue']['label']}"]
        pred = max(0.0, min(100.0, robust_base + trend + momentum + reversion + boost + ab))
        spread = (7 + 3.2 * h) + (1 - trust) * 10
        days.append({
            "date": day.isoformat(),
            "date_id": fmt_date_id(datetime(day.year, day.month, day.day)),
            "pred_index": round(pred, 1),
            "low": round(max(0.0, pred - spread), 1),
            "high": round(min(100.0, pred + spread), 1),
            "level": _level(pred),
            "crisis_prob": round(100 / (1 + math.exp(-(pred - 60) / 8))),
            "reasons": reasons,
        })
    peak = max(days, key=lambda d: d["pred_index"])
    first_cross = next((d for d in days if d["pred_index"] >= 60), None)
    made = now.isoformat(timespec="seconds")
    for d in days:
        store.conn.execute(
            "INSERT INTO forecasts (made_at, target_date, pred_index, low,"
            " high, crisis_prob, reasons) VALUES (?,?,?,?,?,?,?)",
            (made, d["date"], d["pred_index"], d["low"], d["high"],
             d["crisis_prob"], json.dumps(d["reasons"], ensure_ascii=False)))
    store.conn.commit()
    checks = verify_past(store, tz)
    out = {"made_at": made, "base_risk": round(robust_base, 1),
           "latest_risk": current_risk,
           "slope_per_day_effective": round(slope_day, 2),
           "slope_per_day_raw_capped": round(max(-15.0, min(15.0, raw_slope_day)), 2),
           "fast_layer_now": round(fast_now, 1),
           "fast_slope_effective": round(fast_slope, 2),
           "baseline_median": round(baseline, 1),
           "samples": len(series),
           "recent_samples": len(recent),
           "observed_span_hours": round(span_hours, 2),
           "data_trust": round(trust, 3),
           "alert_ready": bool((trust >= 0.35 and len(recent) >= 24)
                               or (analog and analog.get("similarity", 0) >= 0.45
                                   and robust_base >= 35)),
           "analog": ({"episode_id": analog["analogue"]["episode_id"],
                       "label": analog["analogue"]["label"],
                       "pattern": analog["analogue"]["pattern"],
                       "similarity": analog["similarity"],
                       "episode_start": analog["episode_start"],
                       "expected_peak_date": analog["expected_peak_date"],
                       "expected_peak_date_id": analog["expected_peak_date_id"],
                       "analogue_duration_days": analog["analogue"]["duration_days"]}
                      if analog and analog.get("analogue") else None),
           "historical_priors": analog["priors"] if analog else None,
           "days": days,
           "peak": peak,
           "predicted_crisis_date": first_cross["date"] if first_cross else None,
           "predicted_crisis_date_id": first_cross["date_id"] if first_cross else None,
           "verification": checks}
    if out_path is not None:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def lay_summary(fc):
    """One or two plain-language sentences for the human bulletin/alert.

    A dated call is only surfaced when the observation window is mature
    enough (alert_ready). Before that the forecast remains an internal
    calibration artifact, not a promise to the user."""
    if not fc:
        return None
    peak = fc["peak"]
    if not fc.get("alert_ready"):
        return None
    analog = fc.get("analog")
    if analog and analog.get("similarity", 0) >= 0.45 and analog.get("expected_peak_date_id"):
        return (f"Perkiraan dari pola krisis sebelumnya: antrean "
                f"kemungkinan memuncak pada {analog['expected_peak_date_id']}. "
                f"Kalau bisa, isi bensin sebelum tanggal itu.")
    if fc["predicted_crisis_date"] and peak["pred_index"] >= 60:
        return (f"Perkiraan: antrean kemungkinan memuncak pada "
                f"{fc['predicted_crisis_date_id']}. Kalau bisa, isi bensin "
                f"sebelum tanggal itu.")
    if peak["pred_index"] >= 50:
        return (f"Perkiraan: hari paling ramai kemungkinan "
                f"{peak['date_id']}. Sisanya cenderung lebih tenang.")
    return None
