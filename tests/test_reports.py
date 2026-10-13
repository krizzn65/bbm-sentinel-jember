import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from sentinel.collectors.stations import report_effect
import report_ground

NOW = datetime(2026, 10, 14, 2, 0, tzinfo=timezone.utc)


def _rep(status, age_h, fuel="Pertalite"):
    return {"ts": (NOW - timedelta(hours=age_h)).isoformat(),
            "fuel_type": fuel, "status": status, "queue_note": ""}


def test_report_floor_full_then_decays():
    floor, cap, ov, n, age = report_effect([_rep("kosong", 1)], NOW)
    assert floor == 85 and n == 1 and ov["Pertalite"]["status"] == "kosong"
    floor, *_ = report_effect([_rep("kosong", 8)], NOW)
    assert abs(floor - 85 * 0.85) < 0.01
    floor, *_ = report_effect([_rep("kosong", 20)], NOW)
    assert abs(floor - 85 * 0.6) < 0.01
    floor, cap, ov, n, age = report_effect([_rep("kosong", 30)], NOW)
    assert floor == 0 and n == 0 and not ov


def test_report_normal_caps_score():
    floor, cap, *_ = report_effect([_rep("normal", 1)], NOW)
    assert floor == 0 and cap == 25
    # a stale 'normal' no longer caps
    floor, cap, *_ = report_effect([_rep("normal", 8)], NOW)
    assert cap is None


def test_report_fuel_override_expires():
    *_, ov, n, age = report_effect([_rep("kosong", 8)], NOW)
    assert not ov  # overrides only while <=6h old


def test_parse_text_variants():
    p = report_ground.parse_text
    r = p("Ahmad Yani pertalite kosong, antrean mengular")
    assert r == {"code": "54.681.25", "fuel": "Pertalite", "status": "kosong"}, r
    r = p("di mastrip solar habis")
    assert r["code"] == "54.681.18" and r["fuel"] == "Solar", r
    r = p("Mangli Brawijaya antre panjang banget")
    assert r["code"] == "54.681.10" and r["status"] == "antre_panjang", r
    r = p("tegal besar masih lancar")
    assert r["code"] == "53.681.35" and r["status"] == "normal", r
    assert p("cuaca hari ini cerah") is None
    assert p("pertalite kosong") is None  # no station -> never guessed
