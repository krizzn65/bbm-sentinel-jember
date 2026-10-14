"""Feature building + weighted risk index.

Every raw observation becomes a feature with an explicit, inspectable
transformation to 0-100:
- threshold ramps for physical/market values (config.thresholds)
- baseline z-scores for count-like signals once enough history exists
  (falls back to threshold ramps before that)

The analysis is a FUNNEL of nine layers, widest to narrowest, the
way a Jember fuel crisis actually forms - world events narrow down
through Asia, ASEAN, Indonesia, Java and East Java into the Besuki /
Tapal Kuda chokepoints (Gumitir, Ketapang, Tanjungwangi), then
Jember regency, then the city/campus stations themselves:

  dunia -> asia -> asean -> indonesia -> jawa -> jatim
        -> tapal_kuda -> jember -> kota_kampus

Layer scores are weighted means of their features; the risk index
renormalises the configured weights over the layers that actually
have data, so a dead collector dilutes nothing and fabricates
nothing. Tapal Kuda weighs heaviest: Jember's history shows its
crises are decided at those chokepoints, while world signals only
set the stage."""

FUNNEL_LAYERS = ("dunia", "asia", "asean", "indonesia", "jawa",
                 "jatim", "tapal_kuda", "jember", "kota_kampus")


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
        "news_asia_24h": "news_asia_count_24h",
        "news_asean_24h": "news_asean_count_24h",
        "news_jawa_24h": "news_jawa_count_24h",
        "news_jatim_24h": "news_jatim_count_24h",
        "news_kota_24h": "news_kota_count_24h",
    }
    # --- Lapis 1: DUNIA (world markets and geopolitics set the stage)
    add("brent_7d", "dunia", _latest(store, "brent_change_7d_pct"), "brent_change_7d_pct")
    add("usdidr_30d", "dunia", _latest(store, "usdidr_change_30d_pct"),
        "usdidr_change_30d_pct")
    add("news_global_24h", "dunia", _latest(store, "news_global_count_24h"),
        "news_count_24h", use_z=True)
    # --- Lapis 2-6 + 9: news funnels (asia, asean, indonesia, jawa,
    # jatim, kota) - one count feature (z-scored against its own
    # baseline) and one stockout-mention feature each.
    for coll, funnel, mult in (("asia", "asia", 20.0),
                               ("asean", "asean", 20.0),
                               ("nasional", "indonesia", 15.0),
                               ("jawa", "jawa", 15.0),
                               ("jatim", "jatim", 15.0),
                               ("kota", "kota_kampus", 15.0)):
        add(f"news_{coll}_24h", funnel,
            _latest(store, f"news_{coll}_count_24h"),
            "news_count_24h", use_z=True)
        feats[f"news_{coll}_stockout"] = {
            "layer": funnel,
            "value": _latest(store, f"news_{coll}_stockout_mentions"),
            "score": None}
        v = feats[f"news_{coll}_stockout"]["value"]
        if v is not None:
            feats[f"news_{coll}_stockout"]["score"] = round(
                min(100.0, v * mult), 1)
    # --- Lapis 7: TAPAL KUDA / BESUKI (the chokepoints decide)
    add("wave_ketapang", "tapal_kuda", _latest(store, "wave_max_72h_ketapang"),
        "wave_max_72h_ketapang_m")
    add("wave_south", "tapal_kuda", _latest(store, "wave_max_72h_south"),
        "wave_max_72h_south_m")
    add("rain_gumitir", "tapal_kuda", _latest(store, "rain_sum_72h_gumitir"),
        "rain_sum_72h_gumitir_mm")
    add("news_regional_24h", "tapal_kuda", _latest(store, "news_regional_count_24h"),
        "news_count_24h", use_z=True)
    feats["news_regional_stockout"] = {
        "layer": "tapal_kuda", "value": _latest(store, "news_regional_stockout_mentions"),
        "score": None}
    v = feats["news_regional_stockout"]["value"]
    if v is not None:
        feats["news_regional_stockout"]["score"] = round(min(100.0, v * 20.0), 1)
    # Upstream sensors inside Tapal Kuda: shortages in Banyuwangi /
    # Bondowoso / Situbondo / Lumajang and trouble at the Tanjungwangi
    # terminal or Ketapang precede Jember's own queues by hours to
    # days - Jember's crisis is born there, not at its pumps.
    feats["news_hulu_stockout"] = {
        "layer": "tapal_kuda",
        "value": _latest(store, "news_hulu_stockout_mentions"), "score": None}
    v = feats["news_hulu_stockout"]["value"]
    if v is not None:
        feats["news_hulu_stockout"]["score"] = round(min(100.0, v * 10.0), 1)
    feats["news_hulu_queue"] = {
        "layer": "tapal_kuda",
        "value": _latest(store, "news_hulu_queue_mentions"), "score": None}
    v = feats["news_hulu_queue"]["value"]
    if v is not None:
        feats["news_hulu_queue"]["score"] = round(min(100.0, v * 2.0), 1)
    # --- Lapis 8: JEMBER (regency-wide signals)
    add("news_lokal_24h", "jember", _latest(store, "news_lokal_count_24h"),
        "news_count_24h", use_z=True)
    feats["news_lokal_stockout"] = {
        "layer": "jember", "value": _latest(store, "news_lokal_stockout_mentions"),
        "score": None}
    v = feats["news_lokal_stockout"]["value"]
    if v is not None:
        feats["news_lokal_stockout"]["score"] = round(min(100.0, v * 15.0), 1)
    feats["news_lokal_queue_m"] = {
        "layer": "jember", "value": _latest(store, "news_lokal_queue_max_m"),
        "score": None}
    v = feats["news_lokal_queue_m"]["value"]
    if v is not None:
        feats["news_lokal_queue_m"]["score"] = round(min(100.0, v / 10.0), 1)
    # Social listening: public posts about Jember SPBU queues in the
    # last 24h (agent-fed, see collectors/social.py). Citizens post
    # hours before newsrooms publish, so this is the earliest local
    # signal; 5 queue posts saturate the feature.
    feats["social_lokal_posts"] = {
        "layer": "jember", "value": _latest(store, "social_queue_posts_24h"),
        "score": None}
    v = feats["social_lokal_posts"]["value"]
    if v is not None:
        feats["social_lokal_posts"]["score"] = round(min(100.0, v * 20.0), 1)
    # Public complaints + official PPID attention: a citizen who
    # bothers to file/tag a complaint, and the regency publishing
    # fuel-crisis field news, are stronger intent signals than
    # general posts, so the combined count saturates at 4.
    feats["complaint_lokal"] = {
        "layer": "jember",
        "value": None, "score": None}
    parts = [x for x in (_latest(store, "complaint_posts_24h"),
                         _latest(store, "ppid_fuel_articles_72h"))
             if x is not None]
    if parts:
        feats["complaint_lokal"]["value"] = sum(parts)
        feats["complaint_lokal"]["score"] = round(
            min(100.0, sum(parts) * 25.0), 1)
    # --- Lapis 9: KOTA + KAMPUS (the 11 stations themselves)
    rows = store.conn.execute(
        "SELECT crisis_score FROM station_scores WHERE id IN "
        "(SELECT MAX(id) FROM station_scores GROUP BY station_code)"
    ).fetchall()
    if rows:
        scores = [r[0] for r in rows]
        feats["stations_max"] = {"layer": "kota_kampus",
                                 "value": max(scores),
                                 "score": round(float(max(scores)), 1)}
        feats["stations_mean"] = {"layer": "kota_kampus",
                                  "value": round(sum(scores) / len(scores), 1),
                                  "score": round(sum(scores) / len(scores), 1)}
    else:
        feats["stations_max"] = {"layer": "kota_kampus", "value": None,
                                  "score": None}
        feats["stations_mean"] = {"layer": "kota_kampus", "value": None,
                                   "score": None}
    return feats


def layer_scores(feats):
    layers = {}
    for layer in FUNNEL_LAYERS:
        vals = [f["score"] for f in feats.values()
                if f["layer"] == layer and f["score"] is not None]
        layers[layer] = round(sum(vals) / len(vals), 1) if vals else None
    return layers


def risk_index(layers, cfg):
    w = cfg["layer_weights"]
    present = {k: v for k, v in w.items() if layers.get(k) is not None}
    if not present:
        return 0.0
    total = sum(present.values())
    return round(sum(layers[k] * wt for k, wt in present.items()) / total, 1)


def level_of(index, cfg):
    name = cfg["levels"][0]["name"]
    for lvl in cfg["levels"]:
        if index >= lvl["min"]:
            name = lvl["name"]
    return name
