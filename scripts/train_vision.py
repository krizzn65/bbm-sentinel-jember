#!/usr/bin/env python3
"""Fine-tune YOLOv8 on SPBU queue photos once enough HUMAN-VERIFIED
box labels exist (see scripts/build_vision_dataset.py).

The gate is deliberate: below 150 boxed images a fine-tune would
memorise a handful of scenes and get WORSE on new ones, so this
script reports exactly how far the dataset is from ready instead of
training on too little. When the gate opens it fine-tunes yolov8s
in the repo .venv (torch + ultralytics live there from the one-time
ONNX export) and exports models/yolov8s_spbu.onnx, which
sentinel.vision prefers automatically.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "vision_dataset" / "manifest.json"


def main():
    if not MANIFEST.exists():
        print("dataset belum dibangun; jalankan "
              "scripts/build_vision_dataset.py dulu")
        return 2
    m = json.loads(MANIFEST.read_text())
    if not m["ready_for_finetune"]:
        print(f"BELUM SIAP: {m['images_with_boxes']} gambar berkotak dari "
              f"minimum {m['min_images']}; {len(m['needs_annotation'])} "
              f"gambar terverifikasi masih perlu anotasi kotak manual. "
              f"Dataset tumbuh dari koreksi manusia (learning.py) dan "
              f"foto panen yang terverifikasi.")
        return 1
    from ultralytics import YOLO
    data_yaml = ROOT / "data" / "vision_dataset" / "dataset.yaml"
    names = [None] * 6
    for name, idx in m["classes"].items():
        names[idx] = name
    data_yaml.write_text(
        f"path: {ROOT / 'data' / 'vision_dataset'}\n"
        f"train: images\nval: images\nnames: {names}\n")
    model = YOLO("yolov8s.pt")
    model.train(data=str(data_yaml), epochs=60, imgsz=640,
                project=str(ROOT / "models" / "finetune"), name="spbu",
                exist_ok=True)
    best = ROOT / "models" / "finetune" / "spbu" / "weights" / "best.pt"
    YOLO(str(best)).export(format="onnx", imgsz=640,
                           dynamic=False, simplify=True)
    exported = best.with_suffix(".onnx")
    target = ROOT / "models" / "yolov8s_spbu.onnx"
    exported.replace(target)
    print(f"model khusus SPBU tersimpan: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
