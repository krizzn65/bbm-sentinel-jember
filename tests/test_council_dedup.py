import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sentinel.forecast import council


FC = {"analog": {"expected_peak_date": "2026-10-18", "similarity": 0.48},
      "peak": {"date": "2026-10-17", "pred_index": 48.9}}


def test_council_two_agree_twin_abstains():
    twin = {"city": {"Pertalite": {"peak_dry_date": "2026-10-14",
                                   "peak_dry_share": 0.0}}}
    c = council(FC, twin)
    assert c["total"] == 2 and c["methods"] == 3, c
    assert c["agreeing"] == 2 and c["spread_days"] == 1
    assert c["date"] in ("2026-10-17", "2026-10-18")
    assert "2 dari 3 metode" in c["lay"]


def test_council_twin_votes_when_dry():
    twin = {"city": {"Pertalite": {"peak_dry_date": "2026-10-17",
                                   "peak_dry_share": 0.27}}}
    c = council(FC, twin)
    assert c["total"] == 3 and c["date"] == "2026-10-17", c


def test_council_none_without_votes():
    assert council({"analog": {}, "peak": {"pred_index": 10}}, None) is None
