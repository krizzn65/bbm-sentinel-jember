"""Public complaint & official-channel signals.

Two lawful, public sources - no logins, no internal systems:
1. PPID Kabupaten Jember (ppid.jemberkab.go.id/berita): the regency's
   OWN published news, server-rendered with dated slugs. Fuel-crisis
   field reports and complaint follow-ups (incl. Wadul Gus'e
   responses) appear here; the collector counts fuel-related items
   from the last 72h and mines station names from their slugs.
2. alerts/complaint_signals.json, written by the social-sweep agent:
   counts of PUBLIC complaint posts (citizens complaining publicly /
   tagging the official Wadul Gus'e accounts) and whatever the public
   LAPOR! agency wall visibly shows. Complaint CONTENTS and reporter
   identities are never collected - counts and station names only.

The internal inboxes themselves (Wadul Gus'e WhatsApp/call-center,
LAPOR! backend) are not public and are NOT accessed; if Pemkab ever
issues an official data feed/API key, it can be added here as a
third source through the credential vault.
"""
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SIGNALS_PATH = ROOT / "alerts" / "complaint_signals.json"
PPID_URL = "https://ppid.jemberkab.go.id/berita"
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 "
              "Safari/537.36"}
FUEL_SLUG_KEYS = ("bbm", "spbu", "antre", "antri", "pertalite",
                  "pertamax", "bensin", "solar", "elpiji", "minyak")
MAX_AGE_H = 6


def parse_ppid_listing(html, now, window_h=72):
    """Extract dated article slugs; return fuel-related ones inside
    the window as [{date, slug}]. Pure function (testable)."""
    out = []
    for slug, ymd in re.findall(r"/berita/([a-z0-9\-]+)-(\d{8})", html):
        try:
            d = datetime.strptime(ymd, "%Y%m%d").replace(
                tzinfo=timezone.utc)
        except ValueError:
            continue
        if now - d > timedelta(hours=window_h) or d > now + timedelta(days=1):
            continue
        if any(k in slug for k in FUEL_SLUG_KEYS):
            out.append({"date": d.date().isoformat(), "slug": slug})
    return out


def _fetch_ppid(now):
    req = urllib.request.Request(PPID_URL, headers=BROWSER_UA)
    with urllib.request.urlopen(req, timeout=25) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    return parse_ppid_listing(html, now)


def _ingest_file(store, run_id, now):
    if not SIGNALS_PATH.exists():
        return {"status": "no_signals_file"}
    try:
        data = json.loads(SIGNALS_PATH.read_text())
        ts = datetime.fromisoformat(data["ts"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_h = (now - ts).total_seconds() / 3600.0
    except Exception:
        return {"status": "signals_unreadable"}
    if age_h > MAX_AGE_H:
        return {"status": "signals_stale", "age_h": round(age_h, 1)}
    n = int(data.get("complaint_posts") or 0)
    store.observe(run_id, "lokal", "public-complaints",
                  "complaint_posts_24h", n)
    store.conn.execute(
        "INSERT INTO social_signals(ts, platform, posts_found,"
        " queue_posts, stations_mentioned, detail) VALUES (?,?,?,?,?,?)",
        (data["ts"], "aduan-publik", int(data.get("posts_found") or 0), n,
         json.dumps(data.get("stations_mentioned") or []),
         json.dumps(data.get("samples") or [], ensure_ascii=False)))
    store.conn.commit()
    return {"status": "ok", "complaint_posts": n,
            "stations_mentioned": data.get("stations_mentioned") or [],
            "age_h": round(age_h, 1)}


def collect(store, run_id, cfg):
    now = datetime.now(timezone.utc)
    result = {"ppid": None, "file": None}
    try:
        articles = _fetch_ppid(now)
        store.observe(run_id, "lokal", "ppid-jember",
                      "ppid_fuel_articles_72h", len(articles))
        result["ppid"] = {"articles_72h": len(articles),
                          "items": articles[:5]}
    except Exception as exc:  # fail soft like every collector
        result["ppid"] = {"status": "unreachable", "error": str(exc)[:120]}
    result["file"] = _ingest_file(store, run_id, now)
    return result
