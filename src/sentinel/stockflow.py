"""Digital twin of station fuel stocks: numbers in, dates out.

Pertamina publishes no per-station stock data, so this is a flow
simulation on LABELLED estimates (data/station_params.json carries
the basis of every number: the regency burns ~700 KL/day across 41
outlets; the 11 city/campus stations are assumed to carry 55% of
that, split by station class; tank sizes are class estimates).

Per station and fuel, day by day for 14 days:

    level += deliveries   (cadence 1.5 d, 16 KL tanker, scaled by
                           the disruption factor from live signals)
    level -= demand       (baseline demand x panic surge factor,
                           decaying back to 1 as the episode ages)

Disruption is a noisy-or of the live chokepoint signals (Gumitir
closure/repair, Ketapang congestion, high waves, upstream stockout
score, tanker mentions) and is assumed to last the analog episode's
expected remaining duration, then decay over 2 days. Starting fill
is inferred from the station's own latest fuel status (kosong ->
5% left, antre -> 35%, otherwise 70%) and labelled an inference.

Outputs are ESTIMATES with the backtest's ±2-day honesty attached:
per-fuel stockout dates, the city's driest day, and the dates it
should ease and return to normal.
"""
import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FUELS = ("Pertalite", "Pertamax", "Bio Solar")


def load_params():
    return json.loads((ROOT / "data" / "station_params.json").read_text())


def _nilai(node):
    return node["nilai"] if isinstance(node, dict) else node


def station_daily_demand(params, code):
    g = params["_dasar_global"]
    info = params["stations"][code]
    cls = g["kelas"][info["kelas"]]
    total_city = (_nilai(g["kebutuhan_kabupaten_kl_hari"])
                  * _nilai(g["porsi_volume_kota_kampus"]))
    weights = {c: g["kelas"][params["stations"][c]["kelas"]]["bobot_volume"]
               for c in params["stations"]}
    wsum = sum(weights.values())
    total = total_city * weights[code] / wsum
    mix = g["campuran_bbm"]
    return {f: total * mix[f] for f in FUELS}, cls["tangki_kl"]


def disruption_factor(triggers, feats):
    parts = []
    if triggers.get("gumitir_closure"):
        parts.append(0.85)
    elif triggers.get("gumitir_repair"):
        parts.append(0.50)
    if triggers.get("ketapang_congestion"):
        parts.append(0.40)
    if triggers.get("high_waves"):
        parts.append(0.30)
    if triggers.get("tanker_schedule_change"):
        parts.append(0.30)
    up = (feats.get("news_hulu_stockout") or {}).get("score")
    if up:
        parts.append(up / 100.0 * 0.5)
    prod = 1.0
    for p in parts:
        prod *= (1 - p)
    return round(1 - prod, 3), parts


def surge_factor(feats):
    s = 1.0
    soc = (feats.get("social_lokal_posts") or {}).get("score")
    if soc:
        s += soc / 100.0 * 0.8
    comp = (feats.get("complaint_lokal") or {}).get("score")
    if comp:
        s += comp / 100.0 * 0.5
    return round(min(s, 2.2), 2)


def _start_fill(detail, fuel=None):
    """Inferred tank fill for one fuel. A station reported dry for
    Solar is not thereby dry for Pertalite: use the fuel's own
    status when known, else a neutral 70%."""
    fs = detail.get("fuel_status") or {}
    if fuel and fuel in fs:
        st = fs[fuel].get("status")
        return {"kosong": 0.05, "antre": 0.35}.get(st, 0.70)
    if fuel:
        return 0.70
    worst = 0.70
    for info in fs.values():
        if info.get("status") == "kosong":
            worst = min(worst, 0.05)
        elif info.get("status") == "antre":
            worst = min(worst, 0.35)
    return worst


def simulate(store, feats, analog, horizon=14):
    from .collectors.stations import load_stations
    from .history import current_pattern
    params = load_params()
    pattern = current_pattern(store)
    D, dparts = disruption_factor(pattern, feats)
    S = surge_factor(feats)
    expected_total = (analog or {}).get("expected_duration_days") or 7
    onset_ago = 2  # documented: current episode began 12 Oct
    disrupt_days = max(1, int(round(expected_total)) - onset_ago)
    latest = {}
    for code, detail in store.conn.execute(
            "SELECT station_code, detail FROM station_scores WHERE id IN"
            " (SELECT MAX(id) FROM station_scores GROUP BY station_code)"):
        try:
            latest[code] = json.loads(detail or "{}")
        except Exception:
            latest[code] = {}
    # Data assimilation by calibration: the raw signal pair (D, S)
    # routinely overstates reality - repair news is not stopped
    # tankers (Pertamina rerouted via Surabaya/Malang in Sep/Oct
    # 2026), and chatter is not litres. So the pair is calibrated:
    # replay the episode's elapsed days from a uniform 80% fill and
    # pick the (D, S) whose simulated mean Pertalite fill today best
    # matches the mean fill inferred from observed station states.
    fills_obs = {c: _start_fill(latest.get(c, {}), "Pertalite")
                 for c in params["stations"]}
    mean_obs = sum(fills_obs.values()) / len(fills_obs)
    dem_tank = {c: station_daily_demand(params, c)
                for c in params["stations"]}
    cadence0 = _nilai(params["_dasar_global"]["ritme_kirim_normal_hari"])
    def _replay(Dc, Sc):
        ends = []
        for c, (dem, tanks) in dem_tank.items():
            cap = tanks["Pertalite"]
            level = cap * 0.8
            for _d in range(onset_ago):
                level -= dem["Pertalite"] * Sc
                level = max(0.0, level)
                planned = dem["Pertalite"] * 1.15
                level += min(planned, cap - level) * (1 - Dc)
            ends.append(level / cap)
        return sum(ends) / len(ends)
    best = None
    d = 0.0
    while d <= D + 1e-9:
        s = 1.0
        while s <= S + 1e-9:
            err = abs(_replay(d, s) - mean_obs)
            dist = abs(d - D) + abs(s - S)
            key = (round(err, 4), round(dist, 3))
            if best is None or key < best[0]:
                best = (key, d, s)
            s += 0.1
        d += 0.05
    _key, D, S = best
    calib = {"mean_fill_observed": round(mean_obs, 2),
             "mean_fill_simulated": round(_replay(D, S), 2),
             "d_signals": None, "s_signals": None}
    D_sig, S_sig = disruption_factor(pattern, feats)[0], surge_factor(feats)
    calib["d_signals"], calib["s_signals"] = D_sig, S_sig
    g = params["_dasar_global"]
    cadence = _nilai(g["ritme_kirim_normal_hari"])
    tanker = _nilai(g["tangki_antar_kl"])
    today = date.today()
    per_station = {}
    dry_count = {f: [0] * horizon for f in FUELS}
    for st in load_stations():
        code = st["code"]
        demand, tanks = station_daily_demand(params, code)
        entry = {}
        for fuel in FUELS:
            cap = tanks[fuel]
            level = cap * _start_fill(latest.get(code, {}), fuel)
            stockout = None
            for d in range(horizon):
                day_D = D if d < disrupt_days else (
                    D * max(0.0, 1 - (d - disrupt_days + 1) / 2.0)
                    if d < disrupt_days + 2 else 0.0)
                day_S = 1 + (S - 1) * max(0.0, 1 - d / max(1, disrupt_days + 3))
                # Order within a day: demand drains first (a
                # station that hits empty mid-day counts as dry
                # that day), the tanker arrives afterwards.
                # Deliveries are modelled as a smoothed daily rate
                # (busy stations are in practice served near-daily;
                # a lumpy 1.5-day cadence produced sawtooth levels
                # that oscillated dry/not-dry on alternate days).
                level -= demand[fuel] * day_S
                if level <= cap * 0.02:
                    if stockout is None:
                        stockout = (today + timedelta(days=d)).isoformat()
                    level = 0.0
                    dry_count[fuel][d] += 1
                planned = demand[fuel] * 1.15
                room = cap - level
                level += min(planned, room) * (1 - day_D)
            entry[fuel] = {"stockout_date": stockout,
                           "tank_kl": cap,
                           "demand_kl_day": round(demand[fuel], 1),
                           "start_fill_pct": round(
                               _start_fill(latest.get(code, {}), fuel)
                               * 100)}
        per_station[code] = {"name": st["name"], "fuels": entry}
    n = len(per_station)
    city = {}
    for fuel in FUELS:
        shares = [round(c / n, 2) for c in dry_count[fuel]]
        peak_d = max(range(horizon), key=lambda i: shares[i])
        recovery = normal = None
        for d in range(peak_d, horizon):
            if recovery is None and shares[d] < 0.10:
                recovery = (today + timedelta(days=d)).isoformat()
            if recovery and d + 1 < horizon and shares[d] == 0 \
                    and shares[d + 1] == 0:
                normal = (today + timedelta(days=d)).isoformat()
                break
        city[fuel] = {"dry_share_by_day": shares,
                      "peak_dry_date": (today + timedelta(days=peak_d)).isoformat(),
                      "peak_dry_share": shares[peak_d],
                      "recovery_date": recovery, "normal_date": normal}
    return {"generated": today.isoformat(),
            "assumptions": {"disruption_factor": D,
                            "disruption_parts": dparts,
                            "surge_factor": S,
                            "calibration": calib,
                            "disruption_days_expected": disrupt_days,
                            "params_basis": "data/station_params.json"},
            "city": city, "stations": per_station}


def lay_lines(sim):
    lines = []
    p = sim["city"]["Pertalite"]
    first = None
    for code, st in sim["stations"].items():
        d = st["fuels"]["Pertalite"]["stockout_date"]
        if d and (first is None or d < first[1]):
            first = (st["name"].replace("SPBU ", ""), d)
    from datetime import datetime as _dt
    def fmt(iso):
        if not iso:
            return None
        dt = _dt.fromisoformat(iso)
        bulan = ["", "Januari", "Februari", "Maret", "April", "Mei",
                 "Juni", "Juli", "Agustus", "September", "Oktober",
                 "November", "Desember"]
        hari = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu",
                "Minggu"]
        return f"{hari[dt.weekday()]}, {dt.day} {bulan[dt.month]}"
    if first and p["peak_dry_share"] > 0:
        lines.append(f"Perkiraan hitungan stok: Pertalite paling cepat "
                     f"habis di {first[0]} sekitar {fmt(first[1])}.")
    if p["recovery_date"]:
        lines.append(f"Kondisi diperkirakan mulai membaik sekitar "
                     f"{fmt(p['recovery_date'])}")
        if p["normal_date"]:
            lines[-1] += (f", dan kembali normal sekitar "
                          f"{fmt(p['normal_date'])}.")
        else:
            lines[-1] += "."
        lines[-1] += (" (Perkiraan dari hitungan stok dan pola lama; "
                      "bisa meleset sekitar dua hari.)")
    return lines
