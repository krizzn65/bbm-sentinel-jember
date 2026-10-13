import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sentinel import history
from sentinel.store import Store


def test_priors_from_closed_episodes():
    p = history.priors()
    assert p["episodes_closed"] == 3
    assert p["median_duration_days"] == 7
    assert p["median_peak_offset_days"] == 2
    assert p["by_pattern"]["panic_information"]["median_duration_days"] == 4
    assert p["trigger_frequency"]["ketapang_congestion"] == 0.67


def test_similarity_identical_is_one():
    eps = history.load_episodes()
    jul = next(e for e in eps if e["id"] == "2025-07-gumitir")
    assert history._similarity(jul["triggers"], jul["triggers"]) == 1.0


def test_analog_picks_september_for_corridor_pattern(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    rid = store.start_run()
    store.observe(rid, "regional", "google-news-rss",
                  "news_regional_trigger_ketapang_congestion", 3)
    store.observe(rid, "regional", "google-news-rss",
                  "news_regional_trigger_gumitir_disruption", 2)
    store.observe(rid, "regional", "google-news-rss",
                  "news_regional_trigger_high_waves", 1)
    store.observe(rid, "lokal", "google-news-rss",
                  "news_lokal_stockout_mentions", 4)
    out = history.analog_forecast(store, {"timezone": "Asia/Jakarta"})
    assert out["analogue"] is not None
    assert out["analogue"]["episode_id"] == "2026-09-distribution"
    assert out["similarity"] >= 0.5
