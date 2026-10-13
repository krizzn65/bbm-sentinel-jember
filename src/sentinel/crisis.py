"""Crisis mode + the human bulletin.

Two audiences, two formats, deliberately kept apart:
- machines (SQLite, latest_run.json) keep every number: risk index, layer
  scores, station scores, confidence.
- humans (this bulletin, WhatsApp) get plain language only: a simple
  status word, what is happening in one or two sentences, which fuel is
  hard to find, which stations to avoid and which are still fine, and one
  concrete suggestion. No index values, no scores, no percentages, no
  jargon. Station groups are translated from scores: >=60 avoid for now,
  30-59 queueing but moving, <30 still relatively fine.

Crisis mode itself is entered while the risk index is ORANYE+ or local
stock-outs / queues are confirmed by reports."""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]

LEVEL_PLAIN = {
    "HIJAU": "AMAN",
    "KUNING": "WASPADA",
    "ORANYE": "SIAGA, antrean likely dalam 1-3 hari",
    "MERAH": "KRISIS",
}
FUEL_PLAIN = {
    "kosong": "habis di beberapa SPBU",
    "antre": "antre panjang",
    "disebut": "masih tersedia",
}


def crisis_active(store, risk, level, cfg):
    if risk >= cfg["crisis_mode"]["enter_risk_index"]:
        return True
    stockout = store.latest("news_lokal_stockout_mentions")
    queue = store.latest("news_lokal_queue_max_m")
    return bool((stockout and stockout["value"] >= 2)
                or (queue and queue["value"] >= 100))


def fuel_status_summary(station_results, news_layers):
    status = {}
    rank = {"kosong": 3, "antre": 2, "disebut": 1}
    for layer in ("lokal", "regional"):
        for fuel, info in (news_layers.get(layer, {}).get("fuel_status") or {}).items():
            cur = status.get(fuel)
            if cur is None or rank[info["status"]] > rank[cur["status"]]:
                status[fuel] = info
    for res in station_results:
        for fuel, info in res["detail"].get("fuel_status", {}).items():
            cur = status.get(fuel)
            if cur is None or rank[info["status"]] > rank[cur["status"]]:
                status[fuel] = info
    return status


def _station_groups(station_results):
    avoid, queueing, fine = [], [], []
    for res in station_results:
        d = res["detail"]
        label = d["name"].replace("SPBU ", "")
        if d["queue_max_m"]:
            label += f" (antrean sekitar {d['queue_max_m']:.0f} meter)"
        elif d["wait_max_h"]:
            label += f" (nunggu sampai {d['wait_max_h']:.0f} jam)"
        if res["score"] >= 60:
            avoid.append(label)
        elif res["score"] >= 30:
            queueing.append(label)
        elif res["score"] > 0:
            fine.append(label)
        else:
            fine.append(label)
    return avoid, queueing, fine


def build_bulletin(store, risk, level, layers, feats, station_results,
                   news_layers, cfg, prev=None, forecast_lay=None, evidence=None):
    tz = ZoneInfo(cfg.get("timezone", "Asia/Jakarta"))
    now = datetime.now(tz)
    hari = now.strftime("%A, %d %B %Y")
    for en, idn in (("Monday", "Senin"), ("Tuesday", "Selasa"),
                    ("Wednesday", "Rabu"), ("Thursday", "Kamis"),
                    ("Friday", "Jumat"), ("Saturday", "Sabtu"),
                    ("Sunday", "Minggu"), ("January", "Januari"),
                    ("February", "Februari"), ("March", "Maret"),
                    ("April", "April"), ("May", "Mei"), ("June", "Juni"),
                    ("July", "Juli"), ("August", "Agustus"),
                    ("September", "September"), ("October", "Oktober"),
                    ("November", "November"), ("December", "Desember")):
        hari = hari.replace(en, idn)
    jam = now.strftime("%H:%M")
    status_plain = LEVEL_PLAIN.get(level, level)
    if risk < cfg["crisis_mode"]["enter_risk_index"]:
        status_plain = "ADA SPBU KEHABISAN STOK"
    trend_word = ""
    if prev:
        delta = risk - prev["risk_index"]
        if delta >= 5:
            trend_word = " Kondisinya lagi memburuk dibanding pantauan sebelumnya."
        elif delta <= -5:
            trend_word = " Kondisinya mulai membaik dibanding pantauan sebelumnya."
    lines = [f"Info BBM Jember, {hari} pukul {jam} WIB",
             f"Status: {status_plain}.{trend_word}"]
    if forecast_lay:
        lines.append(forecast_lay)
    lines.append("")
    fuels = fuel_status_summary(station_results, news_layers)
    if fuels:
        lines.append("Bensin yang lagi susah dicari:")
        order = {"kosong": 0, "antre": 1, "disebut": 2}
        for fuel, info in sorted(fuels.items(), key=lambda kv: order[kv[1]["status"]]):
            lines.append(f"- {fuel}: {FUEL_PLAIN[info['status']]}")
        lines.append("")
    if station_results:
        avoid, queueing, fine = _station_groups(station_results)
        if avoid:
            lines.append("Paling parah, hindari dulu:")
            lines += [f"- {s}" for s in avoid]
        if queueing:
            lines.append("Antre, tapi masih jalan:")
            lines += [f"- {s}" for s in queueing]
        if fine:
            lines.append("Masih relatif lancar:")
            lines += [f"- {s}" for s in fine[:4]]
        lines.append("")
    if evidence:
        from .imaging import fmt_dt_id
        lines.append("Foto bukti terbaru (gambarnya terlampir):")
        for ev in evidence[:3]:
            when = ""
            try:
                when = " — " + fmt_dt_id(datetime.fromisoformat(ev["captured_at"]))
            except Exception:
                pass
            q = ev.get("queue_status") or "keadaan antrean tercatat di gambar"
            if ev.get("queue_length_m"):
                q += f", sekitar {ev['queue_length_m']:.0f} meter"
            vc = ev.get("vehicle_counts") or {}
            det = ", ".join(f"{v} {k}" for k, v in vc.items()
                            if v and k in ("motor", "mobil", "truk", "bus"))
            if det:
                q += f" (terhitung di foto: {det})"
            lines.append(f"- {ev['station_name']}: {q}{when}")
        lines.append("")
    worst_fuel = None
    if fuels:
        worst_fuel = sorted(fuels.items(),
                            key=lambda kv: {"kosong": 0, "antre": 1, "disebut": 2}[kv[1]["status"]])[0][0]
    if worst_fuel and fuels[worst_fuel]["status"] == "kosong":
        lines.append(f"Saran: kalau {worst_fuel} di kendaraanmu tinggal sedikit, "
                     "isi hari ini di SPBU yang masih lancar di atas. "
                     "Isi secukupnya saja, tidak perlu menimbun.")
    else:
        lines.append("Saran: isi seperti biasa, secukupnya. Belum perlu ikut antre panjang.")
    lines.append("")
    lines.append("Sumber: laporan berita dan warga hari ini. Keadaan di SPBU "
                 "bisa berubah sewaktu-waktu.")
    text = "\n".join(lines)
    out_dir = ROOT / "alerts"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "bulletin_latest.md").write_text(text)
    with open(out_dir / "bulletin_history.jsonl", "a") as fh:
        fh.write(json.dumps({"ts": f"{hari} {jam}", "risk": risk, "level": level,
                             "bulletin": text}, ensure_ascii=False) + "\n")
    return text
