import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sentinel.collectors.complaints import parse_ppid_listing

NOW = datetime(2026, 10, 14, 2, 0, tzinfo=timezone.utc)
HTML = """
<a href="https://ppid.jemberkab.go.id/berita/antrean-bbm-di-sumberjambe-camat-imbau-warga-20260909">x</a>
<a href="https://ppid.jemberkab.go.id/berita/spbu-jember-pemkab-koordinasi-pertamina-20261013">y</a>
<a href="https://ppid.jemberkab.go.id/berita/debit-air-menurun-bpbd-jember-20261013">z</a>
<a href="https://ppid.jemberkab.go.id/berita/bbm-langka-warga-antre-20261001">old</a>
"""


def test_ppid_parser_filters_fuel_and_window():
    arts = parse_ppid_listing(HTML, NOW)
    slugs = [a["slug"] for a in arts]
    # Sep article is fuel-related but outside the 72h window; the
    # Oct 1 one too. Only the Oct 13 SPBU article survives both cuts.
    assert slugs == ["spbu-jember-pemkab-koordinasi-pertamina"], slugs


def test_ppid_parser_empty_on_no_match():
    assert parse_ppid_listing("<html>tidak ada</html>", NOW) == []
