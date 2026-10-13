import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sentinel import vision


def test_nms_removes_overlaps():
    boxes = np.array([[0, 0, 100, 100], [5, 5, 105, 105], [300, 300, 400, 400]], dtype=float)
    scores = np.array([0.9, 0.8, 0.7])
    keep = vision._nms(boxes, scores)
    assert keep == [0, 2], keep


def test_tiles_cover_portrait():
    tiles = vision._tiles(1280, 2275)
    assert len(tiles) > 1
    assert tiles[0][:2] == (0, 0)
    assert max(t[2] for t in tiles) == 1280
    assert max(t[3] for t in tiles) == 2275


def test_queue_math_and_summary():
    counts = {"motor": 10, "mobil": 2, "truk": 1, "bus": 0, "sepeda": 0, "orang": 30}
    assert vision.estimate_queue_m(counts) == 10 * 1.7 + 2 * 5.0 + 1 * 8.0
    s = vision.summarize(counts)
    assert "10 motor" in s and "2 mobil" in s and "orang" not in s


def test_analyze_unavailable_is_honest(monkeypatch=None):
    # Point the model search at nothing: analyze must refuse, not invent.
    orig = vision.MODEL_PATH
    try:
        vision.MODEL_PATH = Path("/nonexistent/yolov8s.onnx")
        res = vision.analyze(__file__)
        assert res["status"] == "unavailable"
    finally:
        vision.MODEL_PATH = orig
