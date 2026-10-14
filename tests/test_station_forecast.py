import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sentinel.station_forecast import _haversine_km, ENTRY


def test_haversine_entry_distances_sane():
    # Mastrip (east side of Jember) must be closer to the Banyuwangi
    # entry than Mangli (west side) - the route-order premise.
    mastrip = _haversine_km(ENTRY, (-8.15989, 113.71997))
    mangli = _haversine_km(ENTRY, (-8.19564, 113.65239))
    assert 60 < mastrip < 75 and mangli > mastrip


def test_station_forecast_ranking(tmp_path):
    from sentinel.store import Store
    from sentinel import station_forecast
    store = Store(str(tmp_path / "t.db"))
    store.conn.execute(
        "INSERT INTO station_scores(run_id, ts, station_code,"
        " crisis_score, confidence, detail) VALUES (1,'t','54.681.25',"
        " 90, 0.8, '{}')")
    store.conn.commit()
    fc = station_forecast.build_station_forecast(store)
    assert len(fc["ranking"]) == 11
    top = fc["ranking"][0]
    # highest current score + highest vulnerability -> Ahmad Yani top
    assert top["code"] == "54.681.25", top
    assert "rawan kosong duluan" in station_forecast.lay_line(fc)
