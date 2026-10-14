"""Video queue analysis: from a citizen's queue VIDEO to a wait time.

A photo shows a queue once; a video shows it several times. This
samples up to `max_frames` evenly spaced frames, runs the same
formation analysis per frame, and aggregates MEDIAN queue counts
(robust against a single bad frame). The wait estimate for the last
person in line assumes ONE active service lane and published-style
service times per vehicle class:

    motor 45-75 s | mobil 90-150 s | truk/bus 180-300 s

Those are transparent assumptions, printed in the output - a rough
range, never a promise. Without ffmpeg the module reports
"unavailable"; it never fabricates numbers.
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import vision

SERVICE_S = {"motor": (45, 75), "mobil": (90, 150),
             "truk": (180, 300), "bus": (180, 300)}
CLASSES = ("orang", "sepeda", "mobil", "motor", "bus", "truk")


def extract_frames(video_path, out_dir, max_frames=6):
    """Evenly spaced frames via ffmpeg. Returns [Path] or []."""
    if not shutil.which("ffmpeg"):
        return []
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(video_path)],
        capture_output=True, text=True, timeout=30)
    try:
        dur = float(json.loads(probe.stdout)["format"]["duration"])
    except Exception:
        return []
    if dur <= 0:
        return []
    out = []
    for i in range(max_frames):
        t = dur * (i + 0.5) / max_frames
        fp = Path(out_dir) / f"frame_{i}.jpg"
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i",
             str(video_path), "-frames:v", "1", "-q:v", "3", str(fp)],
            capture_output=True, timeout=30)
        if r.returncode == 0 and fp.exists():
            out.append(fp)
    return out


def _median(vals):
    vals = sorted(vals)
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def wait_range_minutes(queue_counts):
    """(low, high) minutes for the last in line, one service lane."""
    lo = hi = 0.0
    for cls, (a, b) in SERVICE_S.items():
        n = queue_counts.get(cls, 0)
        lo += n * a
        hi += n * b
    return round(lo / 60.0, 1), round(hi / 60.0, 1)


def analyze_video(video_path, max_frames=6):
    if not shutil.which("ffmpeg"):
        return {"status": "unavailable", "reason": "ffmpeg tidak ada"}
    with tempfile.TemporaryDirectory() as td:
        frames = extract_frames(video_path, td, max_frames)
        if not frames:
            return {"status": "unavailable",
                    "reason": "tidak ada bingkai terbaca dari video"}
        per_frame = []
        for fp in frames:
            res = vision.analyze(str(fp))
            if res.get("status") == "ok":
                per_frame.append(res)
        if not per_frame:
            return {"status": "unavailable",
                    "reason": "model vision gagal di semua bingkai"}
        med_counts = {c: int(_median([r["counts"].get(c, 0)
                                      for r in per_frame]))
                      for c in CLASSES}
        med_m = _median([r["queue_length_est_m"] or 0 for r in per_frame])
        lo, hi = wait_range_minutes(med_counts)
        vehicles = sum(med_counts[k] for k in SERVICE_S)
        return {
            "status": "ok", "frames_used": len(per_frame),
            "queue_counts_median": med_counts,
            "queue_length_est_m": round(med_m, 1),
            "vehicles_queue_median": vehicles,
            "wait_estimate_min": [lo, hi],
            "wait_assumption": ("satu lajur layanan aktif; waktu layan "
                                "per kendaraan: motor 45-75 dtk, mobil "
                                "90-150 dtk, truk/bus 180-300 dtk; "
                                "perkiraan kasar untuk orang terakhir "
                                "di antrean"),
            "middle_frame_index": len(frames) // 2,
        }
