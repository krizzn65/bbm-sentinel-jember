#!/usr/bin/env python3
"""Record a ground-truth station report (from the user / friends in chat).
Usage:
  report_ground.py 54.681.18 Pertalite kosong "antrean 300 m" Krisna
Statuses: kosong | antre_panjang | terbatas | normal"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sentinel.store import Store, now_iso

ROOT = Path(__file__).resolve().parents[1]


def main():
    code, fuel, status = sys.argv[1], sys.argv[2], sys.argv[3]
    note = sys.argv[4] if len(sys.argv) > 4 else ""
    reporter = sys.argv[5] if len(sys.argv) > 5 else ""
    store = Store(str(ROOT / "data" / "sentinel.db"))
    store.conn.execute(
        "INSERT INTO ground_reports(ts, station_code, fuel_type, status, queue_note, reporter)"
        " VALUES (?,?,?,?,?,?)",
        (now_iso(), code, fuel, status, note, reporter))
    store.conn.commit()
    print(f"recorded: {code} {fuel} {status} {note}")


if __name__ == "__main__":
    main()
