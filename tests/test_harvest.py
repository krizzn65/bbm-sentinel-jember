import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sentinel.collectors import images


def test_queue_relevance():
    assert images.is_queue_relevant("Antrean Mengular di SPBU Jember, Pertalite Kosong")
    assert images.is_queue_relevant("Stok BBM Langka, Warga Antre di SPBU")
    assert not images.is_queue_relevant("Harga BBM Turun, Pengamat Beri Tanggapan")
    assert not images.is_queue_relevant("Antrean Sembako Murah di Balai Kota")


def test_extract_images_prefers_og_and_skips_logos():
    html = """
    <meta property="og:image" content="https://cdn.example.com/foto-antrean.jpg">
    <img src="/static/logo.png">
    <img src="https://cdn.example.com/isi-berita.jpg">
    """
    out = images.extract_images(html, "https://media.example.com/berita/1")
    assert out[0] == "https://cdn.example.com/foto-antrean.jpg"
    assert "https://cdn.example.com/isi-berita.jpg" in out
    assert not any("logo" in u for u in out)


def test_extract_published_from_jsonld():
    html = '<script type="application/ld+json">{"datePublished": "2026-10-13T09:43:18+07:00"}</script>'
    dt = images.extract_published(html)
    assert dt is not None and (dt.hour, dt.minute) == (9, 43)
    assert images.extract_published("<html>tanpa tanggal</html>") is None


def test_geo_gate():
    assert images.is_jember("Antrean BBM Mulai Terlihat di SPBU Ahmad Yani Jember")
    assert not images.is_jember("BBM Langka, Antrean SPBU di Sukawati Picu Kemacetan")
    assert not images.is_jember("Antrean Panjang di SPBU, Bupati Kubu Raya Ingatkan Stok")


def test_match_station_by_alias():
    st = images.match_station("Antrean panjang di SPBU Ahmad Yani sejak pagi")
    assert st and st["code"] == "54.681.25"
    st2 = images.match_station("SPBU Mastrip dekat kampus ikut antre")
    assert st2 and st2["code"] == "54.681.18"
    assert images.match_station("Antrean di SPBU sebuah kota lain") is None
