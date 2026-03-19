"""
run_live.py  [Gen 3]
─────────────────────────────────────────────────────────────────────────────
Versi sederhana run_realtime.py — satu-shot, tanpa scheduler.
Gunakan ini untuk testing cepat atau manual check.

Usage:
  python run_live.py            → scan semua liga, tampilkan hasil
  python run_live.py --league epl   → hanya EPL
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from rich.console import Console

console = Console()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--league", type=str, default=None,
                        help="Kunci liga: epl / ucl / nba / nhl")
    args = parser.parse_args()

    cfg_path = Path("config.yaml")
    if not cfg_path.exists():
        console.print("[red]config.yaml tidak ditemukan.[/]")
        sys.exit(1)

    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # Import setelah config tersedia
    from analytics.backtester import Backtester
    from run_realtime import run_once, process_league, display_header

    display_header()
    bt = Backtester()

    if args.league:
        if args.league not in cfg["leagues"]:
            console.print(f"[red]Liga '{args.league}' tidak dikenal. Pilihan: {list(cfg['leagues'].keys())}[/]")
            sys.exit(1)
        process_league(args.league, cfg, bt)
    else:
        run_once(cfg)


if __name__ == "__main__":
    main()