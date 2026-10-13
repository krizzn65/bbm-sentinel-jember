"""Physical signals from Open-Meteo: wave height in the Bali Strait
(Ketapang-Gilimanuk ferry + tanker routes) and south of Jember, plus
rainfall over the Gumitir corridor and Jember city (landslide / road
disruption proxy). All values are numbers: max / mean / sums over 72h."""
from ..http_util import get_json


def _marine(lat, lon):
    url = ("https://marine-api.open-meteo.com/v1/marine"
           f"?latitude={lat}&longitude={lon}&hourly=wave_height"
           "&forecast_days=3&timezone=Asia%2FJakarta")
    data = get_json(url, timeout=15, retries=2)
    waves = [w for w in data["hourly"]["wave_height"] if w is not None]
    return {"wave_max_72h": max(waves), "wave_mean_72h": sum(waves) / len(waves)}


def _forecast(lat, lon):
    url = ("https://api.open-meteo.com/v1/forecast"
           f"?latitude={lat}&longitude={lon}&hourly=precipitation,wind_gusts_10m"
           "&forecast_days=3&timezone=Asia%2FJakarta")
    data = get_json(url, timeout=15, retries=2)
    precip = [p or 0 for p in data["hourly"]["precipitation"]]
    gusts = [g or 0 for g in data["hourly"]["wind_gusts_10m"]]
    return {"rain_sum_72h": sum(precip), "rain_max_1h": max(precip),
            "wind_gust_max_72h": max(gusts)}


def collect(store, run_id, cfg):
    loc = cfg["locations"]
    out = {}
    jobs = [
        ("ketapang", _marine, loc["ketapang_strait"], "regional", "open-meteo-marine"),
        ("south", _marine, loc["south_jember_sea"], "regional", "open-meteo-marine"),
        ("gumitir", _forecast, loc["gumitir"], "regional", "open-meteo-forecast"),
        ("jember", _forecast, loc["jember_city"], "lokal", "open-meteo-forecast"),
    ]
    for key, fn, place, layer, src in jobs:
        try:
            vals = fn(place["lat"], place["lon"])
        except Exception as exc:
            store.observe(run_id, layer, src, f"{key}_collector_error", 1,
                          meta={"error": str(exc)[:200], "place": place["label"]})
            continue
        for metric, value in vals.items():
            full = f"{metric}_{key}"
            store.observe(run_id, layer, src, full, float(value),
                          meta={"place": place["label"]})
            out[full] = float(value)
    return out
