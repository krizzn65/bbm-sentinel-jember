import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sentinel.scoring import layer_scores, risk_index, FUNNEL_LAYERS


CFG = {"layer_weights": {"dunia": 0.08, "asia": 0.05, "asean": 0.05,
                         "indonesia": 0.14, "jawa": 0.08, "jatim": 0.10,
                         "tapal_kuda": 0.20, "jember": 0.16,
                         "kota_kampus": 0.14}}


def test_weights_sum_to_one():
    assert abs(sum(CFG["layer_weights"].values()) - 1.0) < 1e-9
    assert set(CFG["layer_weights"]) == set(FUNNEL_LAYERS)


def test_renormalisation_over_present_layers():
    feats = {"a": {"layer": "tapal_kuda", "score": 80.0},
             "b": {"layer": "jember", "score": 40.0}}
    layers = layer_scores(feats)
    assert layers["tapal_kuda"] == 80.0 and layers["dunia"] is None
    idx = risk_index(layers, CFG)
    # only tapal_kuda (0.20) and jember (0.16) present
    expect = (80 * 0.20 + 40 * 0.16) / 0.36
    assert abs(idx - round(expect, 1)) < 0.11, idx


def test_no_layers_no_fake_risk():
    assert risk_index(layer_scores({}), CFG) == 0.0
