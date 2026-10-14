import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sentinel.collectors.stations import gate_fuel_status, _locality_tokens
from sentinel.crisis import _station_groups

ST = {"name": "SPBU Mastrip", "code": "54.681.18",
      "aliases": ["SPBU Mastrip", "54.681.18", "Mastrip Jember"]}


def test_gate_downgrades_foreign_story():
    fs = {"Pertalite": {"status": "kosong", "mentions": 4}}
    titles = ["Tak Ada Posko Pengaduan Motor Mbrebet di Probolinggo, "
              "Cara Lapor ke Pertamina bila Motor Mbrebet usai Diisi "
              "Pertalite - Radar Bromo",
              "Pertalite langka di Probolinggo, warga antre"]
    out = gate_fuel_status(fs, titles, _locality_tokens(ST))
    assert out["Pertalite"]["status"] == "disebut"
    assert out["Pertalite"]["unverified"] is True


def test_gate_keeps_local_stockout():
    fs = {"Pertalite": {"status": "kosong", "mentions": 2}}
    titles = ["Pertalite di SPBU Mastrip Jember kosong, warga beralih "
              "ke Pertamax"]
    out = gate_fuel_status(fs, titles, _locality_tokens(ST))
    assert out["Pertalite"]["status"] == "kosong"


def test_groups_never_call_dry_station_fine():
    res = [{"score": 5, "detail": {
        "name": "SPBU Wolter Monginsidi", "queue_max_m": 0,
        "wait_max_h": 0,
        "fuel_status": {"Solar": {"status": "kosong"}}}}]
    avoid, queueing, fine = _station_groups(res)
    assert not fine and queueing
    assert "dilaporkan habis" in queueing[0]
