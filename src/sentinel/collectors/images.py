"""Automatic queue-photo harvester.

Why this exists: SPBU CCTV has no public feed (verified 2026-10-13), and
the user should not have to photograph queues manually. During a crisis,
local media and residents DO photograph the queues and publish them.
This collector harvests those public news photos automatically:

  Google News RSS (lokal queries) -> queue-relevant articles
  -> resolve publisher URL -> extract og:image / content images
  -> station attribution by alias matching
  -> vision counting (per vehicle class) -> watermark -> evidence table

Photos dropped into alerts/inbox/ (e.g. public social-media photos the
agent forwards) go through the exact same path via process_inbox().

Honesty rules: an article photo is labelled with its source and the
article's publication time as the approximate photo time; a photo that
matches no known station is registered as a general Jember photo, never
silently attributed; hashes dedupe so the same photo is never counted
twice. Only public news pages are fetched, in small numbers."""
import hashlib
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .. import imaging, vision
from ..http_util import get_text
from .news import QUEUE_WORDS, STOCKOUT_WORDS
from .stations import load_stations

# Several Indonesian news sites 403 non-browser agents even for public
# article pages; the harvester fetches a handful of public pages per run,
# like any reader's browser would.
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

ROOT = Path(__file__).resolve().parents[3]
STATE_PATH = ROOT / "alerts" / "harvest_state.json"
HARVEST_DIR = ROOT / "alerts" / "harvest"
INBOX_DIR = ROOT / "alerts" / "inbox"
TZ = ZoneInfo("Asia/Jakarta")
SKIP_IMG = ("logo", "icon", "avatar", "sprite", "placeholder", "ads", "banner",
            "favicon", ".svg", "spacer", "blank.")


def rss_items(query, limit=40):
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(query)
           + "&hl=id&gl=ID&ceid=ID:id")
    root = ET.fromstring(get_text(url, timeout=15, retries=2))
    items = []
    for item in root.findall(".//item")[:limit]:
        try:
            pub = parsedate_to_datetime(item.findtext("pubDate"))
        except Exception:
            continue
        src_el = item.find("source")
        items.append({"title": item.findtext("title") or "",
                      "link": item.findtext("link") or "",
                      "source": (src_el.text if src_el is not None else "") or "",
                      "image": None, "pub": pub})
    return items


BING_NS = {"news": "http://schemas.microsoft.com/search/news/2008/05"}


def bing_items(query, limit=40):
    """Bing News RSS: item links are apiclick redirects that DO resolve
    to the publisher (unlike Google News links, which are JS shells),
    and many items carry a ready <News:Image> thumbnail."""
    url = ("https://www.bing.com/news/search?q=" + urllib.parse.quote(query)
           + "&format=rss&setlang=id")
    root = ET.fromstring(get_text(url, timeout=15, retries=2))
    items = []
    for item in root.findall(".//item")[:limit]:
        try:
            pub = parsedate_to_datetime(item.findtext("pubDate"))
        except Exception:
            continue
        img = item.find("news:Image", BING_NS)
        src = item.find("news:Source", BING_NS)
        items.append({"title": item.findtext("title") or "",
                      "link": item.findtext("link") or "",
                      "source": (src.text if src is not None else "") or "",
                      "image": (img.text if img is not None else None),
                      "pub": pub})
    return items


def is_queue_relevant(title):
    low = title.lower()
    if not any(w in low for w in QUEUE_WORDS + STOCKOUT_WORDS + ["langka"]):
        return False
    return any(w in low for w in ("spbu", "bbm", "bensin", "pertalite", "solar",
                                    "bahan bakar", "pertamax"))


def is_jember(title):
    """Geographic gate for PHOTO evidence. News counting tolerates loose
    regional matches; a photo stamped as Jember evidence must actually
    be Jember - the title has to say so. (First live run caught queue
    photos from Sukawati, Bali and Kubu Raya, Kalimantan slipping in
    through loosely-matched national stories.)"""
    return "jember" in title.lower()


def match_station(text, stations=None):
    """Longest-alias match wins; returns the station dict or None."""
    stations = stations if stations is not None else load_stations()
    low = text.lower()
    best, best_len = None, 0
    for st in stations:
        for alias in st["aliases"]:
            a = alias.lower().replace("spbu", "").strip()
            if len(a) >= 4 and a in low and len(a) > best_len:
                best, best_len = st, len(a)
    if best:
        return best
    for st in stations:  # fall back to the station's street name
        street = st["name"].lower().replace("spbu", "").strip()
        if len(street) >= 5 and street in low:
            return st
    return None


def extract_published(html):
    """The article page's own publication datetime (JSON-LD / meta /
    <time>) - far more precise than the RSS timestamp, which some feeds
    pad to midnight. Returns an aware datetime or None."""
    for pat in (r'"datePublished"\s*:\s*"([^"]+)"',
                r'"dateCreated"\s*:\s*"([^"]+)"',
                r'article:published_time"\s+content="([^"]+)"',
                r'<time[^>]+datetime="([^"]+)"'):
        m = re.search(pat, html)
        if m:
            try:
                dt = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=TZ)
            except ValueError:
                continue
    return None


def resolve_url(link):
    req = urllib.request.Request(link, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as resp:
        final = resp.geturl()
        html = resp.read().decode("utf-8", errors="replace")
    if "news.google.com" in final:  # interstitial: find the publisher URL
        m = re.search(r'data-n-au="([^"]+)"', html) or \
            re.search(r'href="(https?://(?!news\.google)[^"]+)"', html)
        if m:
            final = m.group(1)
            html = get_text(final, timeout=20, retries=2)
    return final, html


def extract_images(html, base_url):
    cands = []
    for pat in (r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
                r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"',
                r'<meta[^>]+name="twitter:image"[^>]+content="([^"]+)"'):
        m = re.search(pat, html, re.I)
        if m:
            cands.append(m.group(1))
    for m in re.finditer(r'<img[^>]+src="([^"]+\.(?:jpe?g|png|webp))[^"]*"', html, re.I):
        cands.append(m.group(1))
    out, seen = [], set()
    for c in cands:
        full = urllib.parse.urljoin(base_url, c.replace("&amp;", "&"))
        low = full.lower()
        if full in seen or any(s in low for s in SKIP_IMG):
            continue
        seen.add(full)
        out.append(full)
    return out


def download_image(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as resp:
        data = resp.read(9 * 1024 * 1024)
        ctype = resp.headers.get_content_type()
    if not ctype.startswith("image/") or len(data) < 30000:
        return None
    return data


def _load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"last_run": None, "image_hashes": [], "article_urls": []}


def _save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1))


def _process_photo(store, raw_path, *, station, source_label, approx_time=None):
    """vision -> annotate -> watermark -> register. Returns meta or None."""
    annotated = Path(str(raw_path).replace(".jpg", "_annotated.jpg"))
    res = vision.analyze(raw_path, annotated)
    counts, queue_m, img_for_stamp = None, None, raw_path
    if res.get("status") == "ok":
        counts = {"queue": res["counts"], "passing": res["passing_counts"]}
        queue_m = res["queue_length_est_m"] or None
        img_for_stamp = annotated
        summary = (f"terhitung dari foto: {res['summary_id']}"
                   if res["vehicles_total"] else
                   "tidak ada kendaraan terhitung jelas di foto ini")
        if res.get("passing_total"):
            summary += (f"; {res['passing_total']} kendaraan sekadar lewat "
                        f"tidak dihitung")
    else:
        summary = "keadaan antrean sesuai foto sumber"
    stamp = datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
    code = station["code"] if station else "jember-umum"
    out = ROOT / "alerts" / "evidence" / f"{code}_{stamp}_stamped.jpg"
    date_only = bool(approx_time) and \
        (approx_time.hour, approx_time.minute, approx_time.second) == (0, 0, 0)
    meta = imaging.watermark_image(
        img_for_stamp, out,
        station_name=station["name"] if station else "SPBU di Jember (dari foto berita)",
        station_code=station["code"] if station else None,
        address=station["address"] if station else
        "SPBU persisnya belum teridentifikasi dari berita",
        captured_at=approx_time,
        time_label=("Perkiraan waktu foto (dari waktu berita terbit)"
                    if approx_time else "Waktu diterima sistem"),
        source_label=source_label, queue_status=summary,
        queue_length_m=queue_m, vehicle_counts=counts, date_only=date_only)
    store_evidence(store, meta)
    return meta


def store_evidence(store, meta):
    imaging.register_evidence(store, meta)


def harvest(store, cfg, force=False):
    """One harvest pass. Returns a summary dict; never raises."""
    hcfg = (cfg or {}).get("harvest", {})
    state = _load_state()
    now = datetime.now(TZ)
    if not force and state.get("last_run"):
        last = datetime.fromisoformat(state["last_run"])
        if now - last < timedelta(hours=hcfg.get("cooldown_hours", 3)):
            return {"status": "cooldown", "new_images": 0}
    max_images = hcfg.get("max_images", 4)
    queries = hcfg.get("queries") or cfg["news_queries"]["lokal"]
    stations = load_stations()
    seen_hashes = set(state.get("image_hashes", []))
    seen_urls = set(state.get("article_urls", []))
    found, errors = [], []
    try:
        items = []
        for q in queries:
            for fetcher in (bing_items, rss_items):
                try:
                    items.extend(fetcher(q))
                except Exception as exc:
                    errors.append(f"rss {q}: {exc}")
        cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
        cands = [it for it in items if it["pub"] >= cutoff
                 and is_queue_relevant(it["title"]) and is_jember(it["title"])
                 and it["link"] not in seen_urls]
        cands.sort(key=lambda it: it["pub"], reverse=True)
        HARVEST_DIR.mkdir(parents=True, exist_ok=True)
        for it in cands:
            if len(found) >= max_images:
                break
            try:
                seen_urls.add(it["link"])
                data, page_html = None, ""
                candidates = [it["image"]] if it.get("image") else []
                if not candidates:
                    final_url, page_html = resolve_url(it["link"])
                    candidates = extract_images(page_html, final_url)[:4]
                from PIL import Image
                import io
                im = None
                for img_url in candidates:  # first usable image wins
                    if not img_url:
                        continue
                    got = download_image(img_url)
                    if not got:
                        continue
                    try:
                        cand = Image.open(io.BytesIO(got))
                        cand.load()
                    except Exception:
                        continue
                    if cand.size[0] >= 640:
                        data, im = got, cand
                        break
                if data is None or im is None:
                    continue
                digest = hashlib.sha256(data).hexdigest()
                if digest in seen_hashes:
                    continue
                seen_hashes.add(digest)
                slug = datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
                raw = HARVEST_DIR / f"{slug}_{digest[:8]}.jpg"
                im.convert("RGB").save(raw, quality=92)
                station = match_station(it["title"] + " " + page_html[:4000], stations)
                src = it["source"].strip()
                label = (f"Berita {src}: {it['title'][:90]}" if src
                         else f"Berita daring: {it['title'][:90]}")
                approx = it["pub"].astimezone(TZ)
                published = extract_published(page_html) if page_html else None
                if published is None and (approx.hour, approx.minute, approx.second) == (0, 0, 0):
                    # RSS timestamp is a midnight placeholder: fetch the
                    # article page for its real publication time.
                    try:
                        _fin, extra_html = resolve_url(it["link"])
                        published = extract_published(extra_html)
                    except Exception:
                        published = None
                if published is not None:
                    approx = published.astimezone(TZ)
                meta = _process_photo(
                    store, raw, station=station, source_label=label,
                    approx_time=approx)
                found.append({"station": meta["station_name"],
                              "watermarked": meta["watermarked_path"],
                              "vehicle_counts": meta.get("vehicle_counts")})
            except Exception as exc:
                errors.append(f"article: {exc}")
    finally:
        state["last_run"] = now.isoformat(timespec="seconds")
        state["image_hashes"] = sorted(seen_hashes)[-300:]
        state["article_urls"] = sorted(seen_urls)[-300:]
        _save_state(state)
    return {"status": "ok", "new_images": len(found), "found": found,
            "errors": errors[:4]}


def process_inbox(store, cfg):
    """Same pipeline for photos placed in alerts/inbox/ (social forwards).
    A station code in the filename (e.g. 54.681.18_foto.jpg) attributes it."""
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    stations = {st["code"]: st for st in load_stations()}
    done = 0
    for path in sorted(INBOX_DIR.glob("*")):
        if path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".mp4",
                                      ".mov", ".mkv", ".webm") \
                or not path.is_file():
            continue
        code = next((c for c in stations if c in path.name), None)
        video_wait = None
        if path.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm"):
            # Citizen video: analyse the whole clip (median queue over
            # frames + wait estimate), stamp its middle frame as the
            # photo evidence.
            import tempfile
            from .. import vision_video
            va = vision_video.analyze_video(str(path))
            meta = None
            with tempfile.TemporaryDirectory() as td:
                frames = vision_video.extract_frames(str(path), td)
                if frames:
                    meta = _process_photo(
                        store, frames[len(frames) // 2],
                        station=stations.get(code),
                        source_label="Foto dari video warga (media sosial)")
            if va.get("status") == "ok":
                video_wait = va["wait_estimate_min"]
        else:
            meta = _process_photo(
                store, path, station=stations.get(code),
                source_label="Foto dari unggahan publik (media sosial)")
        # Citizen-sensor network: a queue photo from a named reporter
        # is photographic evidence, so it also becomes a ground
        # report (marked as photo-derived and machine-counted).
        # Filename pattern: 54.681.25-budi.jpg / 54.681.25_budi.jpg.
        if code and meta and meta.get("vehicle_counts"):
            from ..store import now_iso
            vc = meta["vehicle_counts"]
            q = vc.get("queue", vc) if isinstance(vc, dict) else {}
            vehicles = sum(q.get(k, 0) for k in
                           ("motor", "mobil", "truk", "bus"))
            if vehicles >= 5:
                rest = path.name.replace(code, "").strip("-_ ")
                token = (rest.replace("_", "-").split("-")[0]
                         if rest else "")
                reporter = (token if token and len(token) > 2
                            and not token.isdigit()
                            else "jaringan mata warga")
                queue_m = meta.get("queue_length_m")
                note = (f"foto jaringan mata warga: terhitung {vehicles} "
                        f"kendaraan antre"
                        + (f" ±{queue_m:.0f} m" if queue_m else "")
                        + (f"; perkiraan waktu tunggu {video_wait[0]:.0f}-"
                           f"{video_wait[1]:.0f} menit (dari video)"
                           if video_wait else "")
                        + " (hitungan mesin dari foto, belum diverifikasi "
                          "manusia)")
                store.conn.execute(
                    "INSERT INTO ground_reports(ts, station_code,"
                    " fuel_type, status, queue_note, reporter)"
                    " VALUES (?,?,?,?,?,?)",
                    (now_iso(), code, "umum", "antre_panjang", note,
                     reporter))
                store.conn.commit()
        processed = INBOX_DIR / "processed"
        processed.mkdir(exist_ok=True)
        path.rename(processed / path.name)
        done += 1
    return {"processed": done}
