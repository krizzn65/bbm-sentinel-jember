import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sentinel.vision_video import wait_range_minutes, _median


def test_wait_range_math():
    assert wait_range_minutes({"motor": 5, "mobil": 1, "truk": 1}) == (8.2, 13.8)
    assert wait_range_minutes({}) == (0.0, 0.0)


def test_median():
    assert _median([1, 2, 3]) == 2
    assert _median([1, 2, 3, 4]) == 2.5
