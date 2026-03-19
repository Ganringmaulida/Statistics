"""
run_realtime.py  [Gen 3 — Full Scheduler]
═══════════════════════════════════════════════════════════════════════════
Real-time scheduler untuk Sports Prediction Engine.

Analoginya: seperti seorang analis professional yang bekerja sesuai
jadwal: pagi ada morning briefing, sore ada pre-match check, dan ada
pembaruan otomatis setiap jam menjelang pertandingan penting.

Mode operasi:
  python run_realtime.py           → loop terus menerus (production)
  python run_realtime.py --once    → jalankan sekali lalu selesai (testing)
  python run_realtime.py --backtest → tampilkan performance summary

Pipeline tiap run:
  1. Fetch stats + fixtures + injuries PARALEL (ThreadPoolExecutor)
  2. Build team profiles (strength_profiler)
  3. Untuk setiap fixture upcoming:
     a. Hitung probabilitas Poisson/Pythagorean (probability_engine)
     b. Ambil ELO matchup (elo_model)
     c. Ambil H2H record (h2h_fetcher)
     d. Ensemble blend semua sinyal (ensemble)
     e. Kalibrasi probabilitas (calibrator)
     f. Fetch odds + track line movement (odds_tracker)
     g. Pilih bet terbaik (bet_selector)
  4. Tampilkan hasil (display)
  5. Simpan prediksi (prediction_log)
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml
from rich.console import Console
from rich.rule import Rule

from analytics.probability_engine import calculate_probability as calculate_match_probability
from analytics.strength_profiler   import build_profiles
from analytics.elo_model           import get_matchup as elo_matchup, update_ratings
from analytics.ensemble            import apply_to_prob
from analytics.calibrator          import calibrate_triplet
from analytics.bet_selector        import select_bet
from analytics.backtester          import Backtester

from data.fetcher      import get_league_data, get_odds, get_data_sources
from data.h2h_fetcher  import get_h2h
from data.odds_tracker import record_odds, analyze_movement, cleanup_old_snapshots

from storage.prediction_log import (
    save_prediction, make_match_id, PredictionEntry, get_performance_summary
)

from ui.display         import display_match, display_header, display_data_sources
from ui.backtest_report import print_backtest_report, print_prediction_log, print_pending_results

console = Console()
logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt = "%H:%M:%S",
    handlers=[
        logging.FileHandler("predictor.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("run_realtime")


# ─────────────────────────────────────────────────────────────────────────────
# Config loader
# ─────────────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    path = Path("config.yaml")
    if not path.exists():
        logger.error("config.yaml tidak ditemukan. Buat dari template terlebih dahulu.")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ─────────────────────────────────────────────────────────────────────────────
# Core: process satu liga
# ─────────────────────────────────────────────────────────────────────────────

def process_league(league_key: str, cfg: dict, bt: Backtester) -> int:
    """
    Proses satu liga: fetch data (paralel) → prediksi → simpan.
    Returns: jumlah pertandingan diproses.
    """
    lcfg = cfg["leagues"].get(league_key, {})
    if not lcfg.get("enabled", True):
        return 0

    sport = lcfg.get("sport", "soccer")
    console.print(Rule(f"[bold cyan]{lcfg.get('name', league_key.upper())}[/]"))

    # ── 1. Parallel fetch ────────────────────────────────────────────────────
    console.print(f"  [dim]Fetching data (parallel)...[/]")
    stats, fixtures, injuries = get_league_data(league_key, cfg)

    sources = get_data_sources(league_key, cfg)
    display_data_sources(sources)

    if not fixtures:
        console.print(f"  [dim yellow]No upcoming fixtures found.[/]\n")
        return 0

    max_fix = cfg["display"]["max_fixtures"]
    fixtures = fixtures[:max_fix]

    # ── 2. Build team profiles ───────────────────────────────────────────────
    profiles = build_profiles(league_key, stats, injuries, cfg)

    processed = 0
    for fixture in fixtures:
        home = fixture["home"]
        away = fixture["away"]
        date = fixture.get("date", "")

        home_prof = profiles.get(home)
        away_prof = profiles.get(away)

        if not home_prof or not away_prof:
            # Fallback: cari dengan fuzzy matching
            home_prof = _fuzzy_profile(profiles, home)
            away_prof = _fuzzy_profile(profiles, away)

        if not home_prof or not away_prof:
            logger.debug(f"Profile not found: {home} vs {away} — skipping")
            continue

        # ── 3a. Core probability (Poisson / Pythagorean) ────────────────────
        prob = calculate_match_probability(home_prof, away_prof, cfg)

        # ── 3b. ELO matchup ─────────────────────────────────────────────────
        elo = elo_matchup(home, away, league_key, sport, cfg)

        # ── 3c. H2H record ───────────────────────────────────────────────────
        h2h = get_h2h(home, away, league_key, sport, cfg)

        # ── 3d. Ensemble blend ───────────────────────────────────────────────
        ens_result = apply_to_prob(prob, elo_matchup=elo, h2h=h2h, cfg=cfg)

        # ── 3e. Calibration ──────────────────────────────────────────────────
        ph_cal, pd_cal, pa_cal = calibrate_triplet(
            prob.p_home_win, prob.p_draw, prob.p_away_win, sport
        )
        prob.p_home_win = ph_cal
        prob.p_draw     = pd_cal
        prob.p_away_win = pa_cal

        # ── 3f. Odds + line movement ─────────────────────────────────────────
        odds = get_odds(home, away, league_key, cfg)
        match_id = make_match_id(league_key, home, away, date)
        movement = None
        if odds:
            record_odds(match_id, odds)
            movement = analyze_movement(match_id)
            # Attach market edge ke prob object
            if odds.get("moneyline_home"):
                from analytics.probability_engine import _american_to_prob
                prob.market_p_home = _american_to_prob(odds["moneyline_home"])
                prob.market_p_away = _american_to_prob(odds.get("moneyline_away", 0))
                prob.edge_moneyline_home = prob.p_home_win - prob.market_p_home
                prob.edge_moneyline_away = prob.p_away_win - prob.market_p_away

        # ── 3g. Bet selection ────────────────────────────────────────────────
        bet = select_bet(prob, odds, cfg)

        # ── 4. Display ───────────────────────────────────────────────────────
        display_match(
            prob        = prob,
            fixture     = fixture,
            bet         = bet,
            elo         = elo,
            h2h         = h2h,
            ens_result  = ens_result,
            movement    = movement,
            cfg         = cfg,
        )

        # ── 5. Save prediction ───────────────────────────────────────────────
        entry = PredictionEntry(
            match_id       = match_id,
            created_at     = datetime.now(timezone.utc).isoformat(),
            league         = league_key,
            sport          = sport,
            home           = home,
            away           = away,
            match_date     = date,
            p_home_model   = round(ph_cal, 4),
            p_draw_model   = round(pd_cal, 4),
            p_away_model   = round(pa_cal, 4),
            p_home_final   = round(prob.p_home_win, 4),
            p_draw_final   = round(prob.p_draw,     4),
            p_away_final   = round(prob.p_away_win, 4),
            elo_home       = elo.rating_home  if elo else None,
            elo_away       = elo.rating_away  if elo else None,
            elo_confidence = elo.confidence   if elo else "N/A",
            expected_home  = round(prob.expected_home, 2),
            expected_away  = round(prob.expected_away, 2),
            bet_type       = bet.bet_type,
            selection      = bet.selection,
            confidence     = bet.confidence,
            edge           = bet.edge,
            ml_home_odds   = odds.get("moneyline_home") if odds else None,
            ml_away_odds   = odds.get("moneyline_away") if odds else None,
            ml_draw_odds   = odds.get("moneyline_draw") if odds else None,
            total_line     = odds.get("total_line")     if odds else None,
            line_movement  = movement.signal if movement else "NEUTRAL",
        )
        save_prediction(entry)

        # Record ke backtester (probabilitas saja, hasil diisi nanti)
        bt.record(prob, bet, odds)

        processed += 1

    return processed


def _fuzzy_profile(profiles: dict, name: str):
    """Cari profil tim dengan toleransi perbedaan nama."""
    name_l = name.lower()
    for k, v in profiles.items():
        if k.lower() == name_l:
            return v
    for k, v in profiles.items():
        if name_l in k.lower() or k.lower() in name_l:
            return v
    # Word overlap
    name_words = set(name_l.split())
    for k, v in profiles.items():
        if name_words & set(k.lower().split()):
            return v
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Scheduled tasks
# ─────────────────────────────────────────────────────────────────────────────

def morning_report(cfg: dict) -> None:
    """Morning briefing — performance summary + pending results."""
    console.print(Rule("[bold white]☀  MORNING REPORT[/]"))
    summary = get_performance_summary()
    console.print(
        f"  Total predictions : [cyan]{summary['total']}[/]\n"
        f"  Direction accuracy: [{'bright_green' if summary['accuracy'] >= 0.55 else 'yellow'}]{summary['accuracy']:.1%}[/]\n"
        f"  Active bets       : [cyan]{summary['bets']}[/]\n"
        f"  Total P&L         : [{'bright_green' if summary['total_pnl'] >= 0 else 'bright_red'}]${summary['total_pnl']:+,.0f}[/]\n"
        f"  ROI               : [{'bright_green' if summary['roi'] >= 0 else 'bright_red'}]{summary['roi']:+.1%}[/]"
    )


def run_once(cfg: dict) -> None:
    """Jalankan satu cycle lengkap untuk semua liga yang aktif."""
    display_header()
    bt = Backtester()

    total = 0
    for lk in cfg["leagues"]:
        total += process_league(lk, cfg, bt)

    console.print(f"\n  [dim]Total pertandingan diproses: {total}[/]")
    console.print(f"  [dim]Log disimpan di: predictor.log | predictions_log.json[/]\n")


def run_scheduler(cfg: dict) -> None:
    """
    Loop terus menerus dengan jadwal harian.
    Morning report → full scan → pre-match checks.
    """
    sch = cfg.get("scheduler", {})
    morning_h    = int(sch.get("morning_report_hour", 8))
    evening_h    = int(sch.get("evening_check_hour", 18))
    cleanup_days = int(sch.get("snapshot_cleanup_days", 7))
    do_cleanup   = bool(sch.get("overnight_cleanup", True))

    last_morning = -1
    last_evening = -1

    logger.info("Scheduler started — Ctrl+C untuk berhenti")
    console.print("[bold cyan]run_realtime.py scheduler aktif. Tekan Ctrl+C untuk berhenti.[/]\n")

    while True:
        now  = datetime.now()
        hour = now.hour

        # Morning report
        if hour == morning_h and last_morning != now.date():
            morning_report(cfg)
            run_once(cfg)
            last_morning = now.date()

        # Evening check
        elif hour == evening_h and last_evening != now.date():
            run_once(cfg)
            last_evening = now.date()
            if do_cleanup:
                cleanup_old_snapshots(cleanup_days)

        # Pre-match: cek setiap jam jika dalam 3 jam sebelum kickoff
        # (implementasi sederhana: scan tiap 30 menit antara pagi-malam)
        elif morning_h < hour < evening_h:
            run_once(cfg)

        # Tidur 30 menit sebelum cek berikutnya
        time.sleep(1800)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Sports Prediction Engine — Real-time Scheduler")
    parser.add_argument("--once",     action="store_true", help="Jalankan satu kali lalu selesai")
    parser.add_argument("--backtest", action="store_true", help="Tampilkan performance report")
    parser.add_argument("--pending",  action="store_true", help="Tampilkan prediksi yang belum ada hasil")
    args = parser.parse_args()

    cfg = load_config()

    if args.backtest:
        from storage.prediction_log import load_predictions
        from analytics.backtester   import Backtester
        bt = Backtester()
        entries = load_predictions()
        for e in entries:
            if e.actual_result:
                bt.update_result(e.match_id, e.actual_home or 0, e.actual_away or 0)
        print_prediction_log(entries)
        print_backtest_report(bt.get_report())
        return

    if args.pending:
        from storage.prediction_log import pending_results
        print_pending_results(pending_results())
        return

    if args.once:
        run_once(cfg)
    else:
        run_scheduler(cfg)


if __name__ == "__main__":
    main()