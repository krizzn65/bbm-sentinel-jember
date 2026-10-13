#!/usr/bin/env python3
"""Stamp + register a queue photo as visual evidence.

Usage:
  python3 scripts/watermark_evidence.py FOTO.jpg --station-code 54.681.18 \
      --source "foto laporan warga (WhatsApp)" --queue-status "antre panjang" \
      --queue-m 300 --captured-at 2026-10-13T22:40

The stamped copy lands in alerts/evidence/, the original is never
modified, and the image is registered in data/sentinel.db +
alerts/evidence_latest.json so the next alert can cite/attach it."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sentinel import imaging, vision  # noqa: E402
from sentinel.collectors.stations import load_stations  # noqa: E402
from sentinel.store import Store  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Watermark + register foto bukti antrean")
    ap.add_argument("image")
    ap.add_argument("--station-code", required=True)
    ap.add_argument("--source", required=True,
                    help="mis. 'CCTV publik Dishub', 'foto laporan warga', 'foto berita'")
    ap.add_argument("--queue-status", default=None,
                    help="kata awam: lancar / antre / antre panjang / stok kosong terlihat")
    ap.add_argument("--queue-m", type=float, default=None)
    ap.add_argument("--wait-h", type=float, default=None)
    ap.add_argument("--captured-at", default=None,
                    help="ISO datetime waktu foto diambil; kosongkan bila tidak diketahui")
    ap.add_argument("--vision", action="store_true",
                    help="jalankan computer vision: hitung kendaraan per jenis, "
                         "beri kotak deteksi pada gambar, isi panjang antrean otomatis")
    args = ap.parse_args()
    stations = {s["code"]: s for s in load_stations()}
    st = stations.get(args.station_code)
    if not st:
        print(f"kode SPBU tidak dikenal: {args.station_code}")
        return 1
    src = Path(args.image)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = ROOT / "alerts" / "evidence" / f"{args.station_code}_{stamp}_stamped.jpg"
    captured = datetime.fromisoformat(args.captured_at) if args.captured_at else None
    queue_status, queue_m, counts = args.queue_status, args.queue_m, None
    if args.vision:
        annotated = ROOT / "alerts" / "evidence" / f"{args.station_code}_{stamp}_annotated.jpg"
        res = vision.analyze(src, annotated)
        if res.get("status") != "ok":
            print(f"vision tidak tersedia: {res.get('reason')}")
            return 2
        counts = {"queue": res["counts"], "passing": res["passing_counts"]}
        src = annotated  # the stamped copy carries the detection boxes
        if queue_status is None:
            queue_status = f"terhitung dari foto: {res['summary_id']}"
            if res["counts"].get("orang"):
                queue_status += f"; {res['counts']['orang']} orang terlihat"
            if res.get("passing_total"):
                queue_status += f"; {res['passing_total']} kendaraan lewat tidak dihitung"
        if queue_m is None and res["queue_length_est_m"]:
            queue_m = res["queue_length_est_m"]
        print(f"vision: {res['summary_id']} | orang {res['counts'].get('orang', 0)} "
              f"| lewat tidak dihitung {res.get('passing_total', 0)} "
              f"| perkiraan antrean {res['queue_length_est_m']} m")
    meta = imaging.watermark_image(
        src, out, station_name=st["name"], station_code=st["code"],
        address=st["address"], captured_at=captured,
        time_label="Waktu foto" if captured else "Waktu diterima sistem",
        source_label=args.source, queue_status=queue_status,
        queue_length_m=queue_m, wait_hours=args.wait_h, vehicle_counts=counts)
    store = Store(str(ROOT / "data" / "sentinel.db"))
    imaging.register_evidence(store, meta)
    print(json.dumps(meta, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
