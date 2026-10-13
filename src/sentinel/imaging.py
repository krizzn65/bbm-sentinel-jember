"""Visual evidence with an honest watermark.

Every queue photo the system touches - a public CCTV snapshot, a news or
social photo, or a photo sent by the user/friends - gets a stamped copy:
the original pixels are left untouched, a header strip and a footer panel
are appended around them, and the panel states, in plain language:
  - which SPBU it is (name + code + address)
  - the date and time (WIB) the photo was taken, or, when that is not
    known, the time it was received/processed - labelled as such, never
    dressed up as capture time
  - the queue status in words, plus the measured/estimated queue length
    when one was actually recorded
  - the source of the image
A JSON sidecar + a row in evidence_images + alerts/evidence_latest.json
form the audit trail (including SHA-256 of both files), so an alert can
always be traced back to the exact image it cited."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
TZ = ZoneInfo("Asia/Jakarta")
WEEKDAYS_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
MONTHS_ID = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
             "Agustus", "September", "Oktober", "November", "Desember"]
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font(size, bold=True):
    cands = _FONT_CANDIDATES if bold else list(reversed(_FONT_CANDIDATES))
    for p in cands:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def fmt_dt_id(dt):
    dt = dt.astimezone(TZ)
    return (f"{WEEKDAYS_ID[dt.weekday()]}, {dt.day} {MONTHS_ID[dt.month - 1]} "
            f"{dt.year} • {dt:%H:%M} WIB")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _wrap(draw, text, font, max_width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def watermark_image(input_path, output_path, *, station_name, station_code=None,
                    address=None, captured_at=None, time_label="Waktu foto",
                    source_label, queue_status=None, queue_length_m=None,
                    wait_hours=None, vehicle_counts=None):
    """Write a stamped copy of the image + JSON sidecar. Returns metadata."""
    input_path, output_path = Path(input_path), Path(output_path)
    if captured_at is None:
        captured_at = datetime.now(TZ)
        time_label = "Waktu diterima sistem"
    elif captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=TZ)
    img = Image.open(input_path).convert("RGB")
    W, H = img.size
    scale = max(1.0, W / 900.0)
    pad = int(18 * scale)
    header_h = int(46 * scale)
    f_title = _font(int(30 * scale))
    f_body = _font(int(24 * scale), bold=False)
    f_brand = _font(int(22 * scale))
    probe = ImageDraw.Draw(img)
    max_w = W - 2 * pad
    line1 = station_name + (f" ({station_code})" if station_code else "")
    lines = [(line1, f_title)]
    if address:
        lines.append((address, f_body))
    lines.append((f"{time_label}: {fmt_dt_id(captured_at)}", f_body))
    q = queue_status or "belum dinilai"
    if queue_length_m:
        q += f" — antrean sekitar {queue_length_m:.0f} meter"
    if wait_hours:
        q += f" — tunggu sampai {wait_hours:.0f} jam"
    lines.append((f"Keadaan antrean: {q}", f_body))
    if vehicle_counts:
        det = ", ".join(f"{v} {k}" for k, v in vehicle_counts.items() if v)
        if det:
            lines.append((f"Terdeteksi di foto: {det} (yang terlihat saja)", f_body))
    lines.append((f"Sumber gambar: {source_label}", f_body))
    wrapped = []
    for text, font in lines:
        for part in _wrap(probe, text, font, max_w):
            wrapped.append((part, font))
    line_h = int(36 * scale)
    footer_h = pad * 2 + line_h * len(wrapped)
    canvas = Image.new("RGB", (W, H + header_h + footer_h), (12, 12, 12))
    canvas.paste(img, (0, header_h))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, W, header_h], fill=(146, 24, 24))
    draw.text((pad, int(10 * scale)), "BBM SENTINEL JEMBER — BUKTI VISUAL",
              font=f_brand, fill=(255, 255, 255))
    y = header_h + H + pad
    for text, font in wrapped:
        draw.text((pad, y), text, font=font, fill=(255, 255, 255))
        y += line_h
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=92)
    meta = {
        "station_name": station_name, "station_code": station_code,
        "address": address,
        "captured_at": captured_at.astimezone(TZ).isoformat(timespec="seconds"),
        "time_label": time_label, "source": source_label,
        "queue_status": queue_status, "queue_length_m": queue_length_m,
        "wait_hours": wait_hours, "vehicle_counts": vehicle_counts,
        "original_path": str(input_path), "watermarked_path": str(output_path),
        "original_sha256": _sha256(input_path), "watermarked_sha256": _sha256(output_path),
    }
    Path(str(output_path) + ".json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1))
    return meta


def ensure_table(store):
    store.conn.execute(
        "CREATE TABLE IF NOT EXISTS evidence_images (id INTEGER PRIMARY KEY, "
        "ts TEXT, station_code TEXT, station_name TEXT, source TEXT, "
        "captured_at TEXT, queue_status TEXT, queue_length_m REAL, "
        "original_path TEXT, watermarked_path TEXT, sha256 TEXT, "
        "vehicle_counts TEXT)")
    try:
        store.conn.execute("ALTER TABLE evidence_images ADD COLUMN vehicle_counts TEXT")
    except Exception:
        pass  # column already there
    store.conn.commit()


def register_evidence(store, meta):
    ensure_table(store)
    store.conn.execute(
        "INSERT INTO evidence_images (ts, station_code, station_name, source, "
        "captured_at, queue_status, queue_length_m, original_path, "
        "watermarked_path, sha256, vehicle_counts) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (datetime.now(TZ).isoformat(timespec="seconds"), meta.get("station_code"),
         meta.get("station_name"), meta.get("source"), meta.get("captured_at"),
         meta.get("queue_status"), meta.get("queue_length_m"),
         meta.get("original_path"), meta.get("watermarked_path"),
         meta.get("watermarked_sha256"),
         json.dumps(meta.get("vehicle_counts"), ensure_ascii=False)
         if meta.get("vehicle_counts") else None))
    store.conn.commit()
    write_manifest(store)


def latest_evidence(store, limit=5):
    ensure_table(store)
    rows = store.conn.execute(
        "SELECT station_code, station_name, source, captured_at, queue_status, "
        "queue_length_m, watermarked_path, vehicle_counts FROM evidence_images "
        "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{"station_code": r[0], "station_name": r[1], "source": r[2],
             "captured_at": r[3], "queue_status": r[4], "queue_length_m": r[5],
             "watermarked_path": r[6],
             "vehicle_counts": json.loads(r[7]) if r[7] else None} for r in rows]


def write_manifest(store):
    items = latest_evidence(store, limit=10)
    out = ROOT / "alerts" / "evidence_latest.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"images": items}, ensure_ascii=False, indent=1))
    return items
