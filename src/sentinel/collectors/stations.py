"""Per-station crisis estimation for the agreed scope only: Jember city +
campus area (Kaliwates, Sumbersari, Patrang).

Pertamina does not publish per-station stock via a public API, so a station
score is an estimate built from independent, checkable signals:
  - targeted news/RSS mentions naming the station or its street (24-72h)
  - phrase mining in those titles: stock-out words, queue length, wait time
  - ground reports sent by the user / friends through this chat (highest
    weight, stored in ground_reports)
Each station gets crisis_score 0-100 and confidence 0-1 from source count
and recency, so a low-confidence number is never presented as fact."""
import json
from pathlib import Path

from .news import fetch_rss, mine_phrases

ROOT = Path(__file__).resolve().parents[3]


def load_stations():
    return json.loads((ROOT / "data" / "spbu_kota_jember.json").read_text())["stations"]


_FLOOR = {"kosong": 85.0, "habis": 85.0, "antre_panjang": 70.0,
          "antre panjang": 70.0, "terbatas": 50.0}
_FUEL_OVERRIDE = {"kosong": "kosong", "habis": "kosong",
                  "antre_panjang": "antre", "antre panjang": "antre"}


def report_effect(reports, now):
    """Ground-truth effect of citizen reports on one station.

    A report is the strongest signal this system has, but it decays:
    full authority for 3h, 85% of its floor up to 12h, 60% up to 24h,
    ignored after that. A fresh 'normal' report caps the score (the
    queue is gone even if old news still circulates). Fuel-specific
    overrides apply while the report is <=6h old. Returns
    (score_floor, score_cap, fuel_overrides, fresh_count, latest_age_h).
    """
    from datetime import datetime, timezone
    floor, cap, overrides, fresh = 0.0, None, {}, 0
    latest_age = None
    for r in reports:
        try:
            ts = datetime.fromisoformat(r["ts"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = (now - ts).total_seconds() / 3600.0
        except Exception:
            continue
        if age > 24:
            continue
        fresh += 1
        latest_age = age if latest_age is None else min(latest_age, age)
        status = (r["status"] or "").lower()
        factor = 1.0 if age <= 3 else (0.85 if age <= 12 else 0.6)
        if status in _FLOOR:
            floor = max(floor, _FLOOR[status] * factor)
        elif status == "normal" and age <= 3:
            cap = 25.0 if cap is None else min(cap, 25.0)
        fuel = r.get("fuel_type") or ""
        if age <= 6 and status in _FUEL_OVERRIDE and fuel and fuel != "umum":
            overrides[fuel] = {"status": _FUEL_OVERRIDE[status],
                               "source": "laporan warga"}
    return floor, cap, overrides, fresh, latest_age


def _locality_tokens(st):
    """Distinctive place words for one station (street/district),
    used to prove a headline is really about THIS station."""
    toks = set()
    for a in list(st.get("aliases", [])) + [st["name"]]:
        s = a.lower().replace("spbu", " ").replace(st["code"], " ")
        for w in s.split():
            if len(w) >= 5 and w != "jember":
                toks.add(w)
        phrase = " ".join(s.split())
        if len(phrase) >= 6 and "jember" not in phrase:
            toks.add(phrase)
    return toks


def gate_fuel_status(fuel_status, titles, tokens):
    """Precision gate (owner's rule: never claim a stockout loosely).

    The per-station news query uses OR branches, so loosely related
    stories leak in - a Probolinggo Pertalite story once flipped
    Mastrip's Pertalite to 'kosong'. A station-level 'kosong' now
    survives only when a title that names THIS station/area also
    carries a stockout word for that fuel. Otherwise the status is
    downgraded to 'disebut' (mentioned) and flagged unverified.
    City-wide stockout headlines still feed the CITY fuel summary;
    they just no longer pin 'kosong' on a specific station."""
    from .news import STOCKOUT_WORDS
    out = {}
    for fuel, info in fuel_status.items():
        info = dict(info)
        if info.get("status") == "kosong":
            seg = [t for t in titles if fuel.lower() in t.lower()]
            hit = any(any(tok in t.lower() for tok in tokens)
                      and any(w in t.lower() for w in STOCKOUT_WORDS)
                      for t in seg)
            if not hit:
                info["status"] = "disebut"
                info["unverified"] = True
        out[fuel] = info
    return out


def _station_titles(st):
    titles, seen = [], set()
    for alias in st["aliases"][:2]:
        try:
            items = fetch_rss(f'"{alias}" antre OR BBM OR bensin OR Pertalite')
        except Exception:
            continue
        for it in items:
            if it["title"] not in seen:
                seen.add(it["title"])
                titles.append(it["title"])
    return titles


def collect(store, run_id, cfg):
    from concurrent.futures import ThreadPoolExecutor

    stations = load_stations()
    with ThreadPoolExecutor(max_workers=6) as pool:
        all_titles = list(pool.map(_station_titles, stations))
    results = []
    for st, titles in zip(stations, all_titles):
        mined = mine_phrases(titles)
        score = 0.0
        score += min(40, mined["queue_mentions"] * 8)
        score += min(35, mined["stockout_mentions"] * 12)
        score += min(15, mined["queue_max_m"] / 100.0)
        score += min(10, mined["wait_max_h"] * 3)
        from datetime import datetime, timezone
        reports = store.ground_reports(st["code"], limit=10)
        floor, cap, overrides, n_fresh, latest_age = report_effect(
            reports, datetime.now(timezone.utc))
        if floor:
            score = max(score, floor)
        if cap is not None:
            score = min(score, cap)
        fuel_status = gate_fuel_status(
            dict(mined["fuel_status"]), titles, _locality_tokens(st))
        fuel_status.update(overrides)
        agreeing = sum(1 for r in reports
                       if (r["status"] or "").lower() in _FLOOR)
        sources = len(titles) + (2 if n_fresh else 0)
        confidence = min(1.0, 0.25 + 0.15 * sources) if sources else 0.1
        if n_fresh >= 2 and agreeing >= 2:
            confidence = min(1.0, confidence + 0.2)
        detail = {"name": st["name"], "code": st["code"], "zone": st["zone"],
                  "district": st["district"], "mentions": len(titles),
                  "queue_max_m": mined["queue_max_m"],
                  "wait_max_h": mined["wait_max_h"],
                  "fuel_status": fuel_status,
                  "report_fresh_count": n_fresh,
                  "report_latest_age_h": (round(latest_age, 1)
                                          if latest_age is not None else None),
                  "ground_reports": reports[:2], "sample_titles": titles[:3]}
        store.save_station(run_id, st["code"], round(score, 1), round(confidence, 2),
                           detail)
        store.observe(run_id, "lokal", "station-scan", f"station_{st['code']}_score",
                      round(score, 1), meta={"confidence": confidence})
        results.append({"station": st, "score": round(score, 1),
                        "confidence": round(confidence, 2), "detail": detail})
    results.sort(key=lambda r: r["score"], reverse=True)
    return results
