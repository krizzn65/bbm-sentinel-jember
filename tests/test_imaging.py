import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PIL import Image

from sentinel import imaging
from sentinel.store import Store


def test_format_when_date_only_is_honest():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    dt = datetime(2026, 10, 12, 0, 0, tzinfo=ZoneInfo("Asia/Jakarta"))
    assert imaging.format_when(dt) == "Senin, 12 Oktober 2026 • 00:00 WIB"
    honest = imaging.format_when(dt, date_only=True)
    assert "00:00" not in honest and "tidak tercantum" in honest


def test_watermark_appends_panels_and_sidecar(tmp_path):
    src = tmp_path / "in.jpg"
    Image.new("RGB", (900, 600), (70, 90, 120)).save(src)
    out = tmp_path / "out.jpg"
    meta = imaging.watermark_image(
        src, out, station_name="SPBU Mastrip", station_code="54.681.18",
        address="Jl. Mastrip, Tegalgede, Sumbersari",
        captured_at=datetime(2026, 10, 13, 22, 40, tzinfo=ZoneInfo("Asia/Jakarta")),
        source_label="foto laporan warga", queue_status="antre panjang",
        queue_length_m=300)
    assert out.exists() and Path(str(out) + ".json").exists()
    stamped = Image.open(out)
    assert stamped.size[0] == 900 and stamped.size[1] > 600  # panels appended
    assert meta["station_code"] == "54.681.18"
    assert meta["original_sha256"] != meta["watermarked_sha256"]
    assert "Selasa, 13 Oktober 2026" in imaging.fmt_dt_id(
        datetime(2026, 10, 13, 22, 40, tzinfo=ZoneInfo("Asia/Jakarta")))


def test_register_and_manifest(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    src = tmp_path / "in.jpg"
    Image.new("RGB", (300, 200), (10, 10, 10)).save(src)
    out = tmp_path / "out.jpg"
    meta = imaging.watermark_image(src, out, station_name="SPBU Ahmad Yani",
                                   station_code="54.681.25",
                                   source_label="CCTV publik")
    imaging.register_evidence(store, meta)
    items = imaging.latest_evidence(store)
    assert len(items) == 1 and items[0]["station_code"] == "54.681.25"
