import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sentinel import stockflow


def test_demand_splits_to_documented_total():
    p = stockflow.load_params()
    total = 0.0
    for code in p["stations"]:
        d, _t = stockflow.station_daily_demand(p, code)
        total += sum(d.values())
    g = p["_dasar_global"]
    expect = g["kebutuhan_kabupaten_kl_hari"]["nilai"] \
        * g["porsi_volume_kota_kampus"]["nilai"] \
        * sum(g["campuran_bbm"][f] for f in stockflow.FUELS)
    assert abs(total - expect) < 1.0, (total, expect)


def test_disruption_noisy_or():
    d, parts = stockflow.disruption_factor(
        {"gumitir_closure": 1, "ketapang_congestion": 1}, {})
    assert abs(d - (1 - 0.15 * 0.6)) < 1e-6
    d0, _ = stockflow.disruption_factor({}, {})
    assert d0 == 0.0


def test_simulation_produces_dates(tmp_path):
    from sentinel.store import Store
    store = Store(str(tmp_path / "t.db"))
    # all stations bone dry at start -> stockouts must appear
    for code in stockflow.load_params()["stations"]:
        store.conn.execute(
            "INSERT INTO station_scores(run_id, ts, station_code,"
            " crisis_score, confidence, detail) VALUES (1,'t',?,90,"
            " 0.8, '{\"fuel_status\": {\"Pertalite\": {\"status\":"
            " \"kosong\"}}}')", (code,))
    store.conn.commit()
    sim = stockflow.simulate(store, {}, {"expected_duration_days": 9})
    assert sim["city"]["Pertalite"]["peak_dry_share"] > 0
    lines = stockflow.lay_lines(sim)
    assert any("Perkiraan hitungan stok" in x for x in lines), lines
