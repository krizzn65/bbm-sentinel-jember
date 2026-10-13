#!/usr/bin/env python3
"""Run one automatic queue-photo harvest pass (see collectors/images.py).

Normally invoked by the pipeline itself when crisis mode is on; run
manually with --force to bypass the risk gate and cooldown."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sentinel.collectors import images  # noqa: E402
from sentinel.store import Store  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    cfg = json.loads((ROOT / "config.json").read_text())
    store = Store(ROOT / "data" / "sentinel.db")
    print(json.dumps(images.harvest(store, cfg, force=args.force),
                     ensure_ascii=False, indent=1))
    print(json.dumps(images.process_inbox(store, cfg), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
