#!/usr/bin/env python3
"""Record a ground-truth station report (from the user / friends).

Positional form:
  report_ground.py 54.681.18 Pertalite kosong "antrean 300 m" Krisna
Statuses: kosong | antre_panjang | terbatas | normal

Free-text form (what a chat message looks like):
  report_ground.py --text "Ahmad Yani pertalite kosong, antrean mengular" Krisna
The parser matches the station by code, name, or alias; the fuel by
keyword; the status by keyword (kosong/habis, antre panjang/mengular,
terbatas/menipis, normal/lancar). Unparseable text is rejected, never
guessed at.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sentinel.store import Store, now_iso
from sentinel.collectors.stations import load_stations

ROOT = Path(__file__).resolve().parents[1]

_FUELS = [("pertalite", "Pertalite"), ("pertamax", "Pertamax"),
          ("bio solar", "Solar"), ("biosolar", "Solar"), ("solar", "Solar"),
          ("dexlite", "Dexlite"), ("dex", "Dex")]
_STATUS = [(r"kosong|habis", "kosong"),
           (r"antre\s*panjang|mengular|antrean\s*panjang", "antre_panjang"),
           (r"terbatas|menipis|sedikit", "terbatas"),
           (r"normal|lancar|aman", "normal")]


def _station_keys(st):
    """Match keys from formal name/aliases down to the distinctive
    short form a chat message actually uses ('Ahmad Yani', 'Mastrip',
    'Tegal Besar'). Longest keys win so 'Mangli Brawijaya' is not
    swallowed by plain 'Mangli'."""
    keys = {st["code"].lower()}
    raw = [st["name"]] + st.get("aliases", [])
    for name in raw:
        n = name.lower().replace("spbu", "").strip()
        for part in re.split(r"[/()]", n):
            part = part.strip(" ,")
            if len(part) >= 4:
                keys.add(part)
    return sorted(keys, key=len, reverse=True)


def parse_text(text):
    low = text.lower()
    station, best = None, -1
    for st in load_stations():
        for key in _station_keys(st):
            if key in low and len(key) > best:
                station, best = st, len(key)
    if station is None:
        return None
    fuel = "umum"
    for kw, canon in _FUELS:
        if kw in low:
            fuel = canon
            break
    status = None
    for pat, canon in _STATUS:
        if re.search(pat, low):
            status = canon
            break
    if status is None:
        return None
    return {"code": station["code"], "fuel": fuel, "status": status}


def record(store, code, fuel, status, note, reporter):
    store.conn.execute(
        "INSERT INTO ground_reports(ts, station_code, fuel_type, status,"
        " queue_note, reporter) VALUES (?,?,?,?,?,?)",
        (now_iso(), code, fuel, status, note, reporter))
    store.conn.commit()
    print(f"recorded: {code} {fuel} {status} {note}")


def main():
    store = Store(str(ROOT / "data" / "sentinel.db"))
    if len(sys.argv) > 1 and sys.argv[1] == "--text":
        text = sys.argv[2]
        reporter = sys.argv[3] if len(sys.argv) > 3 else "Krisna (chat)"
        parsed = parse_text(text)
        if not parsed:
            print("TIDAK TERCATAT: stasiun atau status tidak dikenali "
                  "dari teks; tidak menebak.")
            return 2
        record(store, parsed["code"], parsed["fuel"], parsed["status"],
               text, reporter)
        return 0
    code, fuel, status = sys.argv[1], sys.argv[2], sys.argv[3]
    note = sys.argv[4] if len(sys.argv) > 4 else ""
    reporter = sys.argv[5] if len(sys.argv) > 5 else ""
    record(store, code, fuel, status, note, reporter)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
