"""
ui/backtest_report.py  [Gen 3]
─────────────────────────────────────────────────────────────────────────────
Rich CLI rendering untuk Backtest Report dan Prediction Log.

Dipanggil dari app.py (menu 7) dan run_realtime.py (--backtest flag).
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from rich import box
from rich.console import Console
from rich.panel   import Panel
from rich.table   import Table
from rich.text    import Text

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Backtest summary (dari analytics.backtester.BacktestReport)
# ─────────────────────────────────────────────────────────────────────────────

def print_backtest_report(report) -> None:
    """Tampilkan BacktestReport dalam format Rich yang terstruktur."""
    body = Text()

    # Header stats
    body.append(f"  Total Predictions : {report.total_predictions}\n", style="white")
    body.append(f"  Completed         : {report.completed}\n", style="white")

    if report.completed == 0:
        body.append("\n  [dim]Belum ada pertandingan selesai untuk dievaluasi.[/dim]\n")
        console.print(Panel(body, title="[bold white]📈 BACKTEST REPORT[/]",
                            border_style="cyan", padding=(0, 2)))
        return

    # Accuracy
    acc_col = "bright_green" if report.hit_rate_direction >= 0.55 else \
              "yellow" if report.hit_rate_direction >= 0.45 else "red"
    body.append(f"\n  Direction Accuracy : ", style="bold")
    body.append(f"{report.hit_rate_direction:.1%}\n", style=f"bold {acc_col}")

    # Brier + Log Loss
    brier_col = "bright_green" if report.brier_score < 0.20 else \
                "yellow" if report.brier_score < 0.25 else "red"
    body.append(f"  Brier Score       : ", style="bold")
    body.append(f"{report.brier_score:.5f}  ", style=brier_col)
    body.append("(lower = better, 0 = perfect)\n", style="dim")

    body.append(f"  Log Loss          : ", style="bold")
    body.append(f"{report.log_loss:.5f}\n", style="white")

    # ROI
    if report.bets_placed:
        roi_col = "bright_green" if report.roi_pct > 0 else "bright_red"
        body.append(f"\n  Bets Placed  : {report.bets_placed}\n", style="bold white")
        body.append(f"  Bets Won     : {report.bets_won}\n", style="white")
        body.append(f"  Total Wagered: ${report.total_wagered:,.0f}\n", style="dim")
        body.append(f"  ROI          : ", style="bold")
        body.append(f"{report.roi_pct:+.2f}%\n", style=f"bold {roi_col}")

    console.print(Panel(body, title="[bold white]📈 BACKTEST REPORT[/]",
                        border_style="cyan", padding=(0, 2)))

    # Calibration table
    if report.calibration:
        t = Table(title="Calibration Bins", box=box.SIMPLE_HEAD,
                  header_style="bold cyan", border_style="dim")
        t.add_column("Bin",        width=12)
        t.add_column("Model Avg",  width=10, justify="center")
        t.add_column("Actual %",   width=10, justify="center")
        t.add_column("N",          width=6,  justify="center")
        t.add_column("Gap",        width=8,  justify="center")

        for label, b in sorted(report.calibration.items()):
            pred   = b.get("predicted_avg", 0)
            actual = b.get("actual_rate",   0)
            n      = b.get("n", 0)
            gap    = actual - pred
            gap_col = "green" if abs(gap) < 0.05 else "yellow" if abs(gap) < 0.10 else "red"
            t.add_row(label, f"{pred:.0%}", f"{actual:.0%}", str(n),
                      Text(f"{gap:+.0%}", style=gap_col))
        console.print(t)

    # Per sport
    if report.per_sport:
        t = Table(title="Per Sport", box=box.SIMPLE_HEAD,
                  header_style="bold cyan", border_style="dim")
        t.add_column("Sport",    width=12)
        t.add_column("N",        width=6,  justify="center")
        t.add_column("Hit Rate", width=10, justify="center")
        for sport, d in report.per_sport.items():
            hr = d.get("hit_rate", 0)
            hr_col = "green" if hr >= 0.55 else "yellow" if hr >= 0.45 else "red"
            t.add_row(sport, str(d.get("n", 0)), Text(f"{hr:.1%}", style=hr_col))
        console.print(t)

    # Per bet type
    if report.per_bet_type:
        t = Table(title="Per Bet Type", box=box.SIMPLE_HEAD,
                  header_style="bold cyan", border_style="dim")
        t.add_column("Type",     width=12)
        t.add_column("N",        width=6,  justify="center")
        t.add_column("Win Rate", width=10, justify="center")
        t.add_column("Net P&L",  width=10, justify="right")
        for bt, d in report.per_bet_type.items():
            wr    = d.get("win_rate", 0)
            pnl   = d.get("net_pnl",  0)
            wr_col  = "green" if wr >= 0.53 else "yellow" if wr >= 0.48 else "red"
            pnl_col = "green" if pnl > 0 else "red"
            t.add_row(bt, str(d.get("n", 0)),
                      Text(f"{wr:.1%}", style=wr_col),
                      Text(f"${pnl:+,.0f}", style=pnl_col))
        console.print(t)


# ─────────────────────────────────────────────────────────────────────────────
# Prediction log report (dari storage.prediction_log)
# ─────────────────────────────────────────────────────────────────────────────

def print_prediction_log(entries, limit: int = 20) -> None:
    """Tampilkan tabel prediction log terbaru."""
    if not entries:
        console.print("  [dim]Belum ada prediksi tersimpan.[/]")
        return

    # Sort by created_at descending
    entries = sorted(entries, key=lambda e: e.created_at, reverse=True)[:limit]

    t = Table(
        title=f"[bold]Prediction Log (last {limit})[/]",
        box=box.ROUNDED, header_style="bold cyan",
        border_style="blue", padding=(0, 1),
    )
    t.add_column("Match",       width=30)
    t.add_column("Bet",         width=11, justify="center")
    t.add_column("Conf",        width=7,  justify="center")
    t.add_column("P(H)",        width=6,  justify="center")
    t.add_column("P(A)",        width=6,  justify="center")
    t.add_column("Result",      width=8,  justify="center")
    t.add_column("P&L",         width=8,  justify="right")

    _bet_style = {"MONEYLINE": "cyan", "SPREAD": "blue",
                  "OVER": "bright_green", "UNDER": "bright_red", "PASS": "dim"}
    _conf_style = {"HIGH": "bright_green", "MEDIUM": "yellow", "LOW": "dim"}

    for e in entries:
        match_label = f"{e.home[:12]} v {e.away[:12]}"
        result_label, result_col = "", "dim"
        if e.actual_result:
            result_label = e.actual_result
            result_col   = "bright_green" if e.bet_won else "bright_red" \
                           if e.bet_won is False else "yellow"
        pnl_label = f"${e.pnl:+.0f}" if e.pnl is not None else "-"
        pnl_col   = "green" if (e.pnl or 0) > 0 else "red" if (e.pnl or 0) < 0 else "dim"

        t.add_row(
            match_label,
            Text(e.bet_type, style=_bet_style.get(e.bet_type, "white")),
            Text(e.confidence, style=_conf_style.get(e.confidence, "white")),
            f"{e.p_home_final:.0%}", f"{e.p_away_final:.0%}",
            Text(result_label, style=result_col),
            Text(pnl_label, style=pnl_col),
        )
    console.print(t)


def print_pending_results(pending) -> None:
    """Tampilkan prediksi yang menunggu hasil aktual."""
    if not pending:
        console.print("  [dim]Tidak ada prediksi yang menunggu hasil.[/]")
        return

    console.print(f"\n  [bold yellow]⏳ {len(pending)} prediksi menunggu hasil aktual[/]\n")
    for e in pending[:10]:
        console.print(
            f"  [cyan]{e.match_id}[/]  "
            f"[dim]→ update via:[/]  "
            f"bt.update_result(\"{e.match_id}\", home_score, away_score)"
        )
    if len(pending) > 10:
        console.print(f"  [dim]... dan {len(pending) - 10} lainnya[/]")