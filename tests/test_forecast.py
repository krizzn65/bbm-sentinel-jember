import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sentinel import forecast
from sentinel.store import Store

CFG = {"timezone": "Asia/Jakarta",
       "forecast": {"horizon_days": 7, "holiday_major_boost": 10,
                    "holiday_minor_boost": 5, "weekend_boost": 3},
       "known_events": []}


def _seed(store, values):
    tz = ZoneInfo("Asia/Jakarta")
    now = datetime.now(tz)
    rid = store.start_run()
    for i, v in enumerate(values):
        ts = (now - timedelta(hours=len(values) - i)).isoformat(timespec="seconds")
        store.conn.execute(
            "INSERT INTO risk_scores (run_id, ts, risk_index, level,"
            " layer_scores, features) VALUES (?,?,?,?,?,?)",
            (rid, ts, v, "HIJAU", '{"lokal": 10, "regional": 10}', '{}'))
    store.conn.commit()


def test_flat_series_no_crisis_date(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    _seed(store, [20.0] * 30)
    fc = forecast.build_forecast(store, CFG, 20.0)
    assert fc is not None and len(fc["days"]) == 7
    assert fc["predicted_crisis_date"] is None
    assert forecast.lay_summary(fc) is None


def test_rising_series_predicts_peak(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    _seed(store, [20 + 2.2 * i for i in range(30)])
    fc = forecast.build_forecast(store, CFG, 84.0)
    assert fc["peak"]["pred_index"] >= fc["days"][0]["pred_index"]
    assert fc["predicted_crisis_date"] is not None
    assert forecast.lay_summary(fc) is not None


def test_date_format_indonesian():
    s = forecast.fmt_date_id(datetime(2026, 10, 14))
    assert s == "Rabu, 14 Oktober 2026", s
