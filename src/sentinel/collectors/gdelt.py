"""Optional GDELT layer: global news-volume timelines. GDELT throttles hard
(one request per 5s per IP, frequent 429s), so this collector is spaced,
cached by the store, and strictly fail-soft: the pipeline never depends on
it. Google News RSS counts remain the primary news signal."""
import time

from ..http_util import get_json

QUERIES = {
    "gdelt_hormuz_oil_vol": "Hormuz oil",
    "gdelt_spbu_queue_vol": "antrean SPBU",
}


def collect(store, run_id, cfg):
    out = {}
    for metric, query in QUERIES.items():
        try:
            url = ("https://api.gdeltproject.org/api/v2/doc/doc?query="
                   + query.replace(" ", "%20")
                   + "&mode=timelinevol&timespan=14d&format=json")
            data = get_json(url, retries=1)
            series = data.get("timeline", [{}])[0].get("data", [])
            if series:
                last = series[-1]["value"]
                avg = sum(p["value"] for p in series) / len(series)
                store.observe(run_id, "global", "gdelt", metric, float(last),
                              meta={"avg14d": avg})
                out[metric] = float(last)
        except Exception as exc:
            store.observe(run_id, "global", "gdelt", f"{metric}_error", 1,
                          meta={"error": str(exc)[:160]})
        time.sleep(6)
    return out
