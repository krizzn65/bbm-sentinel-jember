import argparse
import json
from datetime import datetime
from pathlib import Path

from . import crisis, forecast, imaging, scoring
from .collectors import complaints, gdelt, market, meteo, news, social, stations
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
                     ("news", news.collect), ("social", social.collect),
                     ("complaints", complaints.collect)):
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
    fc, fc_lay = None, None
    try:
        fc = forecast.build_forecast(store, cfg, risk,
                                     out_path=ROOT / "alerts" / "forecast_latest.json")
        if fc:
            fc_lay = forecast.lay_summary(fc)
    except Exception as exc:  # forecast must never break the pipeline
        errors.append(f"forecast: {exc}")
    harvest_summary = None
    hcfg = cfg.get("harvest", {})
    if hcfg.get("enabled") and (active or risk >= hcfg.get("min_risk", 40)):
        try:
            from .collectors import images as image_harvest
            harvest_summary = image_harvest.harvest(store, cfg)
            image_harvest.process_inbox(store, cfg)
        except Exception as exc:
            errors.append(f"harvest: {exc}")
    try:
        evidence = imaging.latest_evidence(store, limit=5)
    except Exception:
        evidence = []
    station_fc, station_fc_lay = None, None
    try:
        from . import station_forecast
        station_fc = station_forecast.build_station_forecast(store)
        (ROOT / "alerts" / "station_forecast.json").write_text(
            json.dumps(station_fc, ensure_ascii=False, indent=1))
        station_fc_lay = station_forecast.lay_line(station_fc)
    except Exception as exc:  # never break the pipeline
        errors.append(f"station_forecast: {exc}")
    stock_sim, stock_lay = None, None
    try:
        from . import stockflow
        _analog = None
        if fc and fc.get("analog"):
            _analog = {"expected_duration_days":
                       fc["analog"].get("analogue_duration_days")}
        stock_sim = stockflow.simulate(store, feats, _analog)
        (ROOT / "alerts" / "stockflow.json").write_text(
            json.dumps(stock_sim, ensure_ascii=False, indent=1))
        _lines = stockflow.lay_lines(stock_sim)
        stock_lay = " ".join(_lines) if _lines else None
    except Exception as exc:  # never break the pipeline
        errors.append(f"stockflow: {exc}")
    try:
        _council = forecast.council(fc, stock_sim)
        if _council and fc is not None:
            fc["council"] = _council
            (ROOT / "alerts" / "forecast_latest.json").write_text(
                json.dumps(fc, ensure_ascii=False, indent=1, default=str))
            if fc.get("alert_ready") and _council.get("lay"):
                fc_lay = _council["lay"]
    except Exception as exc:  # never break the pipeline
        errors.append(f"council: {exc}")
    ml_models_report = None
    try:
        from . import ml_models
        ml_models_report = ml_models.run(store)
    except Exception as exc:
        errors.append(f"ml_models: {exc}")
    bulletin = None
    if active:
        bulletin = crisis.build_bulletin(store, risk, level, layers, feats,
                                         station_results, news_layers, cfg,
                                         prev=prev, forecast_lay=fc_lay,
                                         evidence=evidence,
                                         station_forecast_lay=station_fc_lay,
                                         stockflow_lay=stock_lay)
        try:
            from . import selfaudit
            _av, _qu, _fi = crisis._station_groups(station_results)
            _fuels = crisis.fuel_status_summary(station_results,
                                                news_layers)
            from zoneinfo import ZoneInfo
            selfaudit.append_bulletin_log(
                datetime.now(ZoneInfo(cfg.get("timezone",
                                               "Asia/Jakarta")))
                .date().isoformat(), _av, _qu, _fi,
                [f for f, i in _fuels.items()
                 if i["status"] == "kosong"])
            # Forwardable image card, same data as the text bulletin.
            from . import card as _card
            import re as _re
            _m = _re.search(r"Info BBM Jember, (.+) pukul (\S+) WIB",
                            bulletin or "")
            _card.render_card(
                ROOT / "alerts" / "bulletin_card.png",
                risk=risk,
                hari=_m.group(1) if _m else "",
                jam=_m.group(2) if _m else "",
                fuel_lines=[f"{f}: {crisis.FUEL_PLAIN.get(i['status'], i['status'])}"
                            for f, i in _fuels.items()],
                avoid=_av, queueing=_qu, fine=_fi,
                peak_line=fc_lay,
                footer_note="BBM Sentinel Jember — HIMANIKA")
        except Exception as exc:
            errors.append(f"bulletin_log: {exc}")
    audit_report = None
    try:
        from . import selfaudit
        audit_report = selfaudit.run(store, cfg)
    except Exception as exc:
        errors.append(f"selfaudit: {exc}")
    summary = {"run_id": run_id, "risk_index": risk, "level": level,
               "layer_scores": layers, "crisis_mode": active,
               "errors": errors,
               "features": {k: v for k, v in feats.items()},
               "top_stations": [
                   {"name": r["detail"]["name"], "code": r["station"]["code"],
                    "score": r["score"], "confidence": r["confidence"]}
                   for r in station_results[:5]],
               "bulletin": bulletin,
               "stockflow": ({"pertalite_city": stock_sim["city"]["Pertalite"],
                              "assumptions": stock_sim["assumptions"]}
                             if stock_sim else None),
               "ml_models": ml_models_report,
               "self_audit": ({"graded_days": audit_report["graded_days"],
                               "mean_avoid_precision":
                                   audit_report["mean_avoid_precision"],
                               "mean_fine_stability":
                                   audit_report["mean_fine_stability"]}
                              if audit_report else None),
               "station_forecast": ({"top_dry_first": [
                   {"name": r["name"], "code": r["code"],
                    "dry_risk": r["dry_risk"]}
                   for r in station_fc["ranking"][:3]]}
                   if station_fc else None),
               "social_signals": collected.get("social"),
               "complaint_signals": collected.get("complaints"),
               "upstream": (collected.get("news", {}).get("hulu")
                            if isinstance(collected.get("news"), dict)
                            else None),
               "harvest": harvest_summary,
               "evidence_images": evidence,
               "forecast": ({"peak_date": fc["peak"]["date"],
                             "peak_date_id": fc["peak"]["date_id"],
                             "peak_index": fc["peak"]["pred_index"],
                             "predicted_crisis_date": fc["predicted_crisis_date"],
                             "predicted_crisis_date_id": fc["predicted_crisis_date_id"],
                             "verification": fc["verification"],
                             "alert_ready": fc.get("alert_ready"),
                             "data_trust": fc.get("data_trust"),
                             "analog": fc.get("analog"),
                             "historical_priors": fc.get("historical_priors"),
                             "lay_summary": fc_lay} if fc else None)}
    try:
        from . import train
        ml_report = train.cycle(db_path, crisis_active=active)
        ls = ml_report["live_snapshots"]
        summary["ml"] = {
            "labelled": ls["labelled"], "positives": ls["positives"],
            "negatives": ls["negatives"],
            "labels_open": ml_report.get("labels_open"),
            "label_maintenance": ml_report.get("label_maintenance"),
            "models": {k: ("fitted" if "weights" in v else v.get("reason"))
                       for k, v in ml_report["models"].items()},
        }
    except Exception as exc:
        errors.append(f"train: {exc}")
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
