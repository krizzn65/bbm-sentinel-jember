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


def _det(cls, cx, cy, w=60, h=80):
    return {"class": cls, "confidence": 0.9,
            "box": [cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2]}


def test_queue_filter_excludes_passers_by():
    dets = ([_det("motor", 300 + 55 * i, 400 + 8 * i) for i in range(6)]
            + [_det("motor", 60, 120), _det("motor", 120, 90)])
    method = vision.classify_queue(dets, 1000, 700)
    assert method == "formasi_antrean"
    queue = [d for d in dets if d["in_queue"]]
    passing = [d for d in dets if not d["in_queue"]]
    assert len(queue) == 6 and len(passing) == 2, (len(queue), len(passing))


def test_queue_filter_follows_bent_queue():
    # L-shaped queue: a horizontal arm turning into a vertical arm -
    # one straight corridor cannot cover it, chaining must.
    dets = ([_det("motor", 300 + 55 * i, 500) for i in range(5)]
            + [_det("motor", 520, 445 - 55 * i) for i in range(1, 4)]
            + [_det("motor", 80, 110, w=26, h=34),
               _det("motor", 140, 90, w=26, h=34)])
    method = vision.classify_queue(dets, 1000, 700)
    assert method == "formasi_antrean"
    queue = [d for d in dets if d["in_queue"]]
    passing = [d for d in dets if not d["in_queue"]]
    assert len(queue) == 8 and len(passing) == 2, (len(queue), len(passing))


def test_queue_filter_counts_photographer_neighbours():
    # Queue photos are usually taken from INSIDE the queue: a huge
    # vehicle cut off at the bottom frame edge is a queue neighbour,
    # not passing traffic - even when far from the file's nucleus.
    dets = ([_det("motor", 300 + 55 * i, 400) for i in range(4)]
            + [{"class": "motor", "confidence": 0.5,
                "box": [60, 380, 190, 700]}]
            + [_det("motor", 850, 150, w=30, h=40)])
    method = vision.classify_queue(dets, 1000, 700)
    assert method == "formasi_antrean"
    queue = [d for d in dets if d["in_queue"]]
    passing = [d for d in dets if not d["in_queue"]]
    assert len(queue) == 5 and len(passing) == 1, (len(queue), len(passing))


def test_queue_filter_few_vehicles_counts_all():
    dets = [_det("motor", 100, 100), _det("mobil", 300, 120)]
    assert vision.classify_queue(dets, 800, 600) == "formasi_kurang"
    assert all(d["in_queue"] for d in dets)


def test_analyze_unavailable_is_honest(monkeypatch=None):
    # Point the model search at nothing: analyze must refuse, not invent.
    orig = vision.MODEL_PATH
    try:
        vision.MODEL_PATH = Path("/nonexistent/yolov8s.onnx")
        res = vision.analyze(__file__)
        assert res["status"] == "unavailable"
    finally:
        vision.MODEL_PATH = orig
