"""Per-station dry-out ordering: which SPBU is likely to run dry
FIRST.

A city-level warning tells citizens a crisis is coming; this answers
the question they actually ask - where. The ordering is a transparent
weighted estimate, documented here, never presented as certainty:

  45% current station crisis score (news + reports, latest scan)
  25% route distance from the supply entry: fuel enters Jember from
      the east (IT Tanjungwangi, Banyuwangi); stations farther west
      are refilled later in the tanker round, so they dry earlier
      and recover later (haversine from the Ketapang-side entry)
  20% historical vulnerability, hand-coded from the documented
      episodes: Sep 2026 queues started at Ahmad Yani and Teuku
      Umar; Oct 2026's worst station was Basuki Rahmat; Pertamina
      itself flags southern Jember as distance-vulnerable
  10% fresh citizen-report pressure on that station (<=24h)

Kenanga's geocode is flagged unreliable (see data/spbu_layout.json);
its distance component is computed anyway but marked low-trust in
the output detail.
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENTRY = (-8.2190, 114.3690)  # Banyuwangi side: supply entry point
VULNERABILITY = {
    "54.681.25": 0.90,  # Ahmad Yani: first queues Sep 2026
    "54.681.11": 0.85,  # Teuku Umar: first queues Sep 2026
    "53.681.35": 0.90,  # Basuki Rahmat: worst station Oct 2026
    "54.681.18": 0.60,  # Mastrip: campus demand spikes
    "54.681.12": 0.55, "54.681.10": 0.55,  # Mangli pair: far west
    "54.681.06": 0.50,  # Baratan: far north-east, own corridor
    "54.681.13": 0.45, "54.681.04": 0.45,
    "54.681.19": 0.50,  # Wolter Monginsidi: south side
    "51.681.23": 0.45,  # Kenanga
}


def _haversine_km(a, b):
    r = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = math.radians(b[0] - a[0])
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _latest_station_scores(store):
    rows = store.conn.execute(
        "SELECT station_code, crisis_score, detail FROM station_scores "
        "WHERE id IN (SELECT MAX(id) FROM station_scores "
        "GROUP BY station_code)").fetchall()
    out = {}
    for code, score, detail in rows:
        try:
            d = json.loads(detail or "{}")
        except Exception:
            d = {}
        out[code] = {"score": score, "detail": d}
    return out


def build_station_forecast(store):
    from .collectors.stations import load_stations, report_effect
    from datetime import datetime, timezone
    stations = load_stations()
    layout = {}
    lp = ROOT / "data" / "spbu_layout.json"
    if lp.exists():
        layout = json.loads(lp.read_text())["stations"]
    latest = _latest_station_scores(store)
    now = datetime.now(timezone.utc)
    dists = {}
    for st in stations:
        info = layout.get(st["code"]) or {}
        if "lat" in info and "lng" in info:
            dists[st["code"]] = _haversine_km(ENTRY, (info["lat"], info["lng"]))
    dmin, dmax = (min(dists.values()), max(dists.values())) if dists else (0, 1)
    rows = []
    for st in stations:
        code = st["code"]
        cur = latest.get(code, {"score": 0, "detail": {}})
        reports = store.ground_reports(code, limit=10)
        _f, _c, _o, n_fresh, _a = report_effect(reports, now)
        dist_norm = ((dists[code] - dmin) / (dmax - dmin)
                     if code in dists and dmax > dmin else 0.5)
        dry = (0.45 * (cur["score"] / 100.0)
               + 0.25 * dist_norm
               + 0.20 * VULNERABILITY.get(code, 0.45)
               + 0.10 * min(1.0, n_fresh / 2.0))
        rows.append({
            "code": code, "name": st["name"],
            "dry_risk": round(dry, 3),
            "components": {
                "current_score": cur["score"],
                "route_distance_km": (round(dists[code], 1)
                                      if code in dists else None),
                "route_norm": round(dist_norm, 2),
                "vulnerability": VULNERABILITY.get(code, 0.45),
                "fresh_reports": n_fresh,
                "coords_trust": ("rendah"
                                  if code == "51.681.23" else "normal"),
            },
        })
    rows.sort(key=lambda r: r["dry_risk"], reverse=True)
    return {"generated_from": "station_forecast v1 (45/25/20/10)",
            "ranking": rows}


def lay_line(forecast, top=3):
    names = [r["name"].replace("SPBU ", "")
             for r in forecast["ranking"][:top]]
    return ("Yang paling rawan kosong duluan: " + ", ".join(names) + ".")
