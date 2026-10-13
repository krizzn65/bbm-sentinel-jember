"""Quantitative market signals: Brent crude (Stooq daily bars, FRED fallback)
and USD/IDR (Frankfurter/ECB series)."""
import csv
import io
from datetime import date, timedelta

from ..http_util import get_json, get_text


def _stooq_brent():
    text = get_text("https://stooq.com/q/l/?s=brent.f&f=sd2t2ohlcv&h&e=csv",
                    timeout=15, retries=2)
    rows = list(csv.DictReader(io.StringIO(text)))
    rows = [r for r in rows if r.get("Close") not in (None, "", "N/D")]
    if len(rows) < 8:
        raise ValueError("stooq brent: too few rows")
    closes = [float(r["Close"]) for r in rows]
    latest, prev = closes[-1], closes[-2]
    ref7 = closes[-8]
    return {
        "brent_close_usd": latest,
        "brent_change_1d_pct": (latest / prev - 1) * 100,
        "brent_change_7d_pct": (latest / ref7 - 1) * 100,
        "as_of": rows[-1].get("Date", ""),
    }


def _fred_brent():
    text = get_text("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU",
                    timeout=15, retries=2)
    vals = []
    for line in text.strip().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) == 2 and parts[1] not in (".", ""):
            vals.append((parts[0], float(parts[1])))
    if len(vals) < 8:
        raise ValueError("fred brent: too few rows")
    latest, ref7 = vals[-1][1], vals[-8][1]
    return {
        "brent_close_usd": latest,
        "brent_change_7d_pct": (latest / ref7 - 1) * 100,
        "as_of": vals[-1][0],
    }


def _frankfurter_usdidr():
    end = date.today()
    start = end - timedelta(days=40)
    url = (f"https://api.frankfurter.app/{start.isoformat()}..{end.isoformat()}"
           "?from=USD&to=IDR")
    data = get_json(url)
    rates = sorted(data["rates"].items())
    vals = [(d, r["IDR"]) for d, r in rates]
    latest = vals[-1][1]
    ref30 = vals[0][1]
    for d, v in vals:
        if (end - date.fromisoformat(d)).days <= 30:
            ref30 = v
            break
    return {
        "usdidr": latest,
        "usdidr_change_30d_pct": (latest / ref30 - 1) * 100,
        "as_of": vals[-1][0],
    }


def collect(store, run_id, cfg):
    out = {}
    brent, src = None, None
    for name, fn in (("stooq", _stooq_brent), ("fred", _fred_brent)):
        try:
            brent, src = fn(), name
            break
        except Exception:
            continue
    if brent:
        for metric, value in brent.items():
            if isinstance(value, (int, float)):
                store.observe(run_id, "global", src, metric, value,
                              meta={"as_of": brent["as_of"]})
                out[metric] = value
    else:
        store.observe(run_id, "global", "market", "brent_collector_error", 1)
    try:
        fx = _frankfurter_usdidr()
        for metric, value in fx.items():
            if isinstance(value, (int, float)):
                store.observe(run_id, "global", "frankfurter", metric, value,
                              meta={"as_of": fx["as_of"]})
                out[metric] = value
    except Exception:
        store.observe(run_id, "global", "market", "usdidr_collector_error", 1)
    return out
