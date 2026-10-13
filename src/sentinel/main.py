import argparse
import json
from pathlib import Path

from . import crisis, scoring
from .collectors import gdelt, market, meteo, news, stations
from .store import Store

ROOT = Path(__file__).resolve().parents[2]


def load_cfg():
    return json.loads((ROOT / "config.json").read_text())


def seed_labels(store):
    data = json.loads((ROOT / "data" / "episodes.json").read_text())
    n = store.conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0]
    if n:
        return
    for ep in data["episodes"]:
        store.conn.execute(
            "INSERT INTO labels(start, end, outcome, label, triggers) VALUES (?,?,?,?,?)",
            (ep["start"], ep["end"], ep["outcome"], ep["label"],
             json.dumps(ep["triggers"], ensure_ascii=False)))
    store.conn.commit()


def run(db_path=None, with_gdelt=False, with_stations=True):
    cfg = load_cfg()
    store = Store(db_path or str(ROOT / "data" / "sentinel.db"))
    seed_labels(store)
    run_id = store.start_run()
    collected, errors = {}, []
    for name, fn in (("market", market.collect), ("meteo", meteo.collect),
                     ("news", news.collect)):
        try:
            collected[name] = fn(store, run_id, cfg)
            print(f"[sentinel] collector {name} ok", flush=True)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            print(f"[sentinel] collector {name} FAILED: {exc}", flush=True)
    if with_gdelt:
        try:
            collected["gdelt"] = gdelt.collect(store, run_id, cfg)
        except Exception as exc:
            errors.append(f"gdelt: {exc}")
    station_results = []
    # Station scans are the heaviest Google News load (22 queries). Outside
    # elevated risk they run every 4th cycle; at KUNING+ or with a recent
    # crisis they run every cycle. This also reduces rate-limit blocks,
    # which otherwise zero out the news layer for a whole run.
    last = store.last_risk()
    scan_stations = with_stations and (
        last is None or last["risk_index"] >= 35 or run_id % 4 == 0)
    if scan_stations:
        try:
            station_results = stations.collect(store, run_id, cfg)
            print("[sentinel] collector stations ok", flush=True)
        except Exception as exc:
            errors.append(f"stations: {exc}")
    else:
        print("[sentinel] stations skipped this cycle (low risk, throttled)",
              flush=True)
    feats = scoring.build_features(store, cfg)
    layers = scoring.layer_scores(feats)
    risk = scoring.risk_index(layers, cfg)
    level = scoring.level_of(risk, cfg)
    prev = store.last_risk()
    store.save_risk(run_id, risk, level, layers, feats)
    news_layers = collected.get("news", {})
    active = crisis.crisis_active(store, risk, level, cfg)
    bulletin = None
    if active:
        bulletin = crisis.build_bulletin(store, risk, level, layers, feats,
                                         station_results, news_layers, cfg,
                                         prev=prev)
    summary = {"run_id": run_id, "risk_index": risk, "level": level,
               "layer_scores": layers, "crisis_mode": active,
               "errors": errors,
               "features": {k: v for k, v in feats.items()},
               "top_stations": [
                   {"name": r["detail"]["name"], "code": r["station"]["code"],
                    "score": r["score"], "confidence": r["confidence"]}
                   for r in station_results[:5]],
               "bulletin": bulletin}
    out_dir = ROOT / "alerts"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "latest_run.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    store.finish_run(run_id, "ok" if not errors else "partial",
                     f"risk={risk} level={level} crisis={active}")
    return summary


def main():
    ap = argparse.ArgumentParser(description="BBM Sentinel Jember: one pipeline run")
    ap.add_argument("--db", default=None)
    ap.add_argument("--gdelt", action="store_true", help="also poll GDELT (slow, throttled)")
    ap.add_argument("--no-stations", action="store_true")
    args = ap.parse_args()
    summary = run(args.db, with_gdelt=args.gdelt,
                  with_stations=not args.no_stations)
    print(json.dumps({k: summary[k] for k in
                      ("run_id", "risk_index", "level", "layer_scores",
                       "crisis_mode", "errors", "top_stations")},
                     ensure_ascii=False, indent=1))
    if summary["bulletin"]:
        print("\n" + summary["bulletin"])


if __name__ == "__main__":
    main()
