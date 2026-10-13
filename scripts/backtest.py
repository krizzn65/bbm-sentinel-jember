#!/usr/bin/env python3
"""Run the leave-one-out analog backtest and write
alerts/backtest_report.json. See sentinel/backtest.py."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sentinel import backtest

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    report = backtest.run_backtest()
    out = ROOT / "alerts" / "backtest_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"episodes tested: {report['episodes_tested']}")
    for r in report["rows"]:
        print(f"- {r['episode']}: analog {r['best_analog']} "
              f"(sim {r['similarity']}) | durasi nyata "
              f"{r['actual_duration_days']}d vs analog "
              f"{r['analog_duration_days']}d (err {r['analog_duration_error']}) "
              f"| puncak nyata h+{r['actual_peak_offset_days']} vs analog "
              f"h+{r['analog_peak_offset_days']} (err {r['analog_peak_error']})")
    print(f"MAE analog: durasi {report['mae_analog_duration_days']} hari, "
          f"puncak {report['mae_analog_peak_days']} hari")
    print(f"MAE median: durasi {report['mae_median_duration_days']} hari, "
          f"puncak {report['mae_median_peak_days']} hari")
    print(f"report -> {out}")
