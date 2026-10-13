import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sentinel.scoring import ramp

CFG = {"zero": 0, "half": 4, "full": 10}


def test_ramp_bounds():
    assert ramp(-1, CFG) == 0.0
    assert ramp(0, CFG) == 0.0
    assert ramp(4, CFG) == 50.0
    assert ramp(10, CFG) == 100.0
    assert ramp(99, CFG) == 100.0


def test_ramp_midpoints():
    assert 20 < ramp(2, CFG) < 30
    assert 70 < ramp(7, CFG) < 80
