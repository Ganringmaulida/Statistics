"""
app.py — Sports Prediction Engine  [Gen 3]
══════════════════════════════════════════════════════════════════════════
Jalankan: python app.py

Menu:
  1-4  → analisis liga (EPL / UCL / NBA / NHL)
  5    → semua jadwal
  6    → analisis pertandingan spesifik
  7    → backtest report
  8    → prediction log
  0    → keluar
══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analytics.strength_profiler  import build_profiles
from analytics.probability_engine import calculate_probability
from analytics.bet_selector        import select_bet
from analytics.backtester          import Backtester
from analytics.elo_model           import get_matchup as elo_matchup
from analytics.ensemble            import apply_to_prob

from data.fetcher      import get_team_stats, get_fixtures, get_injuries, get_odds, get_data_sources
from data.h2h_fetcher  import get_h2h
from data.odds_tracker import record_odds, analyze_movement

from storage.prediction_log import (
    save_prediction, make_match_id, PredictionEntry,
    load_predictions, pending_results, get_performance_summary,
)

from ui.display import (
    console, print_header, print_section, print_main_menu,
    print_strength_card, print_probability, print_recommendation,
    print_fixtures, print_match_summary_table, print_data_sources,
    prompt, loading, warn, ok,
    display_match,
)
from ui.backtest_report import print_prediction_log, print_pending_results

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

LEAGUE_KEYS = {"1": "epl", "2": "ucl", "3": "nba", "4": "nhl"}


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

def load_cfg(path: str = "config.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config tidak ditemukan: {path}")
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _is_demo(cfg: dict) -> bool:
    key = cfg.get("the_odds_api", {}).get("api_key", "")
    return "YOUR" in key or len(key) < 10


# ─────────────────────────────────────────────────────────────────────────────
# Core: analisis satu pertandingan
# ─────────────────────────────────────────────────────────────────────────────

def analyse_match(
    home_name:  str,
    away_name:  str,
    league_key: str,
    profiles:   dict,
    cfg:        dict,
    backtester: Backtester | None = None,
) -> dict:
    sport    = cfg["leagues"][league_key].get("sport", "soccer")
    home_p   = profiles.get(home_name) or _fuzzy_profile(profiles, home_name)
    away_p   = profiles.get(away_name) or _fuzzy_profile(profiles, away_name)

    if not home_p or not away_p:
        warn(f"Profil tidak ditemukan: {home_name} atau {away_name}")
        return {}

    odds = get_odds(home_name, away_name, league_key, cfg)
    prob = calculate_probability(home_p, away_p, cfg, odds)

    # ── Gen 3: ELO + H2H + Ensemble ─────────────────────────────────────────
    elo  = elo_matchup(home_name, away_name, league_key, sport, cfg)
    h2h  = get_h2h(home_name, away_name, league_key, sport, cfg)
    ens  = apply_to_prob(prob, elo_matchup=elo, h2h=h2h, cfg=cfg)

    bet  = select_bet(prob, odds, cfg)

    # Odds tracking
    match_id = make_match_id(league_key, home_name, away_name, "")
    movement = None
    if odds:
        record_odds(match_id, odds)
        movement = analyze_movement(match_id)

    if backtester is not None:
        if hasattr(backtester, "record_prediction"):
            backtester.record_prediction(prob, bet, odds)
        elif hasattr(backtester, "record"):
            backtester.record(prob, bet, odds)

    return {
        "home": home_name, "away": away_name,
        "home_profile": home_p, "away_profile": away_p,
        "prob": prob, "rec": bet, "odds": odds,
        "p_home": prob.p_home_win, "p_away": prob.p_away_win,
        "bet_type": bet.bet_type, "selection": bet.selection,
        "confidence": bet.confidence, "edge": bet.edge,
        "dixon_coles": getattr(prob, "dixon_coles_applied", False),
        "elo": elo, "h2h": h2h, "ens": ens, "movement": movement,
    }


def _fuzzy_profile(profiles: dict, name: str):
    name_l = name.lower()
    for k, v in profiles.items():
        if k.lower() == name_l or name_l in k.lower() or k.lower() in name_l:
            return v
    words = set(name_l.split())
    for k, v in profiles.items():
        if words & set(k.lower().split()):
            return v
    return None


# ─────────────────────────────────────────────────────────────────────────────
# View: satu liga penuh
# ─────────────────────────────────────────────────────────────────────────────

def view_league(league_key: str, cfg: dict, backtester: Backtester) -> None:
    lcfg = cfg["leagues"][league_key]
    name = lcfg["name"]
    print_section(f"  {name}")

    loading("Mengambil statistik tim")
    stats = get_team_stats(league_key, cfg)
    if not stats:
        warn("Tidak ada data statistik")
        return

    loading("Mengambil data cedera")
    injuries = get_injuries(league_key, cfg)

    loading("Membangun profil kekuatan tim")
    profiles = build_profiles(league_key, stats, injuries, cfg)
    ok(f"{len(profiles)} profil tim dibangun")

    sources = get_data_sources(league_key, cfg)
    print_data_sources(sources, league_key)

    loading("Mengambil jadwal pertandingan")
    fixtures = get_fixtures(league_key, cfg)
    print_fixtures(fixtures, name)

    if not fixtures:
        warn("Tidak ada jadwal — menampilkan profil tim saja")
        for p in list(profiles.values())[:4]:
            print_strength_card(p)
        return

    summary_rows  = []
    match_results = []

    for fix in fixtures:
        result = analyse_match(fix["home"], fix["away"], league_key, profiles, cfg, backtester)
        if result:
            summary_rows.append(result)
            match_results.append(result)

    if summary_rows:
        print_section("📊  Ringkasan Semua Pertandingan")
        print_match_summary_table(summary_rows, name)

    print_section("🔍  Analisis Detail Per Pertandingan")
    for r in match_results:
        display_match(
            prob=r["prob"], fixture={"home": r["home"], "away": r["away"]},
            bet=r["rec"], elo=r["elo"], h2h=r["h2h"],
            ens_result=r["ens"], movement=r["movement"], cfg=cfg,
        )


# ─────────────────────────────────────────────────────────────────────────────
# View: semua jadwal
# ─────────────────────────────────────────────────────────────────────────────

def view_all_fixtures(cfg: dict) -> None:
    print_section("📅  Semua Jadwal Pekan Ini")
    for key in ["epl", "ucl", "nba", "nhl"]:
        lcfg = cfg["leagues"].get(key, {})
        name = lcfg.get("name", key.upper())
        loading(f"  {name}")
        fixtures = get_fixtures(key, cfg)
        print_fixtures(fixtures, name)


# ─────────────────────────────────────────────────────────────────────────────
# View: satu pertandingan
# ─────────────────────────────────────────────────────────────────────────────

def view_single_match(cfg: dict, backtester: Backtester) -> None:
    print_section("🔍  Analisis Pertandingan Spesifik")
    console.print("  Liga: [cyan]epl / ucl / nba / nhl[/]")
    league_key = prompt("Kode liga").lower().strip()
    if league_key not in cfg["leagues"]:
        warn(f"Liga '{league_key}' tidak dikenali")
        return

    loading("Mengambil data")
    stats    = get_team_stats(league_key, cfg)
    injuries = get_injuries(league_key, cfg)
    profiles = build_profiles(league_key, stats, injuries, cfg)

    sources = get_data_sources(league_key, cfg)
    print_data_sources(sources, league_key)

    console.print(f"\n  Tim yang tersedia:")
    for i, name in enumerate(sorted(profiles.keys()), 1):
        console.print(f"  [dim]{i:2d}.[/] {name}")

    home_name = prompt("\nNama tim Home")
    away_name = prompt("Nama tim Away")

    result = analyse_match(home_name, away_name, league_key, profiles, cfg, backtester)
    if not result:
        return

    print_strength_card(result["home_profile"], "HOME")
    print_strength_card(result["away_profile"], "AWAY")
    display_match(
        prob=result["prob"], fixture={"home": home_name, "away": away_name},
        bet=result["rec"], elo=result["elo"], h2h=result["h2h"],
        ens_result=result["ens"], movement=result["movement"], cfg=cfg,
    )


# ─────────────────────────────────────────────────────────────────────────────
# View: backtest report
# ─────────────────────────────────────────────────────────────────────────────

def view_backtest(backtester: Backtester) -> None:
    print_section("📈  Backtest Report")
    if hasattr(backtester, "print_summary"):
        backtester.print_summary()
    entries = load_predictions()
    print_prediction_log(entries, limit=15)


# ─────────────────────────────────────────────────────────────────────────────
# View: prediction log & performance
# ─────────────────────────────────────────────────────────────────────────────

def view_prediction_log() -> None:
    print_section("📋  Prediction Log & Performance")
    summary = get_performance_summary()
    console.print(
        f"  Total : [cyan]{summary['total']}[/]  "
        f"Accuracy: [{'bright_green' if summary['accuracy'] >= 0.55 else 'yellow'}]{summary['accuracy']:.1%}[/]  "
        f"ROI: [{'bright_green' if summary['roi'] >= 0 else 'bright_red'}]{summary['roi']:+.1%}[/]"
    )
    entries = load_predictions()
    print_prediction_log(entries)
    print_pending_results(pending_results())


# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────

def run(cfg: dict) -> None:
    demo       = _is_demo(cfg)
    backtester = Backtester()

    while True:
        print_header()
        if demo:
            console.print(
                "  [bold yellow]⚠  Odds market: DEMO[/] — "
                "Stats: [bold green]REAL-TIME[/] (Understat / NHL API / ESPN)\n"
                "  [dim]Isi API keys di config.yaml untuk odds live.[/]\n"
            )
        print_main_menu(is_demo=demo)

        choice = prompt("Pilih menu")

        if choice == "0":
            console.print("\n[dim]Sampai jumpa.[/]\n")
            break
        elif choice in LEAGUE_KEYS:
            view_league(LEAGUE_KEYS[choice], cfg, backtester)
        elif choice == "5":
            view_all_fixtures(cfg)
        elif choice == "6":
            view_single_match(cfg, backtester)
        elif choice == "7":
            view_backtest(backtester)
        elif choice == "8":
            view_prediction_log()
        else:
            warn("Pilihan tidak valid")

        prompt("Tekan Enter untuk kembali ke menu")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sports Prediction Engine [Gen 3]")
    parser.add_argument("--config",   default="config.yaml")
    parser.add_argument("--league",   choices=["epl", "ucl", "nba", "nhl"])
    parser.add_argument("--fixtures", action="store_true")
    parser.add_argument("--backtest", action="store_true")
    parser.add_argument("--log",      action="store_true", help="Tampilkan prediction log")
    args = parser.parse_args()

    try:
        cfg = load_cfg(args.config)
    except FileNotFoundError as e:
        print(f"ERROR: {e}"); sys.exit(1)

    bt = Backtester()

    if args.backtest:
        print_header(); view_backtest(bt)
    elif args.fixtures:
        print_header(); view_all_fixtures(cfg)
    elif args.log:
        print_header(); view_prediction_log()
    elif args.league:
        print_header(); view_league(args.league, cfg, bt)
    else:
        run(cfg)


if __name__ == "__main__":
    main()