"""Computer vision for queue photos: classify and count vehicles.

YOLOv8n (COCO) exported to ONNX, run with onnxruntime + numpy only - no
torch needed at runtime. The model file lives in models/yolov8n.onnx and
is produced once by scripts/fetch_vision_model.py (gitignored; it is a
binary artifact, not source).

What it counts, per class: motor, mobil, truk, bus, sepeda, orang.
The counts are the vehicles VISIBLE in the photo - always a lower bound
for the real queue, and the result says so. Queue length is estimated
from the visible vehicles with average queued spacing per class
(motor 1.7 m, mobil 5.0 m, truk 8 m, bus 10 m); it is labelled an
estimate everywhere it surfaces.

If the model or onnxruntime is missing, analyze() returns
{"status": "unavailable"} - the system never invents a count."""
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
# Prefer the small model (better recall on partly occluded vehicles);
# fall back to nano when only that is present.
MODEL_CANDIDATES = [ROOT / "models" / "yolov8s.onnx", ROOT / "models" / "yolov8n.onnx"]
MODEL_PATH = next((p for p in MODEL_CANDIDATES if p.exists()), MODEL_CANDIDATES[0])
IMG_SIZE = 640
CONF_MIN = 0.35
IOU_MAX = 0.45

CLASSES = {0: "orang", 1: "sepeda", 2: "mobil", 3: "motor", 5: "bus", 7: "truk"}
# Per-class confidence floors. Large boxy classes (truk/bus) attract
# false positives from signboards and buildings at low confidence;
# small classes (motor) need the lower floor to be found at distance.
CLASS_CONF = {"orang": 0.35, "sepeda": 0.35, "mobil": 0.40, "motor": 0.35,
              "bus": 0.45, "truk": 0.45}
VEHICLE_CLASSES = ["motor", "mobil", "truk", "bus", "sepeda"]
SPACING_M = {"motor": 1.7, "sepeda": 1.2, "mobil": 5.0, "truk": 8.0, "bus": 10.0}
COLORS = {"motor": (255, 80, 80), "mobil": (80, 160, 255), "truk": (255, 170, 40),
          "bus": (80, 220, 120), "sepeda": (200, 120, 255), "orang": (160, 160, 160)}
_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _letterbox(img):
    w, h = img.size
    scale = min(IMG_SIZE / w, IMG_SIZE / h)
    nw, nh = int(w * scale), int(h * scale)
    resized = img.resize((nw, nh), Image.BILINEAR)
    canvas = Image.new("RGB", (IMG_SIZE, IMG_SIZE), (114, 114, 114))
    pad = ((IMG_SIZE - nw) // 2, (IMG_SIZE - nh) // 2)
    canvas.paste(resized, pad)
    return canvas, scale, pad


def _nms(boxes, scores, iou_max=IOU_MAX):
    """boxes: (n,4) xyxy. Returns kept indices."""
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while len(order) > 0:
        i = order[0]
        keep.append(i)
        if len(order) == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        iou = inter / (areas[i] + areas[rest] - inter + 1e-9)
        order = rest[iou <= iou_max]
    return keep


def _postprocess(output, scale, pad, orig_w, orig_h, conf_min=CONF_MIN):
    pred = output[0].T  # (8400, 84): cx, cy, w, h, 80 class scores
    boxes_c, classes_scores = pred[:, :4], pred[:, 4:]
    cls = classes_scores.argmax(axis=1)
    conf = classes_scores[np.arange(len(pred)), cls]
    floors = np.array([CLASS_CONF.get(CLASSES.get(int(c)), conf_min) if int(c) in CLASSES
                       else 1.0 for c in cls])
    mask = (conf >= floors) & np.isin(cls, list(CLASSES))
    boxes_c, cls, conf = boxes_c[mask], cls[mask], conf[mask]
    if len(boxes_c) == 0:
        return []
    xyxy = np.stack([boxes_c[:, 0] - boxes_c[:, 2] / 2,
                     boxes_c[:, 1] - boxes_c[:, 3] / 2,
                     boxes_c[:, 0] + boxes_c[:, 2] / 2,
                     boxes_c[:, 1] + boxes_c[:, 3] / 2], axis=1)
    keep = _nms(xyxy, conf)
    dets = []
    for i in keep:
        x1, y1, x2, y2 = xyxy[i]
        x1 = float(np.clip((x1 - pad[0]) / scale, 0, orig_w))
        x2 = float(np.clip((x2 - pad[0]) / scale, 0, orig_w))
        y1 = float(np.clip((y1 - pad[1]) / scale, 0, orig_h))
        y2 = float(np.clip((y2 - pad[1]) / scale, 0, orig_h))
        dets.append({"class": CLASSES[int(cls[i])], "confidence": round(float(conf[i]), 2),
                     "box": [round(x1), round(y1), round(x2), round(y2)]})
    return dets


def _edge_gap(a, b):
    """Pixel gap between two boxes (0 when they touch or overlap)."""
    dx = max(0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0, max(a[1], b[1]) - min(a[3], b[3]))
    return (dx * dx + dy * dy) ** 0.5


def classify_queue(dets, img_w, img_h):
    """Separate QUEUING vehicles from ones merely PASSING THROUGH the
    photo. The rules encode what an SPBU queue actually looks like,
    distilled from news and social-media photos/videos of fuel queues
    (Jember, Bali, Palangka Raya, Balikpapan, Takengon):

    1. A queue is a FILE: riders wait bumper-to-bumper in one or two
       lines, so each member's box nearly touches the next member's.
       Membership is decided by EDGE GAP relative to box size, which
       is perspective-proof: far members are small and close together
       in pixels, near members are large and far apart, but the gap
       between neighbours stays small either way.
    2. Queues SPILL: a long queue overflows the forecourt onto the
       public road, sometimes for hundreds of metres. Being on the
       road never disqualifies a vehicle; only disconnection from
       the file does.
    3. The camera usually sits INSIDE the queue (a waiting rider
       filming): very large vehicles cut off by the bottom frame
       edge are the photographer's queue neighbours, even when the
       detector only catches part of them.
    4. A mounted rider (an 'orang' box overlapping the vehicle)
       right at the file's edge extends the file by one hop.
    Passing traffic is what remains: isolated vehicles or small
    separate groups, typically small in frame on the far carriageway.

    With too few vehicles (<4) or no file of >=3 and no foreground
    anchor, formation cannot be established: everything counts as
    queue and the method says so - an honest fallback, never a
    silent guess. 'orang' detections are not classified; they stay
    counted as people visible in frame."""
    vehicles = [d for d in dets if d["class"] in VEHICLE_CLASSES]
    for d in dets:
        d["in_queue"] = True
    if len(vehicles) < 4:
        return "formasi_kurang"
    boxes = [d["box"] for d in vehicles]
    diags = np.array([((b[2] - b[0]) ** 2 + (b[3] - b[1]) ** 2) ** 0.5
                      for b in boxes])
    parent = list(range(len(vehicles)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(vehicles)):
        for j in range(i + 1, len(vehicles)):
            if _edge_gap(boxes[i], boxes[j]) <= 0.8 * min(diags[i], diags[j]):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj
    comps = {}
    for i in range(len(vehicles)):
        comps.setdefault(find(i), []).append(i)
    areas = np.array([(b[2] - b[0]) * (b[3] - b[1]) for b in boxes],
                     dtype=float)
    main = max(comps.values(),
               key=lambda c: (len(c), sum(areas[i] for i in c)))
    queue = set(main) if len(main) >= 3 else set()
    # Rule 3: the photographer's neighbours, cut off at the frame's
    # bottom edge, are queue even when only partially detected.
    med_area = float(np.median(areas))
    for i, b in enumerate(boxes):
        if i in queue:
            continue
        tall_cut = b[3] >= 0.97 * img_h and (b[3] - b[1]) >= 0.25 * img_h
        huge_low = areas[i] >= 5 * med_area and b[3] >= 0.8 * img_h
        if tall_cut or huge_low:
            queue.add(i)
    if not queue:
        return "tanpa_formasi"
    # Rule 4: a mounted rider at the file's edge extends the file.
    people = [d["box"] for d in dets if d["class"] == "orang"]

    def mounted(b):
        for pb in people:
            ox = max(0, min(b[2], pb[2]) - max(b[0], pb[0]))
            oy = max(0, min(b[3], pb[3]) - max(b[1], pb[1]))
            if ox * oy >= 0.25 * (pb[2] - pb[0]) * (pb[3] - pb[1]):
                return True
        return False

    for i, b in enumerate(boxes):
        if i in queue or not mounted(b):
            continue
        if any(_edge_gap(b, boxes[j]) <= 1.6 * min(diags[i], diags[j])
               for j in list(queue)):
            queue.add(i)
    for i, d in enumerate(vehicles):
        d["in_queue"] = i in queue
    return "formasi_antrean"


def estimate_queue_m(counts):
    return round(sum(counts.get(c, 0) * SPACING_M[c] for c in SPACING_M), 1)


def summarize(counts):
    parts = [f"{counts[c]} {c}" for c in VEHICLE_CLASSES if counts.get(c)]
    return ", ".join(parts) if parts else "tidak ada kendaraan terdeteksi"


def _tiles(w, h, tile=800, overlap=0.25):
    """Overlapping tile windows covering the image. A single 640px pass
    shrinks a tall phone photo so much that distant motorcycles vanish;
    tiling keeps them detectable, at the cost of a few extra passes."""
    if max(w, h) <= 900:
        return [(0, 0, w, h)]
    step = int(tile * (1 - overlap))
    xs = list(range(0, max(1, w - tile + 1), step))
    ys = list(range(0, max(1, h - tile + 1), step))
    if xs[-1] != w - tile:
        xs.append(max(0, w - tile))
    if ys[-1] != h - tile:
        ys.append(max(0, h - tile))
    return [(x, y, min(x + tile, w), min(y + tile, h)) for y in ys for x in xs]


def _infer(sess, img):
    boxed, scale, pad = _letterbox(img)
    arr = np.asarray(boxed, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
    output = sess.run(None, {sess.get_inputs()[0].name: arr})[0]
    return _postprocess(output, scale, pad, img.size[0], img.size[1])


def _merge_nms(dets):
    """Class-aware global NMS over detections from all tiles."""
    out = []
    for cls in {d["class"] for d in dets}:
        group = [d for d in dets if d["class"] == cls]
        boxes = np.array([d["box"] for d in group], dtype=float)
        scores = np.array([d["confidence"] for d in group])
        for i in _nms(boxes, scores):
            out.append(group[i])
    return sorted(out, key=lambda d: -d["confidence"])


def analyze(image_path, annotated_path=None):
    if not MODEL_PATH.exists():
        return {"status": "unavailable", "reason": "model YOLOv8 ONNX belum ada di models/; jalankan scripts/fetch_vision_model.py"}
    try:
        import onnxruntime as ort
    except ImportError:
        return {"status": "unavailable", "reason": "onnxruntime belum terpasang di .venv"}
    img = Image.open(image_path).convert("RGB")
    orig_w, orig_h = img.size
    sess = ort.InferenceSession(str(MODEL_PATH), providers=["CPUExecutionProvider"])
    tiles = _tiles(orig_w, orig_h)
    dets = []
    for (x1, y1, x2, y2) in tiles:
        tile_img = img.crop((x1, y1, x2, y2)) if (x2 - x1, y2 - y1) != (orig_w, orig_h) else img
        for d in _infer(sess, tile_img):
            b = d["box"]
            dets.append({"class": d["class"], "confidence": d["confidence"],
                         "box": [b[0] + x1, b[1] + y1, b[2] + x1, b[3] + y1]})
    dets = _merge_nms(dets) if len(tiles) > 1 else dets
    method = classify_queue(dets, orig_w, orig_h)
    counts = {c: 0 for c in CLASSES.values()}
    passing = {c: 0 for c in CLASSES.values()}
    for d in dets:
        (counts if d.get("in_queue", True) else passing)[d["class"]] += 1
    result = {
        "status": "ok",
        "model": f"{MODEL_PATH.stem}-coco-onnx",
        "tiles": len(tiles),
        "counts": counts,
        "passing_counts": passing,
        "queue_method": method,
        "vehicles_total": sum(counts[c] for c in VEHICLE_CLASSES),
        "passing_total": sum(passing[c] for c in VEHICLE_CLASSES),
        "queue_length_est_m": estimate_queue_m(counts),
        "summary_id": summarize(counts),
        "note": ("Hanya kendaraan yang terlihat di foto; antrean asli bisa "
                 "lebih panjang dari yang terhitung. Kendaraan yang sekadar "
                 "lewat (di luar formasi antrean) tidak dihitung."),
        "detections": dets,
    }
    if annotated_path:
        result["annotated_path"] = str(annotate(image_path, dets, annotated_path))
    return result


def annotate(image_path, detections, out_path):
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(_FONT, max(14, img.size[0] // 45))
    except Exception:
        font = ImageFont.load_default()
    for d in detections:
        x1, y1, x2, y2 = d["box"]
        passing = d.get("in_queue") is False
        color = (150, 150, 150) if passing else COLORS.get(d["class"], (255, 255, 0))
        draw.rectangle([x1, y1, x2, y2], outline=color, width=max(2, img.size[0] // 300))
        label = (f"lewat {d['class']}" if passing
                 else f"{d['class']} {d['confidence']:.2f}")
        tw = draw.textlength(label, font=font)
        draw.rectangle([x1, max(0, y1 - font.size - 6), x1 + tw + 8, y1], fill=color)
        draw.text((x1 + 4, max(0, y1 - font.size - 4)), label, font=font, fill=(0, 0, 0))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, quality=92)
    return out_path


if __name__ == "__main__":
    import sys
    res = analyze(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(json.dumps(res, ensure_ascii=False, indent=1))
