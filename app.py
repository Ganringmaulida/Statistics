"""
app.py — Sports Prediction Engine
Jalankan: python app.py
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
from analytics.bet_selector       import recommend_bet
from data.fetcher                 import get_team_stats, get_fixtures, get_injuries, get_odds
from ui.display import (
    console, print_header, print_section, print_main_menu,
    print_strength_card, print_probability, print_recommendation,
    print_fixtures, print_match_summary_table,
    prompt, loading, warn, ok,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s — %(message)s")

LEAGUE_KEYS = {"1": "epl", "2": "ucl", "3": "nba", "4": "nhl"}


def load_cfg(path: str = "config.yaml") -> dict:
    for p in [Path(path), Path(__file__).parent / path]:
        if p.exists():
            return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    raise FileNotFoundError("config.yaml tidak ditemukan")


def _is_demo(cfg: dict) -> bool:
    k1 = cfg.get("the_odds_api",  {}).get("api_key", "")
    k2 = cfg.get("api_football",  {}).get("api_key", "")
    return (k1 in ("", "YOUR_ODDS_API_KEY_HERE") and
            k2 in ("", "YOUR_API_FOOTBALL_KEY_HERE"))


# ─────────────────────────────────────────────────────────────────────────────
# Core: analisis satu pertandingan
# ─────────────────────────────────────────────────────────────────────────────

def analyse_match(
    home_name: str,
    away_name: str,
    league_key: str,
    profiles: dict,
    cfg: dict,
) -> dict:
    home_p = profiles.get(home_name)
    away_p = profiles.get(away_name)

    if not home_p or not away_p:
        warn(f"Profil tidak ditemukan: {home_name} atau {away_name}")
        return {}

    odds = get_odds(home_name, away_name, league_key, cfg)

    prob = calculate_probability(home_p, away_p, cfg, odds)
    rec  = recommend_bet(prob, home_p, away_p, odds, cfg)

    return {
        "home": home_name, "away": away_name,
        "home_profile": home_p, "away_profile": away_p,
        "prob": prob, "rec": rec, "odds": odds,
        "p_home": prob.p_home_win, "p_away": prob.p_away_win,
        "bet_type": rec.bet_type, "selection": rec.selection,
        "confidence": rec.confidence, "edge": rec.edge,
    }


# ─────────────────────────────────────────────────────────────────────────────
# View: satu liga penuh
# ─────────────────────────────────────────────────────────────────────────────

def view_league(league_key: str, cfg: dict, detailed: bool = True) -> None:
    lcfg = cfg["leagues"][league_key]
    name = lcfg["name"]
    flag = lcfg.get("flag", "")

    print_section(f"{flag}  {name}")

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

    loading("Mengambil jadwal pertandingan")
    fixtures = get_fixtures(league_key, cfg)
    print_fixtures(fixtures, f"{flag} {name}")

    if not fixtures:
        warn("Tidak ada jadwal ditemukan — menampilkan profil tim saja")
        for p in list(profiles.values())[:4]:
            print_strength_card(p)
        return

    # Analisis semua pertandingan mendatang
    summary_rows = []
    match_results = []

    for fix in fixtures:
        home_n = fix["home"]
        away_n = fix["away"]
        result = analyse_match(home_n, away_n, league_key, profiles, cfg)
        if result:
            summary_rows.append(result)
            match_results.append(result)

    # Tabel ringkasan semua pertandingan
    if summary_rows:
        print_section("📊  Ringkasan Semua Pertandingan")
        print_match_summary_table(summary_rows, f"{flag} {name}")

    # Detail per pertandingan
    if detailed and match_results:
        print_section("🔍  Analisis Detail Per Pertandingan")
        for r in match_results:
            print_strength_card(r["home_profile"], title_suffix="HOME")
            print_strength_card(r["away_profile"], title_suffix="AWAY")
            print_probability(r["prob"], r["home"], r["away"])
            print_recommendation(r["rec"], r["home"], r["away"])
            console.print()


# ─────────────────────────────────────────────────────────────────────────────
# View: semua jadwal
# ─────────────────────────────────────────────────────────────────────────────

def view_all_fixtures(cfg: dict) -> None:
    print_section("📅  Semua Jadwal Pekan Ini")
    for key in ["epl", "ucl", "nba", "nhl"]:
        lcfg = cfg["leagues"].get(key, {})
        name = lcfg.get("name", key.upper())
        flag = lcfg.get("flag", "")
        loading(f"{flag} {name}")
        fixtures = get_fixtures(key, cfg)
        print_fixtures(fixtures, f"{flag} {name}")


# ─────────────────────────────────────────────────────────────────────────────
# View: analisis satu pertandingan spesifik
# ─────────────────────────────────────────────────────────────────────────────

def view_single_match(cfg: dict) -> None:
    print_section("🔍  Analisis Pertandingan Spesifik")

    console.print("  Liga yang tersedia: [cyan]epl / ucl / nba / nhl[/]")
    league_key = prompt("Masukkan kode liga").lower().strip()
    if league_key not in cfg["leagues"]:
        warn(f"Liga '{league_key}' tidak dikenali")
        return

    loading("Mengambil data")
    stats    = get_team_stats(league_key, cfg)
    injuries = get_injuries(league_key, cfg)
    profiles = build_profiles(league_key, stats, injuries, cfg)

    console.print(f"\n  Tim yang tersedia:")
    for i, name in enumerate(sorted(profiles.keys()), 1):
        console.print(f"  [dim]{i:2d}.[/] {name}")

    home_name = prompt("\nNama tim Home (ketik persis)")
    away_name = prompt("Nama tim Away (ketik persis)")

    result = analyse_match(home_name, away_name, league_key, profiles, cfg)
    if not result:
        return

    print_strength_card(result["home_profile"], "HOME")
    print_strength_card(result["away_profile"], "AWAY")
    print_probability(result["prob"], home_name, away_name)
    print_recommendation(result["rec"], home_name, away_name)


# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────

def run(cfg: dict) -> None:
    demo = _is_demo(cfg)

    while True:
        print_header()
        if demo:
            console.print(
                "  [bold yellow]⚠  DEMO MODE[/] — Menggunakan data sampel realistis.\n"
                "  [dim]Isi API key di config.yaml untuk data live.[/]\n"
            )
        print_main_menu(is_demo=demo)

        choice = prompt("Pilih menu")

        if choice == "0":
            console.print("\n[dim]Sampai jumpa.[/]\n")
            break
        elif choice in LEAGUE_KEYS:
            view_league(LEAGUE_KEYS[choice], cfg)
        elif choice == "5":
            view_all_fixtures(cfg)
        elif choice == "6":
            view_single_match(cfg)
        else:
            warn("Pilihan tidak valid")

        prompt("Tekan Enter untuk kembali ke menu")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sports Prediction Engine")
    parser.add_argument("--config",  default="config.yaml")
    parser.add_argument("--league",  choices=["epl","ucl","nba","nhl"])
    parser.add_argument("--fixtures",action="store_true")
    args = parser.parse_args()

    try:
        cfg = load_cfg(args.config)
    except FileNotFoundError as e:
        print(f"ERROR: {e}"); sys.exit(1)

    if args.fixtures:
        print_header(); view_all_fixtures(cfg)
    elif args.league:
        print_header(); view_league(args.league, cfg)
    else:
        run(cfg)


if __name__ == "__main__":
    main()