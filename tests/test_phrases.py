import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sentinel.collectors.news import mine_phrases


def test_stockout_and_queue():
    out = mine_phrases(["Pertalite kosong di SPBU Jember, antrean 500 meter",
                        "Warga antre 2 jam untuk Pertamax"])
    assert out["stockout_mentions"] >= 1
    assert out["queue_max_m"] == 500
    assert out["wait_max_h"] == 2
    assert out["fuel_status"]["Pertalite"]["status"] == "kosong"


def test_km_conversion():
    out = mine_phrases(["Antrean BBM mengular hingga 2 km di Jember"])
    assert out["queue_max_m"] == 2000
