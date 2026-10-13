"""Feature building + weighted risk index.

Every raw observation becomes a feature with an explicit, inspectable
transformation to 0-100:
- threshold ramps for physical/market values (config.thresholds)
- baseline z-scores for count-like signals once enough history exists
  (falls back to threshold ramps before that)
Layer scores are weighted means; the risk index is the configured layer
weighting (regional heaviest: Jember history shows distribution through
Gumitir/Ketapang decides, global signals only set the stage)."""


def ramp(value, spec):
    if value is None:
        return None
    z, h, f = spec["zero"], spec["half"], spec["full"]
    if value <= z:
        return 0.0
    if value >= f:
        return 100.0
    if value <= h:
        return 50.0 * (value - z) / max(h - z, 1e-9)
    return 50.0 + 50.0 * (value - h) / max(f - h, 1e-9)


def zscore_ramp(store, metric, value, spec):
    base = store.baseline(metric)
    if base and base["std"] > 0:
        z = (value - base["mean"]) / base["std"]
        if z <= 0:
            return 0.0
        return min(100.0, z * 30.0)
    return ramp(value, spec)


def _latest(store, metric):
    row = store.latest(metric)
    return row["value"] if row else None


def build_features(store, cfg):
    th = cfg["thresholds"]
    feats = {}

    def add(name, layer, value, spec_key=None, use_z=False):
        spec = th.get(spec_key) if spec_key else None
        if value is None:
            feats[name] = {"layer": layer, "value": None, "score": None}
            return
        score = (zscore_ramp(store, _metric_of(name), value, spec)
                 if use_z and spec else ramp(value, spec) if spec else None)
        feats[name] = {"layer": layer, "value": value,
                       "score": round(score, 1) if score is not None else None}

    def _metric_of(name):
        return _FEATURE_METRIC[name]

    global _FEATURE_METRIC
    _FEATURE_METRIC = {
        "brent_7d": "brent_change_7d_pct",
        "usdidr_30d": "usdidr_change_30d_pct",
        "news_global_24h": "news_global_count_24h",
        "wave_ketapang": "wave_max_72h_ketapang",
        "wave_south": "wave_max_72h_south",
        "rain_gumitir": "rain_sum_72h_gumitir",
        "news_regional_24h": "news_regional_count_24h",
        "news_regional_stockout": "news_regional_stockout_mentions",
        "news_nasional_24h": "news_nasional_count_24h",
        "news_lokal_24h": "news_lokal_count_24h",
        "news_lokal_stockout": "news_lokal_stockout_mentions",
        "news_lokal_queue_m": "news_lokal_queue_max_m",
    }
    add("brent_7d", "global", _latest(store, "brent_change_7d_pct"), "brent_change_7d_pct")
    add("usdidr_30d", "global", _latest(store, "usdidr_change_30d_pct"),
        "usdidr_change_30d_pct")
    add("news_global_24h", "global", _latest(store, "news_global_count_24h"),
        "news_count_24h", use_z=True)
    add("wave_ketapang", "regional", _latest(store, "wave_max_72h_ketapang"),
        "wave_max_72h_ketapang_m")
    add("wave_south", "regional", _latest(store, "wave_max_72h_south"),
        "wave_max_72h_south_m")
    add("rain_gumitir", "regional", _latest(store, "rain_sum_72h_gumitir"),
        "rain_sum_72h_gumitir_mm")
    add("news_regional_24h", "regional", _latest(store, "news_regional_count_24h"),
        "news_count_24h", use_z=True)
    feats["news_regional_stockout"] = {
        "layer": "regional", "value": _latest(store, "news_regional_stockout_mentions"),
        "score": None}
    v = feats["news_regional_stockout"]["value"]
    if v is not None:
        feats["news_regional_stockout"]["score"] = round(min(100.0, v * 20.0), 1)
    add("news_nasional_24h", "nasional", _latest(store, "news_nasional_count_24h"),
        "news_count_24h", use_z=True)
    add("news_lokal_24h", "lokal", _latest(store, "news_lokal_count_24h"),
        "news_count_24h", use_z=True)
    feats["news_lokal_stockout"] = {
        "layer": "lokal", "value": _latest(store, "news_lokal_stockout_mentions"),
        "score": None}
    v = feats["news_lokal_stockout"]["value"]
    if v is not None:
        feats["news_lokal_stockout"]["score"] = round(min(100.0, v * 15.0), 1)
    feats["news_lokal_queue_m"] = {
        "layer": "lokal", "value": _latest(store, "news_lokal_queue_max_m"),
        "score": None}
    v = feats["news_lokal_queue_m"]["value"]
    if v is not None:
        feats["news_lokal_queue_m"]["score"] = round(min(100.0, v / 10.0), 1)
    # Social listening: public posts about Jember SPBU queues in the
    # last 24h (agent-fed, see collectors/social.py). Citizens post
    # hours before newsrooms publish, so this is the earliest local
    # signal; 5 queue posts saturate the feature.
    feats["social_lokal_posts"] = {
        "layer": "lokal", "value": _latest(store, "social_queue_posts_24h"),
        "score": None}
    v = feats["social_lokal_posts"]["value"]
    if v is not None:
        feats["social_lokal_posts"]["score"] = round(min(100.0, v * 20.0), 1)
    return feats


def layer_scores(feats):
    layers = {}
    for layer in ("global", "regional", "nasional", "lokal"):
        vals = [f["score"] for f in feats.values()
                if f["layer"] == layer and f["score"] is not None]
        layers[layer] = round(sum(vals) / len(vals), 1) if vals else 0.0
    return layers


def risk_index(layers, cfg):
    w = cfg["layer_weights"]
    total = sum(w.values())
    return round(sum(layers[k] * w[k] for k in w) / total, 1)


def level_of(index, cfg):
    name = cfg["levels"][0]["name"]
    for lvl in cfg["levels"]:
        if index >= lvl["min"]:
            name = lvl["name"]
    return name
