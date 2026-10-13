#!/usr/bin/env python3
"""Assemble the SPBU fine-tuning dataset from HUMAN-VERIFIED labels.

Source of truth: data/vision_labels.jsonl (written by
sentinel.learning.record_correction whenever a human corrects a
count). For each unique image, the latest verified counts are taken;
the current detector is re-run and its boxes become YOLO-format
pseudo-labels ONLY when the detector's counts match the verified
counts exactly - otherwise the image is listed as needing manual box
annotation, because writing boxes the human never confirmed would
teach the model its own mistakes.

Output: data/vision_dataset/{images,labels}/ + manifest.json with
{ready, images_with_boxes, needs_annotation, min_images: 150}.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "vision_dataset"
MIN_IMAGES = 150
# YOLO class ids for the fine-tune (our own compact label space)
CLASS_ID = {"orang": 0, "sepeda": 1, "mobil": 2, "motor": 3, "bus": 4,
            "truk": 5}


def main():
    from sentinel import vision
    labels = {}
    lp = ROOT / "data" / "vision_labels.jsonl"
    if lp.exists():
        for line in lp.read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                labels[e["image"]] = e  # latest entry wins
    (OUT / "images").mkdir(parents=True, exist_ok=True)
    (OUT / "labels").mkdir(parents=True, exist_ok=True)
    boxed, needs = [], []
    for image, entry in labels.items():
        src = ROOT / image
        if not src.exists():
            needs.append({"image": image, "reason": "berkas hilang"})
            continue
        want_raw = entry["verified_counts"]
        want = {part: {c: (want_raw.get(part) or {}).get(c, 0)
                       for c in CLASS_ID}
                for part in ("queue", "passing")}
        res = vision.analyze(str(src))
        got = {"queue": res.get("counts") or {},
               "passing": res.get("passing_counts") or {}}
        if res.get("status") != "ok" or got != want:
            needs.append({"image": image, "reason": "hitungan detektor "
                          "tidak sama dengan label terverifikasi; kotak "
                          "perlu anotasi manual", "want": want, "got": got})
            continue
        from PIL import Image as PILImage
        w, h = PILImage.open(src).size
        lines = []
        for d in res["detections"]:
            if d["class"] not in CLASS_ID:
                continue
            x1, y1, x2, y2 = d["box"]
            lines.append(f"{CLASS_ID[d['class']]} "
                         f"{(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} "
                         f"{(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}")
        stem = Path(image).stem
        shutil.copy(src, OUT / "images" / f"{stem}.jpg")
        (OUT / "labels" / f"{stem}.txt").write_text("\n".join(lines))
        boxed.append(image)
    manifest = {"images_verified": len(labels),
                "images_with_boxes": len(boxed),
                "needs_annotation": needs,
                "min_images": MIN_IMAGES,
                "ready_for_finetune": len(boxed) >= MIN_IMAGES,
                "classes": CLASS_ID}
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1))
    print(json.dumps({k: manifest[k] for k in
                      ("images_verified", "images_with_boxes",
                       "ready_for_finetune")}, indent=1))
    if needs:
        print("perlu anotasi manual:", len(needs))


if __name__ == "__main__":
    main()
