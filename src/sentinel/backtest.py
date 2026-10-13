"""Leave-one-out backtest of the historical analog layer.

For every CLOSED episode: pretend it is the new crisis, find its best
analog among the OTHER closed episodes (history._similarity), and
predict duration + peak offset two ways - from that single best
analog, and from the median of the others. Compare with what really
happened. This measures whether the analog method that produces the
dated forecast ("puncak diperkirakan Sabtu ...") would have been
right in the past, and by how much it would have missed.

Honest framing: only 3 closed episodes exist, so the errors are
indicative, not statistics. The report says so, and it is regenerated
whenever a new episode closes - that is when calibration improves.
"""
from . import history


def run_backtest(episodes=None):
    eps = [e for e in (episodes if episodes is not None
                       else history.load_episodes())
           if e["status"] == "closed"]
    rows = []
    for e in eps:
        others = [o for o in eps if o["id"] != e["id"]]
        if not others:
            continue
        best = max(others, key=lambda o: history._similarity(
            e["triggers"], o["triggers"]))
        sim = history._similarity(e["triggers"], best["triggers"])
        med_dur = history._median([o["duration_days_elapsed"] for o in others])
        med_peak = history._median([o["peak_offset_days"] for o in others])
        rows.append({
            "episode": e["id"], "label": e["label"],
            "pattern": e["pattern"],
            "actual_duration_days": e["duration_days_elapsed"],
            "actual_peak_offset_days": e["peak_offset_days"],
            "best_analog": best["id"], "similarity": sim,
            "analog_duration_days": best["duration_days_elapsed"],
            "analog_peak_offset_days": best["peak_offset_days"],
            "median_duration_days": med_dur,
            "median_peak_offset_days": med_peak,
            "analog_duration_error": abs(best["duration_days_elapsed"]
                                         - e["duration_days_elapsed"]),
            "analog_peak_error": abs(best["peak_offset_days"]
                                     - e["peak_offset_days"]),
            "median_duration_error": abs(med_dur - e["duration_days_elapsed"]),
            "median_peak_error": abs(med_peak - e["peak_offset_days"]),
        })
    def mae(key):
        return round(sum(r[key] for r in rows) / len(rows), 2) if rows else None
    return {
        "episodes_tested": len(rows),
        "rows": rows,
        "mae_analog_duration_days": mae("analog_duration_error"),
        "mae_analog_peak_days": mae("analog_peak_error"),
        "mae_median_duration_days": mae("median_duration_error"),
        "mae_median_peak_days": mae("median_peak_error"),
        "note": ("Sampel sangat kecil (episode tertutup yang terdokumentasi); "
                 "angka ini indikator awal kalibrasi, bukan bukti statistik. "
                 "Bertambah satu episode tertutup = satu baris uji baru."),
    }
