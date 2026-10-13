"""Build the satellite layout reference for the 11 city SPBUs.

WHY: the user asked for the stations' shapes/patterns to be studied
from satellite imagery so queue photos can be judged against the
station's real layout (which side is the road, where the forecourt
and canopy sit, where a queue would physically form). This script
geocodes each station address (results pinned below from the map
geocoder, with match level + relevance kept for honesty), downloads
a 3x3 Esri World Imagery tile mosaic at zoom 19 (~0.3 m/px, about
230 m across) into data/satellite/, and writes data/spbu_layout.json.

What this is NOT: satellite imagery cannot watch queues live (best
free revisit/resolution is far too coarse - see README). Automatic
photo-to-satellite pose matching of arbitrary news photos is not
reliable either; the layout file is a human-reviewed reference that
documents each station's geometry. The live queue-vs-passing call is
made per photo by the formation analysis in vision.classify_queue.
"""
import json
import math
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "satellite"
ZOOM = 19
UA = {"User-Agent": "bbm-sentinel-jember/0.3 (layout reference)"}

# code -> (lat, lng, geocoder matched_level, relevance)
GEOCODED = {
    "54.681.18": (-8.15989, 113.71997, "FULL_ADDRESS (named PERTAMINA)", 55),
    "54.681.25": (-8.17359, 113.70391, "FULL_ADDRESS (named PERTAMINA)", 72),
    "54.681.11": (-8.19142, 113.69618, "STREET", 91),
    "54.681.13": (-8.15497, 113.71251, "STREET", 81),
    "51.681.23": (-8.16882, 113.69302, "FULL_ADDRESS (low relevance)", 56),
    "53.681.35": (-8.20337, 113.69816, "FULL_ADDRESS", 92),
    "54.681.04": (-8.17419, 113.68833, "STREET", 90),
    "54.681.19": (-8.21048, 113.70050, "FULL_ADDRESS", 93),
    "54.681.12": (-8.19564, 113.65239, "FULL_ADDRESS", 93),
    "54.681.10": (-8.19080, 113.65005, "FULL_ADDRESS", 90),
    "54.681.06": (-8.13506, 113.73783, "FULL_ADDRESS (named PERTAMINA)", 100),
}


def tile_xy(lat, lng, z):
    n = 2 ** z
    x = int((lng + 180.0) / 360.0 * n)
    lat_r = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2.0 * n)
    return x, y


def fetch_tile(z, x, y):
    url = (f"https://server.arcgisonline.com/ArcGIS/rest/services/"
           f"World_Imagery/MapServer/tile/{z}/{y}/{x}")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stations = json.loads((ROOT / "data" / "spbu_kota_jember.json").read_text())["stations"]
    layout = {"generated_by": "scripts/build_spbu_layout.py",
              "imagery": "Esri World Imagery, zoom 19, 3x3 tiles (~230 m across)",
              "note": ("Reference only: station geometry for judging queue "
                       "photos. Coordinates are geocoder results; "
                       "visual_verified marks stations whose canopy/forecourt "
                       "was confirmed inside the frame by eye."),
              "stations": {}}
    existing = {}
    prev = ROOT / "data" / "spbu_layout.json"
    if prev.exists():  # keep human notes across rebuilds
        existing = json.loads(prev.read_text()).get("stations", {})
    for st in stations:
        code = st["code"]
        lat, lng, level, rel = GEOCODED[code]
        cx, cy = tile_xy(lat, lng, ZOOM)
        mosaic = Image.new("RGB", (768, 768))
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                from io import BytesIO
                mosaic.paste(Image.open(BytesIO(fetch_tile(ZOOM, cx + dx, cy + dy))),
                             ((dx + 1) * 256, (dy + 1) * 256))
        tile_path = OUT_DIR / f"{code}.jpg"
        mosaic.save(tile_path, quality=88)
        old = existing.get(code, {})
        layout["stations"][code] = {
            "name": st["name"], "address": st["address"],
            "lat": lat, "lng": lng,
            "geocode_level": level, "geocode_relevance": rel,
            "satellite_tile": f"data/satellite/{code}.jpg",
            "visual_verified": old.get("visual_verified", False),
            "layout_notes": old.get("layout_notes"),
        }
        print(code, st["name"], "->", tile_path.name)
    (ROOT / "data" / "spbu_layout.json").write_text(
        json.dumps(layout, ensure_ascii=False, indent=1))
    print("wrote data/spbu_layout.json")


if __name__ == "__main__":
    main()
