import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sentinel import backtest


def test_backtest_excludes_self_and_reports_errors():
    rep = backtest.run_backtest()
    assert rep["episodes_tested"] == 3
    for r in rep["rows"]:
        assert r["best_analog"] != r["episode"]  # leave-one-out
        assert r["analog_duration_error"] >= 0
        assert r["analog_peak_error"] >= 0
    assert rep["mae_analog_duration_days"] is not None
    assert "kecil" in rep["note"]  # small-sample caveat is mandatory


def test_backtest_identical_triggers_pick_each_other():
    base = {"gumitir_closure": 1, "ketapang_congestion": 1}
    eps = [
        {"id": "a", "label": "A", "pattern": "p", "status": "closed",
         "triggers": dict(base), "duration_days_elapsed": 7,
         "peak_offset_days": 2},
        {"id": "b", "label": "B", "pattern": "p", "status": "closed",
         "triggers": dict(base), "duration_days_elapsed": 9,
         "peak_offset_days": 3},
    ]
    rep = backtest.run_backtest(eps)
    row_a = [r for r in rep["rows"] if r["episode"] == "a"][0]
    assert row_a["best_analog"] == "b" and row_a["similarity"] == 1.0
    assert row_a["analog_duration_error"] == 2
