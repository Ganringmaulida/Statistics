"""
diagnose_and_fix.py  [Gen 3]
─────────────────────────────────────────────────────────────────────────────
Tool diagnostik: cek kesehatan sistem sebelum menjalankan app.py.

Analoginya: seperti pilot yang melakukan pre-flight checklist sebelum
terbang. Lebih baik menemukan masalah di darat daripada di udara.

Cek yang dilakukan:
  1. Import semua modul utama
  2. Load config.yaml
  3. Validasi API keys (apakah sudah diisi atau masih placeholder)
  4. Test koneksi ke setiap API source
  5. Cek direktori storage
  6. Test fetch demo data

Usage: python diagnose_and_fix.py
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import sys
from pathlib import Path
from rich.console import Console
from rich.rule    import Rule

console = Console()

OK   = "[bold green]✓[/]"
WARN = "[bold yellow]⚠[/]"
FAIL = "[bold red]✗[/]"


def _verify_module(module_path: str, required_attrs: list[str]) -> str:
    """Import modul dan verifikasi bahwa semua fungsi yang diperlukan ada."""
    import importlib
    mod = importlib.import_module(module_path)
    missing = [a for a in required_attrs if not hasattr(mod, a)]
    if missing:
        raise AttributeError(f"Missing: {', '.join(missing)}")
    return f"OK ({len(required_attrs)} functions verified)"


def check(label: str, fn):
    try:
        result = fn()
        status = OK if result is not False else WARN
        extra  = f"  [dim]{result}[/]" if isinstance(result, str) else ""
        console.print(f"  {status}  {label}{extra}")
        return True
    except Exception as exc:
        console.print(f"  {FAIL}  {label}  [red]{exc}[/]")
        return False


def run_diagnostics():
    console.print(Rule("[bold cyan]Sports Prediction Engine — Diagnostics[/]"))
    console.print()
    passed = failed = warned = 0

    # ── 1. Imports ───────────────────────────────────────────────────────────
    console.print("[bold white]1. Module Imports[/]")
    modules = [
        ("yaml",          lambda: __import__("yaml")),
        ("requests",      lambda: __import__("requests")),
        ("rich",          lambda: __import__("rich")),
        ("analytics.probability_engine", lambda: __import__("analytics.probability_engine")),
        ("analytics.strength_profiler",  lambda: __import__("analytics.strength_profiler")),
        ("analytics.elo_model",          lambda: __import__("analytics.elo_model")),
        ("analytics.ensemble",           lambda: __import__("analytics.ensemble")),
        ("analytics.calibrator",         lambda: __import__("analytics.calibrator")),
        ("analytics.bet_selector",       lambda: __import__("analytics.bet_selector")),
        ("analytics.backtester",         lambda: __import__("analytics.backtester")),
        ("analytics.dixon_coles",        lambda: __import__("analytics.dixon_coles")),
        ("data.fetcher",       lambda: __import__("data.fetcher")),
        ("data.h2h_fetcher",   lambda: __import__("data.h2h_fetcher")),
        ("data.odds_tracker",  lambda: __import__("data.odds_tracker")),
        ("data.demo_data",     lambda: __import__("data.demo_data")),
        ("storage.prediction_log", lambda: _verify_module("storage.prediction_log",
            ["save_prediction", "make_match_id", "PredictionEntry", "load_predictions"])),
        ("ui.display",         lambda: __import__("ui.display")),
        ("ui.backtest_report", lambda: __import__("ui.backtest_report")),
    ]
    for name, fn in modules:
        if check(name, fn): passed += 1
        else: failed += 1

    # ── 2. Config ────────────────────────────────────────────────────────────
    console.print(f"\n[bold white]2. Config[/]")
    cfg = None
    try:
        import yaml
        with open("config.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        console.print(f"  {OK}  config.yaml loaded")
        passed += 1
    except Exception as exc:
        console.print(f"  {FAIL}  config.yaml  [red]{exc}[/]")
        failed += 1
        console.print("\n[bold red]STOP: config.yaml tidak bisa dibaca. Diagnostik dihentikan.[/]")
        return

    # ── 3. API Keys ──────────────────────────────────────────────────────────
    console.print(f"\n[bold white]3. API Keys[/]")
    def key_check(path1, path2):
        key = cfg.get(path1, {}).get(path2, "")
        if isinstance(key, str) and key and "YOUR" not in key and len(key) > 10:
            return f"✓ configured ({key[:6]}...)"
        return False

    key_checks = [
        ("the_odds_api",  "api_key",  "The-Odds-API"),
        ("api_football",  "api_key",  "API-Football"),
        ("balldontlie",   "api_key",  "BallDontLie"),
    ]
    for k1, k2, label in key_checks:
        result = key_check(k1, k2)
        if result:
            console.print(f"  {OK}  {label}: {result}")
            passed += 1
        else:
            console.print(f"  {WARN}  {label}: [yellow]not configured — will use free/demo sources[/]")
            warned += 1

    # ── 4. Connectivity ──────────────────────────────────────────────────────
    console.print(f"\n[bold white]4. Connectivity (free sources)[/]")
    import requests as rq

    def ping(label, url):
        try:
            r = rq.get(url, timeout=8,
                       headers={"User-Agent": "Mozilla/5.0 predictor-diagnostics"})
            return f"HTTP {r.status_code}"
        except Exception as exc:
            raise Exception(str(exc)[:60])

    connectivity_tests = [
        ("Understat (EPL xG)",    "https://understat.com/league/EPL/2024"),
        ("ESPN Soccer standings", "https://site.api.espn.com/apis/v2/sports/soccer/eng.1/standings"),
        ("NHL Official API",      "https://api-web.nhle.com/v1/standings/now"),
        ("ESPN NBA scoreboard",   "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"),
    ]
    for label, url in connectivity_tests:
        if check(label, lambda u=url, l=label: ping(l, u)):
            passed += 1
        else:
            failed += 1

    # ── 5. Storage ───────────────────────────────────────────────────────────
    console.print(f"\n[bold white]5. Storage Directories[/]")
    for d in ["cache", "storage", "storage/odds_snapshots"]:
        p = Path(d)
        if p.exists():
            console.print(f"  {OK}  {d}/")
            passed += 1
        else:
            p.mkdir(parents=True, exist_ok=True)
            console.print(f"  {OK}  {d}/  [dim](created)[/]")
            passed += 1

    # ── 6. Demo data ─────────────────────────────────────────────────────────
    console.print(f"\n[bold white]6. Demo Data Sanity[/]")
    try:
        from data.demo_data import DEMO_TEAM_STATS, DEMO_FIXTURES
        for lk in ["epl", "ucl", "nba", "nhl"]:
            n_s = len(DEMO_TEAM_STATS.get(lk, []))
            n_f = len(DEMO_FIXTURES.get(lk, []))
            console.print(f"  {OK}  {lk.upper()}: {n_s} teams, {n_f} fixtures")
            passed += 1
    except Exception as exc:
        console.print(f"  {FAIL}  demo_data  [red]{exc}[/]")
        failed += 1

    # ── 7. ELO seed ──────────────────────────────────────────────────────────
    console.print(f"\n[bold white]7. ELO Ratings[/]")
    try:
        from analytics.elo_model import load_ratings
        ratings = load_ratings()
        total_teams = sum(len(v) for v in ratings.values())
        console.print(f"  {OK}  {total_teams} teams seeded across {len(ratings)} leagues")
        passed += 1
    except Exception as exc:
        console.print(f"  {FAIL}  ELO ratings  [red]{exc}[/]")
        failed += 1

    # ── Summary ──────────────────────────────────────────────────────────────
    console.print()
    console.print(Rule())
    total = passed + failed + warned
    console.print(
        f"  [bold]Result:[/] "
        f"[green]{passed} passed[/]  "
        f"[yellow]{warned} warnings[/]  "
        f"[red]{failed} failed[/]  "
        f"(total: {total})"
    )
    if failed == 0:
        console.print(f"\n  [bold green]✓ Sistem siap. Jalankan: python app.py[/]")
    elif failed <= 3:
        console.print(f"\n  [bold yellow]⚠ Ada {failed} masalah minor. Sistem mungkin tetap bisa berjalan.[/]")
    else:
        console.print(f"\n  [bold red]✗ Ada {failed} masalah. Periksa error di atas sebelum menjalankan sistem.[/]")
    console.print()


if __name__ == "__main__":
    run_diagnostics()