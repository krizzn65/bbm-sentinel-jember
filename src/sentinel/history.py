"""Historical learning layer: every documented Jember episode is a
teacher, not just a label.

Two uses, both live from day one:
1. Priors: duration and peak-offset statistics per pattern class
   (physical distribution failures lasted 7-9 days and peaked 2-4 days
   in; the pure panic episode peaked in ~1 day and resolved in 4).
2. Analog matching: the current trigger pattern (named triggers mined
   from today's news + physical signals) is compared against each
   closed episode's coded trigger vector. The closest analogue lends
   its peak offset to date the expected peak of the current episode:
   peak_date = current_episode_start + analogue_peak_offset.

The ongoing episode is always excluded from its own analogue search.
Anything not documented is null in the dataset; nothing is invented."""
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]

TRIGGER_KEYS = ["gumitir_closure", "gumitir_repair", "ketapang_congestion",
                "high_waves", "global_conflict_rumor", "tanker_schedule_change",
                "neighbor_shortage", "local_stockout", "panic_buying",
                "retailer_price_spike", "purchase_limit", "government_wfh"]
# Live trigger metric name (news collector) -> historical trigger key.
# Gumitir is handled separately below: a generic disruption headline is
# evidence of works/disruption (repair), while explicit closure wording
# is what made July 2025 different.
LIVE_MAP = {"ketapang_congestion": "ketapang_congestion",
            "high_waves": "high_waves",
            "tanker_or_geopolitics": "tanker_schedule_change",
            "panic_or_hoarding": "panic_buying",
            "neighbor_shortage": "neighbor_shortage"}


def load_episodes():
    p = ROOT / "data" / "historical_episodes.json"
    if not p.exists():
        return []
    return json.loads(p.read_text())["episodes"]


def _median(vals):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def priors(episodes=None):
    eps = [e for e in (episodes if episodes is not None else load_episodes())
           if e["status"] == "closed"]
    by_pattern = {}
    for e in eps:
        by_pattern.setdefault(e["pattern"], []).append(e)
    return {
        "episodes_closed": len(eps),
        "median_duration_days": _median([e["duration_days_elapsed"] for e in eps]),
        "median_peak_offset_days": _median([e["peak_offset_days"] for e in eps]),
        "by_pattern": {
            k: {"n": len(v),
                "median_duration_days": _median([e["duration_days_elapsed"] for e in v]),
                "median_peak_offset_days": _median([e["peak_offset_days"] for e in v])}
            for k, v in by_pattern.items()},
        "trigger_frequency": {
            k: round(sum(e["triggers"].get(k, 0) for e in eps) / len(eps), 2)
            for k in TRIGGER_KEYS} if eps else {},
    }


def current_pattern(store):
    """Binary trigger vector for right now, from the newest observations."""
    vec = {k: 0 for k in TRIGGER_KEYS}
    for layer in ("global", "regional", "lokal", "hulu"):
        for live, hist in LIVE_MAP.items():
            row = store.latest(f"news_{layer}_trigger_{live}")
            if row and row["value"] and row["value"] >= 1:
                vec[hist] = 1
    stock = store.latest("news_lokal_stockout_mentions")
    if stock and stock["value"] and stock["value"] >= 2:
        vec["local_stockout"] = 1
    queue = store.latest("news_lokal_queue_max_m")
    if queue and queue["value"] and queue["value"] >= 100:
        vec["local_stockout"] = 1
    closure = None
    disruption = None
    for layer in ("regional", "lokal"):
        c = store.latest(f"news_{layer}_trigger_gumitir_closure_specific")
        d = store.latest(f"news_{layer}_trigger_gumitir_disruption")
        if c and c["value"]:
            closure = c
        if d and d["value"]:
            disruption = d
    if closure:
        vec["gumitir_closure"] = 1
    elif disruption:
        vec["gumitir_repair"] = 1
    wave = store.latest("wave_max_72h_ketapang")
    if wave and wave["value"] and wave["value"] >= 1.5:
        vec["high_waves"] = 1
    fx = store.latest("usdidr_change_30d_pct")
    brent = store.latest("brent_change_7d_pct")
    if (fx and fx["value"] and fx["value"] >= 1.5) or (brent and brent["value"] and brent["value"] >= 4):
        vec["global_conflict_rumor"] = 1
    return vec


def _similarity(a, b):
    """Weighted Jaccard over trigger vectors; corridor/physical triggers
    weigh more because they decided every physical episode."""
    weights = {"gumitir_closure": 3, "gumitir_repair": 2, "ketapang_congestion": 3,
               "high_waves": 2, "tanker_schedule_change": 2, "neighbor_shortage": 2,
               "local_stockout": 2, "global_conflict_rumor": 1.5,
               "panic_buying": 1.5, "retailer_price_spike": 1,
               "purchase_limit": 0.5, "government_wfh": 1}
    num = den = 0.0
    for k in TRIGGER_KEYS:
        w = weights.get(k, 1)
        num += w * min(a.get(k, 0), b.get(k, 0))
        den += w * max(a.get(k, 0), b.get(k, 0))
    return round(num / den, 3) if den else 0.0


def episode_start(store, cfg):
    """First date of the current contiguous elevated period: walk the
    risk series backwards until readings drop calm for >48h."""
    tz = ZoneInfo(cfg.get("timezone", "Asia/Jakarta"))
    rows = store.conn.execute(
        "SELECT ts, risk_index FROM risk_scores ORDER BY ts DESC").fetchall()
    if not rows:
        return None
    start = None
    prev_ts = None
    for ts, risk in rows:
        t = datetime.fromisoformat(ts).astimezone(tz)
        if prev_ts and (prev_ts - t) > timedelta(hours=48):
            break
        if risk >= 35:
            start = t.date()
            prev_ts = t
        elif start is not None:
            break
        else:
            prev_ts = t
    return start


def analog_forecast(store, cfg):
    eps = [e for e in load_episodes() if e["status"] == "closed"]
    if not eps:
        return None
    vec = current_pattern(store)
    if not any(vec.values()):
        return {"current_pattern": vec, "analogue": None, "similarity": 0.0,
                "expected_peak_date": None, "expected_peak_date_id": None,
                "priors": priors(eps)}
    scored = sorted(
        ({"episode": e, "similarity": _similarity(vec, e["triggers"])} for e in eps),
        key=lambda x: x["similarity"], reverse=True)
    best = scored[0]
    start = episode_start(store, cfg)
    peak_date = None
    if start and best["similarity"] >= 0.25 and best["episode"]["peak_offset_days"] is not None:
        peak_date = start + timedelta(days=int(best["episode"]["peak_offset_days"]))
    from .forecast import fmt_date_id
    return {
        "current_pattern": vec,
        "analogue": {"episode_id": best["episode"]["id"],
                     "label": best["episode"]["label"],
                     "pattern": best["episode"]["pattern"],
                     "peak_offset_days": best["episode"]["peak_offset_days"],
                     "duration_days": best["episode"]["duration_days_elapsed"]},
        "similarity": best["similarity"],
        "ranking": [{"episode_id": s["episode"]["id"],
                     "similarity": s["similarity"]} for s in scored],
        "episode_start": start.isoformat() if start else None,
        "expected_peak_date": peak_date.isoformat() if peak_date else None,
        "expected_peak_date_id": (fmt_date_id(datetime(peak_date.year, peak_date.month, peak_date.day))
                                  if peak_date else None),
        "priors": priors(eps),
    }
