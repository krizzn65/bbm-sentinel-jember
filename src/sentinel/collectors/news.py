"""News as numbers. Google News RSS per configured query, bucketed by layer:
counts in the last 24h / 72h / 7d, plus phrase mining over titles for
stock-out words, queue length (metres/km) and wait time (hours). The counts
are stored as observations, so the scorer can compare them against the
rolling baseline instead of treating any single headline as a signal."""
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from ..http_util import get_text

FUEL_TYPES = ["Pertalite", "Pertamax Turbo", "Pertamax", "Bio Solar", "Solar",
              "Dexlite", "Pertamina Dex"]
STOCKOUT_WORDS = ["kosong", "habis", "langka", "kehabisan", "menipis", "stok terbatas"]
QUEUE_WORDS = ["antre", "antri", "antrean", "antrian", "mengular"]

RE_QUEUE_M = re.compile(r"(\d+(?:[.,]\d+)?)\s*(km|kilometer|meter|m)\b", re.I)
RE_QUEUE_H = re.compile(r"(\d+(?:[.,]\d+)?)\s*(jam)\b", re.I)


def fetch_rss(query, limit=100):
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(query)
           + "&hl=id&gl=ID&ceid=ID:id")
    xml = get_text(url, timeout=12, retries=2)
    root = ET.fromstring(xml)
    items = []
    for item in root.findall(".//item")[:limit]:
        title = item.findtext("title") or ""
        try:
            pub = parsedate_to_datetime(item.findtext("pubDate"))
        except Exception:
            continue
        items.append({"title": title, "pub": pub})
    return items


def mine_phrases(titles):
    text = " \n".join(titles)
    low = text.lower()
    out = {"stockout_mentions": 0, "queue_mentions": 0, "fuel_status": {}}
    out["stockout_mentions"] = sum(low.count(w) for w in STOCKOUT_WORDS)
    out["queue_mentions"] = sum(low.count(w) for w in QUEUE_WORDS)
    lengths = []
    for m in RE_QUEUE_M.finditer(text):
        val = float(m.group(1).replace(",", "."))
        if m.group(2).lower().startswith("k"):
            val *= 1000
        if 10 <= val <= 10000:
            lengths.append(val)
    waits = [float(m.group(1).replace(",", "."))
             for m in RE_QUEUE_H.finditer(text)
             if 0.25 <= float(m.group(1).replace(",", ".")) <= 24]
    out["queue_max_m"] = max(lengths) if lengths else 0
    out["wait_max_h"] = max(waits) if waits else 0
    for fuel in FUEL_TYPES:
        seg = [t for t in titles if fuel.lower() in t.lower()]
        if seg:
            seglow = " ".join(seg).lower()
            status = ("kosong" if any(w in seglow for w in STOCKOUT_WORDS)
                      else "antre" if any(w in seglow for w in QUEUE_WORDS)
                      else "disebut")
            out["fuel_status"][fuel] = {
                "status": status, "mentions": len(seg),
                "sample": seg[0][:160],
            }
    return out


def mine_triggers(titles):
    """Named historical-pattern triggers, counted over titles.

    These are the patterns the four documented Jember episodes actually
    turned on (see data/historical_episodes.json). Counting them by name -
    not just generic queue words - is what lets the forecast compare the
    present situation with the right historical analogue."""
    text = [t.lower() for t in titles]

    def count(pred):
        return sum(1 for t in text if pred(t))

    return {
        "gumitir_disruption": count(lambda t: "gumitir" in t and any(
            w in t for w in ("tutup", "ditutup", "perbaikan", "longsor", "macet", "dialihkan"))),
        "gumitir_closure_specific": count(lambda t: "gumitir" in t and any(
            w in t for w in ("ditutup total", "tutup total", "penutupan", "longsor"))),
        "ketapang_congestion": count(lambda t: ("ketapang" in t or "gilimanuk" in t) and any(
            w in t for w in ("macet", "antre", "antri", "penumpukan", "padat", "gelombang"))),
        "high_waves": count(lambda t: any(
            w in t for w in ("gelombang tinggi", "ombak tinggi", "gelombang 2", "cuaca buruk"))),
        "tanker_or_geopolitics": count(lambda t: any(
            w in t for w in ("tanker", "hormuz", "timur tengah", "geopolitik", "jadwal kapal"))),
        "panic_or_hoarding": count(lambda t: any(
            w in t for w in ("panic buying", "panik", "memborong", "penimbun", "ditimbun", "eceran"))),
        "neighbor_shortage": count(lambda t: any(
            w in t for w in ("bondowoso", "banyuwangi", "situbondo", "lumajang", "bali"))
            and any(w in t for w in ("antre", "antri", "langka", "kosong", "habis"))),
    }


def _safe_fetch(query):
    try:
        return fetch_rss(query)
    except Exception:
        return []


def collect(store, run_id, cfg):
    from concurrent.futures import ThreadPoolExecutor

    now = datetime.now(timezone.utc)
    out = {}
    all_queries = [(layer, q) for layer, qs in cfg["news_queries"].items() for q in qs]
    with ThreadPoolExecutor(max_workers=6) as pool:
        fetched = list(pool.map(
            lambda pair: _safe_fetch(pair[1]), all_queries))
    by_layer = {}
    for (layer, _q), items in zip(all_queries, fetched):
        seen_titles = {it["title"] for it in by_layer.get(layer, [])}
        for it in items:
            if it["title"] not in seen_titles:
                seen_titles.add(it["title"])
                by_layer.setdefault(layer, []).append(it)
    # Cross-layer de-echo (owner's precision programme, v0.7): one
    # story must be counted ONCE, in the NARROWEST funnel layer that
    # carries it. Provincial media re-report Jember stories under
    # "Jawa Timur", so without this a single Jember headline inflated
    # the jember, jatim and jawa layers simultaneously.
    def _norm(t):
        return " ".join(t.lower().split())
    _NARROW_FIRST = ["kota", "lokal", "hulu", "regional", "jatim",
                     "jawa", "nasional", "asia", "asean", "global"]
    claimed = {}
    for layer in _NARROW_FIRST:
        for it in by_layer.get(layer, []):
            claimed.setdefault(_norm(it["title"]), layer)
    removed = 0
    for layer, items in list(by_layer.items()):
        keep = [it for it in items
                if claimed.get(_norm(it["title"])) == layer]
        removed += len(items) - len(keep)
        by_layer[layer] = keep
    store.observe(run_id, "global", "news", "news_dedup_removed",
                  removed, now)
    for layer, queries in cfg["news_queries"].items():
        count24 = count72 = 0
        titles = []
        for it in by_layer.get(layer, []):
            if True:
                items = [it]
            for it in items:
                age = now - it["pub"]
                if age <= timedelta(hours=24):
                    count24 += 1
                if age <= timedelta(hours=72):
                    count72 += 1
                    titles.append(it["title"])
        mined = mine_phrases(titles)
        triggers = mine_triggers(titles)
        prefix = f"news_{layer}"
        store.observe(run_id, layer, "google-news-rss", f"{prefix}_count_24h",
                      count24, meta={"queries": queries})
        store.observe(run_id, layer, "google-news-rss", f"{prefix}_count_72h", count72)
        for k in ("stockout_mentions", "queue_mentions", "queue_max_m", "wait_max_h"):
            store.observe(run_id, layer, "google-news-rss", f"{prefix}_{k}", mined[k])
        for k, v in triggers.items():
            store.observe(run_id, layer, "google-news-rss", f"{prefix}_trigger_{k}", v)
        out[layer] = {"count_24h": count24, "count_72h": count72, **mined,
                      "triggers": triggers, "titles": titles[:8]}
    return out
