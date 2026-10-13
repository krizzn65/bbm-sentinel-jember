"""Crisis mode: entered while risk index >= ORANYE threshold or local
queues are confirmed. Produces the daily bulletin the user asked for:
crisis still ongoing / easing / over, status per fuel type, and the
per-station crisis ranking for the city + campus scope only."""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]


def crisis_active(store, risk, level, cfg):
    if risk >= cfg["crisis_mode"]["enter_risk_index"]:
        return True
    stockout = store.latest("news_lokal_stockout_mentions")
    queue = store.latest("news_lokal_queue_max_m")
    return bool((stockout and stockout["value"] >= 2)
                or (queue and queue["value"] >= 100))


def fuel_status_summary(station_results, news_layers):
    status = {}
    for layer in ("lokal", "regional"):
        for fuel, info in (news_layers.get(layer, {}).get("fuel_status") or {}).items():
            cur = status.get(fuel)
            rank = {"kosong": 3, "antre": 2, "disebut": 1}
            if cur is None or rank[info["status"]] > rank[cur["status"]]:
                status[fuel] = info
    for res in station_results:
        for fuel, info in res["detail"].get("fuel_status", {}).items():
            cur = status.get(fuel)
            rank = {"kosong": 3, "antre": 2, "disebut": 1}
            if cur is None or rank[info["status"]] > rank[cur["status"]]:
                status[fuel] = info
    return status


def build_bulletin(store, risk, level, layers, feats, station_results,
                   news_layers, cfg, prev=None):
    tz = ZoneInfo(cfg.get("timezone", "Asia/Jakarta"))
    today = datetime.now(tz).strftime("%A, %d %B %Y %H:%M WIB")
    trend = ""
    if prev:
        delta = round(risk - prev["risk_index"], 1)
        trend = f" (sebelumnya {prev['risk_index']}, perubahan {delta:+})"
    lines = [f"BULETIN KRISIS BBM JEMBER - {today}",
             f"Status kota: {level} - indeks risiko {risk}{trend}"]
    if risk < cfg["crisis_mode"]["enter_risk_index"]:
        lines.append("Mode krisis aktif karena kekosongan/antrean lokal "
                     "terkonfirmasi dari laporan, meski indeks gabungan "
                     "belum mencapai ambang ORANYE.")
    fuels = fuel_status_summary(station_results, news_layers)
    if fuels:
        lines.append("Per jenis BBM (dari laporan 24-72 jam terakhir):")
        order = {"kosong": 0, "antre": 1, "disebut": 2}
        for fuel, info in sorted(fuels.items(), key=lambda kv: order[kv[1]["status"]]):
            lines.append(f"- {fuel}: {info['status'].upper()} "
                         f"({info['mentions']} laporan)")
    else:
        lines.append("Per jenis BBM: belum ada laporan kosong/antre yang terdeteksi.")
    lines.append("SPBU kota + kampus, peringkat krisis tertinggi:")
    for res in station_results:
        d = res["detail"]
        extra = []
        if d["queue_max_m"]:
            extra.append(f"antrean s.d. {d['queue_max_m']:.0f} m")
        if d["wait_max_h"]:
            extra.append(f"tunggu s.d. {d['wait_max_h']:.0f} jam")
        lines.append(f"- {d['name']} ({d['code']}, {d['district']}): "
                     f"skor {res['score']}/100, keyakinan {res['confidence']:.0%}"
                     + (f" - {', '.join(extra)}" if extra else ""))
    lines.append("Catatan: skor SPBU adalah estimasi dari laporan berita/media "
                 "sosial terverifikasi + laporan lapangan; Pertamina tidak "
                 "mempublikasikan stok per SPBU. Nilai keyakinan rendah berarti "
                 "data tipis, bukan berarti aman.")
    text = "\n".join(lines)
    out_dir = ROOT / "alerts"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "bulletin_latest.md").write_text(text)
    with open(out_dir / "bulletin_history.jsonl", "a") as fh:
        fh.write(json.dumps({"ts": today, "risk": risk, "level": level,
                             "bulletin": text}, ensure_ascii=False) + "\n")
    return text
