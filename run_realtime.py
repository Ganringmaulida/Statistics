"""
run_realtime.py  —  Gen 3 Real-Time Scheduler
═══════════════════════════════════════════════════════════════════════════
FIX v2: Semua import Gen 3 dipindah ke DALAM fungsi (lazy import).
Script tetap jalan meski Gen 3 belum terpasang — fallback ke Gen 2.
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Path setup PERTAMA sebelum import apapun ─────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ── Import Gen 2 (harus selalu ada) ──────────────────────────────────────────
from analytics.strength_profiler  import build_profiles
from analytics.probability_engine import calculate_probability
from analytics.bet_selector       import recommend_bet
from data.fetcher                 import get_team_stats, get_fixtures, get_injuries, get_odds
from ui.display                   import console, print_header, print_section

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("realtime")

LEAGUES = ["epl", "ucl", "nba", "nhl"]


# ─────────────────────────────────────────────────────────────────────────────
# Cek ketersediaan modul Gen 3 (lazy — tidak crash jika tidak ada)
# ─────────────────────────────────────────────────────────────────────────────

def _check_gen3() -> dict:
    """
    Periksa modul Gen 3 mana yang tersedia.
    Mengembalikan dict status tanpa crash.
    """
    status = {
        "odds_tracker":    False,
        "h2h_fetcher":     False,
        "elo_model":       False,
        "prediction_log":  False,
        "apscheduler":     False,
        "storage_pkg":     False,
    }

    try:
        from data.odds_tracker import track_odds, get_movement_summary  # noqa
        status["odds_tracker"] = True
    except (ImportError, ModuleNotFoundError):
        pass

    try:
        from data.h2h_fetcher import get_h2h, apply_h2h_adjustment  # noqa
        status["h2h_fetcher"] = True
    except (ImportError, ModuleNotFoundError):
        pass

    try:
        from analytics.elo_model import (  # noqa
            calculate_elo_matchup, blend_with_elo,
            seed_elo_from_stats, get_store,
        )
        status["elo_model"] = True
    except (ImportError, ModuleNotFoundError):
        pass

    try:
        from storage.prediction_log import save_prediction, make_match_id, PredictionEntry  # noqa
        status["prediction_log"] = True
    except (ImportError, ModuleNotFoundError):
        pass

    try:
        from apscheduler.schedulers.blocking import BlockingScheduler  # noqa
        status["apscheduler"] = True
    except ImportError:
        pass

    status["storage_pkg"] = Path("storage/__init__.py").exists()

    return status


def _print_status(status: dict) -> None:
    """Tampilkan status modul saat startup."""
    console.print("\n  [bold white]── STATUS MODUL ──[/]")

    items = [
        ("Gen 2 Core",          True,                        "analytics + data + ui"),
        ("Gen 3 odds_tracker",  status["odds_tracker"],      "data/odds_tracker.py"),
        ("Gen 3 h2h_fetcher",   status["h2h_fetcher"],       "data/h2h_fetcher.py"),
        ("Gen 3 elo_model",     status["elo_model"],         "analytics/elo_model.py"),
        ("Gen 3 prediction_log",status["prediction_log"],    "storage/prediction_log.py"),
        ("APScheduler",         status["apscheduler"],       "pip install apscheduler"),
    ]

    for label, ok, note in items:
        if ok:
            console.print(f"  [bold green]✅[/] {label:<28} [dim]{note}[/]")
        else:
            console.print(f"  [bold yellow]⚠ [/] {label:<28} [dim red]tidak tersedia — {note}[/]")

    gen3_count = sum([
        status["odds_tracker"], status["h2h_fetcher"],
        status["elo_model"],    status["prediction_log"],
    ])

    if gen3_count == 4:
        console.print("\n  [bold bright_green]Mode: GEN 3 FULL[/] — ELO + H2H + Line Movement + Prediction Log\n")
    elif gen3_count > 0:
        console.print(f"\n  [bold yellow]Mode: GEN 3 PARTIAL ({gen3_count}/4 modul)[/] — fitur tersedia sebagian\n")
    else:
        console.print("\n  [bold cyan]Mode: GEN 2 ONLY[/] — Poisson/Pythagorean + Bet Selector\n")
        console.print(
            "  [dim]Untuk aktifkan Gen 3: copy file dari output gen3_additions/ "
            "ke folder ini.[/]\n"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

def load_cfg(path: str = "config.yaml") -> dict:
    for p in [Path(path), Path(__file__).parent / path]:
        if p.exists():
            return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    raise FileNotFoundError(f"config.yaml tidak ditemukan di: {Path(path).resolve()}")


def _is_demo(cfg: dict) -> bool:
    k1 = cfg.get("the_odds_api", {}).get("api_key", "")
    k2 = cfg.get("api_football", {}).get("api_key", "")
    return (k1 in ("", "YOUR_ODDS_API_KEY_HERE") and
            k2 in ("", "YOUR_API_FOOTBALL_KEY_HERE"))


# ─────────────────────────────────────────────────────────────────────────────
# Job: Poll Odds (Gen 3 — lazy import)
# ─────────────────────────────────────────────────────────────────────────────

def job_poll_odds(cfg: dict, leagues: list[str]) -> None:
    try:
        from data.odds_tracker import track_odds, get_movement_summary
    except (ImportError, ModuleNotFoundError):
        logger.debug("odds_tracker tidak tersedia — skip odds poll")
        return

    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    logger.info(f"[{now}] ODDS POLL — {len(leagues)} leagues")

    for league in leagues:
        try:
            snaps, movements = track_odds(league, cfg)
        except Exception as exc:
            logger.warning(f"  [{league}] odds poll error: {exc}")
            continue

        sharp = [m for m in movements if m.movement_type == "SHARP"]
        if sharp:
            console.print(f"\n  [bold yellow]⚡ LINE MOVEMENT ALERT [{league.upper()}][/]")
            for mv in sharp:
                direction = "↓" if mv.delta < 0 else "↑"
                console.print(
                    f"  [bold white]{mv.home} vs {mv.away}[/]  "
                    f"[dim]{mv.field}[/]  "
                    f"[cyan]{mv.from_odds:+.0f} → {mv.to_odds:+.0f}[/] "
                    f"{direction}  "
                    f"[bold {'green' if 'BUY' in mv.signal else 'red'}]{mv.signal}[/]"
                )

        drifts = [m for m in movements if m.movement_type == "DRIFT"]
        if drifts:
            logger.info(f"  [{league}] {len(drifts)} drift movements")


# ─────────────────────────────────────────────────────────────────────────────
# Job: Full Analysis
# ─────────────────────────────────────────────────────────────────────────────

def job_full_analysis(cfg: dict, leagues: list[str], status: dict) -> None:
    """
   
    """
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    logger.info(f"[{now}] FULL ANALYSIS — {len(leagues)} leagues")

    # Lazy import Gen 3 tools
    _elo_available  = status.get("elo_model", False)
    _h2h_available  = status.get("h2h_fetcher", False)
    _log_available  = status.get("prediction_log", False)
    _odds_available = status.get("odds_tracker", False)

    if _elo_available:
        from analytics.elo_model import (
            calculate_elo_matchup, blend_with_elo,
            seed_elo_from_stats, get_store,
        )
    if _h2h_available:
        from data.h2h_fetcher import get_h2h, apply_h2h_adjustment
    if _log_available:
        from storage.prediction_log import save_prediction, make_match_id, PredictionEntry
    if _odds_available:
        from data.odds_tracker import track_odds, get_movement_summary

    for league_key in leagues:
        lcfg  = cfg["leagues"].get(league_key, {})
        sport = lcfg.get("sport", "soccer")
        name  = lcfg.get("name", league_key.upper())
        flag  = lcfg.get("flag", "")

        # ── Data fetch ───────────────────────────────────────────────────────
        stats    = get_team_stats(league_key, cfg)
        injuries = get_injuries(league_key, cfg)
        fixtures = get_fixtures(league_key, cfg)

        if not stats:
            logger.warning(f"  [{league_key}] tidak ada data stats")
            continue

        profiles = build_profiles(league_key, stats, injuries, cfg)
        logger.info(f"  [{league_key}] {len(profiles)} profil, {len(fixtures)} fixtures")

        # ── ELO Bootstrap (hanya jika tersedia) ──────────────────────────────
        if _elo_available:
            store    = get_store()
            existing = store.all_for_league(league_key)
            if not existing or all(r.matches_played == 0 for r in existing):
                seed_elo_from_stats(league_key, stats, sport)

        # ── Odds movement (hanya jika tersedia) ──────────────────────────────
        movement_map = {}
        if _odds_available:
            try:
                _, movements = track_odds(league_key, cfg)
                movement_map = get_movement_summary(movements)
            except Exception as exc:
                logger.debug(f"  [{league_key}] movement error: {exc}")

        # ── Analisis per pertandingan ─────────────────────────────────────────
        for fix in fixtures:
            home_n = fix["home"]
            away_n = fix["away"]
            date   = fix.get("date", "")

            home_p = profiles.get(home_n)
            away_p = profiles.get(away_n)
            if not home_p or not away_p:
                continue

            # Probabilitas Gen 2
            odds = get_odds(home_n, away_n, league_key, cfg)
            prob = calculate_probability(home_p, away_p, cfg, odds)

            p_h = prob.p_home_win
            p_d = prob.p_draw
            p_a = prob.p_away_win

            # ELO blend (Gen 3)
            elo_matchup = None
            if _elo_available:
                try:
                    elo_matchup = calculate_elo_matchup(home_n, away_n, league_key, sport)
                    p_h, p_d, p_a = blend_with_elo(p_h, p_d, p_a, elo_matchup, elo_weight=0.20)
                except Exception as exc:
                    logger.debug(f"  ELO blend error: {exc}")

            # H2H blend (Gen 3)
            if _h2h_available:
                try:
                    h2h = get_h2h(home_n, away_n, cfg)
                    p_h, p_d, p_a = apply_h2h_adjustment(p_h, p_d, p_a, h2h)
                except Exception as exc:
                    logger.debug(f"  H2H blend error: {exc}")

            # Update prob dengan nilai final
            prob.p_home_win = p_h
            prob.p_draw     = p_d
            prob.p_away_win = p_a

            # Bet recommendation
            rec = recommend_bet(prob, home_p, away_p, odds, cfg)

            # Line movement direction
            mv_key = (home_n, away_n)
            mv_dir = movement_map.get(mv_key, {}).get("net_direction", "NEUTRAL")

            # Confluence alert
            if rec.bet_type != "PASS" and _odds_available:
                sharp_count = len(movement_map.get(mv_key, {}).get("sharp", []))
                if sharp_count > 0:
                    if mv_dir == "LEAN_HOME" and p_h > 0.55:
                        logger.info(f"  🔥 CONFLUENCE: Model + Sharp → {home_n} [{league_key}]")
                    elif mv_dir == "LEAN_AWAY" and p_a > 0.55:
                        logger.info(f"  🔥 CONFLUENCE: Model + Sharp → {away_n} [{league_key}]")

            # Simpan prediksi (Gen 3)
            if _log_available:
                try:
                    match_id = make_match_id(league_key, home_n, away_n, date)
                    entry = PredictionEntry(
                        match_id=match_id,
                        created_at=datetime.now(timezone.utc).isoformat(),
                        league=league_key, sport=sport,
                        home=home_n, away=away_n, match_date=date,
                        p_home_model=round(prob.p_home_win, 4),
                        p_draw_model=round(prob.p_draw, 4),
                        p_away_model=round(prob.p_away_win, 4),
                        p_home_final=p_h, p_draw_final=p_d, p_away_final=p_a,
                        elo_home=elo_matchup.home_rating if elo_matchup else None,
                        elo_away=elo_matchup.away_rating if elo_matchup else None,
                        elo_confidence=elo_matchup.confidence if elo_matchup else "N/A",
                        expected_home=prob.expected_home,
                        expected_away=prob.expected_away,
                        bet_type=rec.bet_type,
                        selection=rec.selection,
                        confidence=rec.confidence,
                        edge=rec.edge,
                        ml_home_odds=odds.get("moneyline_home") if odds else None,
                        ml_away_odds=odds.get("moneyline_away") if odds else None,
                        ml_draw_odds=odds.get("moneyline_draw") if odds else None,
                        total_line=odds.get("total_line")       if odds else None,
                        line_movement=mv_dir,
                    )
                    save_prediction(entry)
                except Exception as exc:
                    logger.debug(f"  prediction save error: {exc}")

            # Print ke terminal (selalu, Gen 2 style)
            from ui.display import print_strength_card, print_probability, print_recommendation
            print_strength_card(home_p, "HOME")
            print_strength_card(away_p, "AWAY")
            print_probability(prob, home_n, away_n)
            print_recommendation(rec, home_n, away_n)
            console.print()

        console.print(f"  [bold green]✓[/] [{league_key.upper()}] selesai\n")


# ─────────────────────────────────────────────────────────────────────────────
# Job: Morning Report
# ─────────────────────────────────────────────────────────────────────────────

def job_morning_report(cfg: dict, status: dict) -> None:
    if not status.get("prediction_log"):
        logger.debug("prediction_log tidak tersedia — skip morning report")
        return

    from storage.prediction_log import load_predictions, get_performance_summary
    from datetime import date

    today_str = date.today().isoformat()
    print_section("☀️  LAPORAN PAGI — Bet Hari Ini")

    all_preds = load_predictions()
    today = [p for p in all_preds if p.match_date.startswith(today_str)]
    bets  = [p for p in today if p.bet_type != "PASS"]

    if not bets:
        console.print("  [dim]Tidak ada rekomendasi bet hari ini.[/]")
    else:
        console.print(f"  [bold]Total rekomendasi: {len(bets)}[/]\n")
        for b in bets:
            cc = {"HIGH": "bright_green", "MEDIUM": "yellow", "LOW": "dim"}.get(b.confidence, "white")
            console.print(
                f"  [cyan]{b.home} vs {b.away}[/]  "
                f"[bold white]{b.bet_type}[/]  [{cc}]{b.confidence}[/]  → {b.selection}"
            )
            if b.line_movement != "NEUTRAL":
                console.print(f"     [dim]Line movement: {b.line_movement}[/]")

    perf = get_performance_summary()
    if perf.get("total", 0) > 10:
        console.print(
            f"\n  [bold]Performa:[/] "
            f"Accuracy {perf['accuracy']:.1%}  |  "
            f"ROI {perf['roi']:+.2f}u/bet  |  "
            f"Total P&L {perf['total_pnl']:+.1f}u"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler
# ─────────────────────────────────────────────────────────────────────────────

def run_with_scheduler(cfg: dict, leagues: list[str], status: dict) -> None:
    if status.get("apscheduler"):
        _run_apscheduler(cfg, leagues, status)
    else:
        _run_simple_loop(cfg, leagues, status)


def _run_apscheduler(cfg: dict, leagues: list[str], status: dict) -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.interval   import IntervalTrigger
    from apscheduler.triggers.cron       import CronTrigger

    scheduler = BlockingScheduler(timezone="UTC")

    scheduler.add_job(
        job_poll_odds, IntervalTrigger(minutes=15),
        args=[cfg, leagues], id="poll_odds",
    )
    scheduler.add_job(
        job_full_analysis, IntervalTrigger(minutes=60),
        args=[cfg, leagues, status], id="full_analysis",
    )
    scheduler.add_job(
        job_morning_report, CronTrigger(hour=7, minute=0),
        args=[cfg, status], id="morning_report",
    )

    console.print("  [bold green]APScheduler aktif:[/]")
    console.print("  Odds poll    → setiap 15 menit")
    console.print("  Full analysis→ setiap 60 menit")
    console.print("  Morning report → 07:00 UTC")
    console.print("\n  [dim]Tekan Ctrl+C untuk berhenti.[/]\n")

    logger.info("Startup: menjalankan analisis pertama…")
    job_full_analysis(cfg, leagues, status)
    scheduler.start()


def _run_simple_loop(cfg: dict, leagues: list[str], status: dict) -> None:
    FULL_INTERVAL = 60 * 60
    ODDS_INTERVAL = 15 * 60

    console.print("  [bold yellow]Simple loop mode[/] (install apscheduler untuk scheduler penuh)")
    console.print("  [dim]Tekan Ctrl+C untuk berhenti.[/]\n")

    last_full = 0.0
    try:
        while True:
            now = time.time()
            if status.get("odds_tracker"):
                job_poll_odds(cfg, leagues)
            if now - last_full >= FULL_INTERVAL:
                job_full_analysis(cfg, leagues, status)
                last_full = now
            time.sleep(ODDS_INTERVAL)
    except KeyboardInterrupt:
        console.print("\n  [dim]Dihentikan.[/]\n")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Sports Prediction Engine — Real-Time")
    parser.add_argument("--config",    default="config.yaml")
    parser.add_argument("--league",    choices=LEAGUES)
    parser.add_argument("--once",      action="store_true", help="Jalankan sekali lalu selesai")
    parser.add_argument("--odds-only", action="store_true", help="Hanya poll odds")
    args = parser.parse_args()

    # ── Load config ──────────────────────────────────────────────────────────
    try:
        cfg = load_cfg(args.config)
    except FileNotFoundError as e:
        console.print(f"\n  [bold red]ERROR:[/] {e}\n")
        sys.exit(1)

    leagues = [args.league] if args.league else LEAGUES

    # ── Header + status ──────────────────────────────────────────────────────
    print_header()

    demo_tag = " [bold yellow](DEMO MODE)[/]" if _is_demo(cfg) else ""
    console.print(f"  [bold]Leagues:[/] {', '.join(l.upper() for l in leagues)}{demo_tag}")

    status = _check_gen3()
    _print_status(status)

    # ── Ensure storage/ adalah Python package ────────────────────────────────
    storage_init = Path("storage/__init__.py")
    if not storage_init.exists():
        storage_init.parent.mkdir(parents=True, exist_ok=True)
        storage_init.write_text("# storage package\n", encoding="utf-8")
        logger.info("storage/__init__.py dibuat otomatis")

    # ── Run ──────────────────────────────────────────────────────────────────
    if args.odds_only:
        job_poll_odds(cfg, leagues)
        return

    if args.once:
        job_full_analysis(cfg, leagues, status)
        console.print("\n  [bold green]✓ Selesai (--once mode)[/]\n")
        return

    run_with_scheduler(cfg, leagues, status)


if __name__ == "__main__":
    main()