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
        reports = store.ground_reports(st["code"], limit=5)
        fresh = [r for r in reports]
        if fresh:
            worst = fresh[0]["status"].lower()
            if worst in ("kosong", "habis"):
                score = max(score, 85)
            elif worst in ("antre_panjang", "antre panjang"):
                score = max(score, 70)
            elif worst in ("terbatas",):
                score = max(score, 50)
        sources = len(titles) + (2 if fresh else 0)
        confidence = min(1.0, 0.25 + 0.15 * sources) if sources else 0.1
        detail = {"name": st["name"], "code": st["code"], "zone": st["zone"],
                  "district": st["district"], "mentions": len(titles),
                  "queue_max_m": mined["queue_max_m"],
                  "wait_max_h": mined["wait_max_h"],
                  "fuel_status": mined["fuel_status"],
                  "ground_reports": fresh[:2], "sample_titles": titles[:3]}
        store.save_station(run_id, st["code"], round(score, 1), round(confidence, 2),
                           detail)
        store.observe(run_id, "lokal", "station-scan", f"station_{st['code']}_score",
                      round(score, 1), meta={"confidence": confidence})
        results.append({"station": st, "score": round(score, 1),
                        "confidence": round(confidence, 2), "detail": detail})
    results.sort(key=lambda r: r["score"], reverse=True)
    return results
