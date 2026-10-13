#!/usr/bin/env python3
"""Backfill archival quantitative data around every documented episode.

For each episode in data/historical_episodes.json this fetches, for the
window [start-14d, end+3d] (ongoing episodes: up to today):
  - Brent daily closes (FRED CSV, one fetch) + 7d change
  - USD/IDR daily rates (Frankfurter range) + ~30d change
  - Gumitir daily rainfall (Open-Meteo archive)
  - Ketapang + south-Jember daily max wave height (Open-Meteo marine)
and writes data/historical_windows.json. The point: the learning layer
must see what the physical/market world looked like BEFORE each crisis,
not only during it. News archives cannot be backfilled reliably from
Google News RSS, so news-derived features exist only from go-live onward;
that gap is recorded, not papered over."""
import csv
import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sentinel.http_util import get_json, get_text  # noqa: E402

LOC = {"gumitir": (-8.35, 113.93), "ketapang": (-8.14, 114.57),
       "south": (-8.45, 113.45)}


def _stooq_brent_daily():
    text = get_text("https://stooq.com/q/d/l/?s=brent.f&i=d",
                    timeout=45, retries=1)
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        try:
            out[row["Date"]] = float(row["Close"])
        except Exception:
            continue
    if len(out) < 100:
        raise ValueError("stooq daily brent: too few rows")
    return out


def _fred_brent():
    text = get_text("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU",
                    timeout=30, retries=2)
    out = {}
    for line in text.strip().splitlines()[1:]:
        p = line.split(",")
        if len(p) == 2 and p[1] not in (".", ""):
            out[p[0]] = float(p[1])
    return out


def _frankfurter(start, end):
    url = f"https://api.frankfurter.app/{start}..{end}?from=USD&to=IDR"
    data = get_json(url, timeout=30, retries=2)
    return {d: r["IDR"] for d, r in sorted(data["rates"].items())}


def _archive_daily(kind, lat, lon, start, end, var):
    if kind == "archive":
        url = ("https://archive-api.open-meteo.com/v1/archive"
               f"?latitude={lat}&longitude={lon}&start_date={start}&end_date={end}"
               f"&daily={var}&timezone=Asia%2FJakarta")
    else:
        url = ("https://marine-api.open-meteo.com/v1/marine"
               f"?latitude={lat}&longitude={lon}&start_date={start}&end_date={end}"
               f"&daily={var}&timezone=Asia%2FJakarta")
    data = get_json(url, timeout=30, retries=2)
    daily = data.get("daily") or {}
    times = daily.get("time") or []
    vals = daily.get(var) or []
    return {t: v for t, v in zip(times, vals) if v is not None}


def _pct(series, day, lag_days):
    if day not in series:
        return None
    target = (date.fromisoformat(day) - timedelta(days=lag_days)).isoformat()
    past = None
    for d in sorted(series):
        if d <= target:
            past = series[d]
        else:
            break
    if past in (None, 0):
        return None
    return round((series[day] / past - 1) * 100, 2)


def main():
    episodes = json.loads((ROOT / "data" / "historical_episodes.json").read_text())["episodes"]
    today = date.today()
    brent = {}
    for name, fn in (("stooq-daily", _stooq_brent_daily), ("fred", _fred_brent)):
        try:
            brent = fn()
            print(f"brent series: {name}, {len(brent)} hari")
            break
        except Exception as exc:  # flaky sources; Brent stays empty, not fatal
            print(f"WARN brent via {name} failed: {exc}")
    windows = []
    for ep in episodes:
        start = date.fromisoformat(ep["start"])
        end = date.fromisoformat(ep["end"]) if ep["end"] else today
        w_start = start - timedelta(days=14)
        w_end = min(end + timedelta(days=3), today)  # archive API rejects future dates
        def safe(fn, default):
            try:
                return fn()
            except Exception as exc:
                print(f"WARN {ep['id']}: {exc}")
                return default

        fx = safe(lambda: _frankfurter((w_start - timedelta(days=35)).isoformat(),
                                       w_end.isoformat()), {})
        rain = safe(lambda: _archive_daily("archive", *LOC["gumitir"],
                                           w_start.isoformat(), w_end.isoformat(),
                                           "precipitation_sum"), {})
        wave_k = safe(lambda: _archive_daily("marine", *LOC["ketapang"],
                                             w_start.isoformat(), w_end.isoformat(),
                                             "wave_height_max"), {})
        wave_s = safe(lambda: _archive_daily("marine", *LOC["south"],
                                             w_start.isoformat(), w_end.isoformat(),
                                             "wave_height_max"), {})
        days = []
        cur = w_start
        while cur <= w_end:
            ds = cur.isoformat()
            days.append({
                "date": ds,
                "days_from_start": (cur - start).days,
                "in_episode": start <= cur <= end,
                "brent_close": brent.get(ds),
                "brent_change_7d_pct": _pct(brent, ds, 7),
                "usdidr": fx.get(ds),
                "usdidr_change_30d_pct": _pct(fx, ds, 30),
                "rain_gumitir_mm": rain.get(ds),
                "wave_ketapang_max_m": wave_k.get(ds),
                "wave_south_max_m": wave_s.get(ds),
            })
            cur += timedelta(days=1)
        windows.append({"episode_id": ep["id"], "window_start": w_start.isoformat(),
                        "window_end": w_end.isoformat(), "days": days})
        print(f"{ep['id']}: {len(days)} hari, "
              f"brent {sum(1 for x in days if x['brent_close'] is not None)}, "
              f"fx {sum(1 for x in days if x['usdidr'] is not None)}, "
              f"rain {sum(1 for x in days if x['rain_gumitir_mm'] is not None)}, "
              f"wave {sum(1 for x in days if x['wave_ketapang_max_m'] is not None)}")
    out = {"generated_at": today.isoformat(),
           "note": "Arsip kuantitatif per episode. News-derived features tidak "
                   "bisa di-backfill dari Google News RSS dan sengaja dikosongkan.",
           "windows": windows}
    (ROOT / "data" / "historical_windows.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1))
    print("wrote data/historical_windows.json")


if __name__ == "__main__":
    main()
