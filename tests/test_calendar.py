import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sentinel.calendar_id import pasaran_of, demand_factors


def test_pasaran_anchor():
    assert pasaran_of(date(1945, 8, 17)) == "Legi"
    assert pasaran_of(date(1945, 8, 21)) == "Kliwon"
    assert pasaran_of(date(1945, 8, 22)) == "Legi"


def test_demand_factors_capped():
    boost, reasons = demand_factors(date(2026, 10, 27))
    assert boost <= 5 and "masa gajian" in reasons
    boost2, _ = demand_factors(date(2026, 12, 16))
    assert boost2 <= 2
