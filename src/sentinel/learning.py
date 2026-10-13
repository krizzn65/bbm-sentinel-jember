"""Active learning: turn human corrections into training data.

Every correction a human makes to a vision count (the user caught
passing motorcycles being counted, then caught a queue neighbour
being called passing) is stored twice: as a row in vision_corrections
(audit trail) and as a line in data/vision_labels.jsonl - the label
file the future SPBU-specific fine-tune (scripts/train_vision.py)
will consume. Only HUMAN-VERIFIED counts become labels; unverified
model output never enters the dataset, so the model cannot teach
itself its own mistakes.
"""
import json
from pathlib import Path

from .store import now_iso

ROOT = Path(__file__).resolve().parents[2]
LABELS_PATH = ROOT / "data" / "vision_labels.jsonl"


def record_correction(store, image_path, station_code, model_counts,
                      corrected_counts, note, source="pengguna"):
    """corrected_counts: {"queue": {...}, "passing": {...}} as verified
    by a human. model_counts: what the system had said (same shape or
    flat). Returns the dataset entry written."""
    store.conn.execute(
        "INSERT INTO vision_corrections(ts, image_path, station_code,"
        " model_counts, corrected_counts, note, source)"
        " VALUES (?,?,?,?,?,?,?)",
        (now_iso(), str(image_path), station_code,
         json.dumps(model_counts), json.dumps(corrected_counts),
         note, source))
    store.conn.commit()
    entry = {"image": str(image_path), "station_code": station_code,
             "verified_counts": corrected_counts, "note": note,
             "source": source, "ts": now_iso()}
    LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LABELS_PATH.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def dataset_stats():
    n = 0
    stations = set()
    if LABELS_PATH.exists():
        for line in LABELS_PATH.read_text().splitlines():
            if line.strip():
                n += 1
                try:
                    stations.add(json.loads(line).get("station_code"))
                except Exception:
                    pass
    return {"labelled_images": n, "stations_covered": len(stations),
            "min_images_for_finetune": 150,
            "ready": n >= 150}
