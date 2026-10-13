#!/usr/bin/env python3
"""Fetch + export the vision model (one-time, and after model upgrades).

Downloads YOLOv8 .pt weights from Ultralytics' HuggingFace repo and
exports ONNX into models/. The runtime (sentinel.vision) needs only
onnxruntime + the .onnx files; torch/ultralytics are used solely here.
models/ is gitignored: weights are binary artifacts, this script is the
reproducible source."""
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = {"yolov8n": "https://huggingface.co/Ultralytics/YOLOv8/resolve/main/yolov8n.pt",
          "yolov8s": "https://huggingface.co/Ultralytics/YOLOv8/resolve/main/yolov8s.pt"}


def main():
    (ROOT / "models").mkdir(exist_ok=True)
    for name, url in MODELS.items():
        pt = ROOT / "models" / f"{name}.pt"
        if not pt.exists():
            print(f"downloading {url}")
            req = urllib.request.Request(url, headers={"User-Agent": "bbm-sentinel/0.2"})
            with urllib.request.urlopen(req, timeout=180) as r, open(pt, "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
        onnx = ROOT / "models" / f"{name}.onnx"
        if not onnx.exists():
            from ultralytics import YOLO
            print(f"exporting {name} -> ONNX")
            YOLO(str(pt)).export(format="onnx", imgsz=640, simplify=False, dynamic=False)
        print(f"ok: {onnx} ({onnx.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
