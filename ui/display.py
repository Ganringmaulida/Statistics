"""
ui/display.py — Rich CLI rendering  [G+1: data source badge + backtest menu]
"""
from __future__ import annotations

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


def _bar(value: float, width: int = 12) -> str:
    filled = max(0, min(width, int(value * width)))
    return "█" * filled + "░" * (width - filled)

def _pct(v: float) -> str:
    return f"{v:.1%}"

def _edge_color(edge: float) -> str:
    if edge >= 0.08: return "bold bright_green"
    if edge >= 0.04: return "green"
    if edge >= 0.01: return "yellow"
    return "dim"

def _conf_style(c: str) -> str:
    return {"HIGH": "bold bright_green", "MEDIUM": "yellow", "LOW": "dim white"}.get(c, "white")

def _bet_style(t: str) -> str:
    return {
        "MONEYLINE": "bold cyan",
        "SPREAD":    "bold blue",
        "OVER":      "bold bright_green",
        "UNDER":     "bold bright_red",
        "PASS":      "dim white",
    }.get(t, "white")

# [G+1] Source badge colors
_SOURCE_STYLE = {
    "understat":   "bold green",
    "nhle.com":    "bold green",
    "stats.nba.com": "bold green",
    "espn":        "green",
    "api-football":"yellow",
    "demo":        "bold yellow",
    "unknown":     "dim",
    "not_fetched": "dim",
}

def _source_label(src: str) -> str:
    icons = {
        "understat":     "🌐 Understat",
        "nhle.com":      "🌐 NHL API",
        "stats.nba.com": "🌐 NBA Stats",
        "espn":          "🌐 ESPN",
        "api-football":  "🔑 API-Football",
        "demo":          "⚠️  DEMO",
        "unknown":       "?  Unknown",
        "not_fetched":   "–  Not fetched",
    }
    return icons.get(src, src)


# ─────────────────────────────────────────────────────────────────────────────
# Header & Menu
# ─────────────────────────────────────────────────────────────────────────────

def print_header() -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    console.print(Panel(
        Text(
            "⚽🏀🏒  SPORTS PREDICTION ENGINE  [G+1]\n"
            "Strength · Probability · Bet Recommendation · Backtest\n"
            f"[dim]{now}[/]",
            justify="center",
            style="bold white",
        ),
        style="bold blue",
        padding=(1, 4),
    ))

def print_section(title: str) -> None:
    console.print(f"\n[bold cyan]{'━' * 64}[/]")
    console.print(f"[bold white]  {title}[/]")
    console.print(f"[bold cyan]{'━' * 64}[/]\n")

def print_main_menu(is_demo: bool = False) -> None:
    tag = " [dim yellow](odds: DEMO)[/]" if is_demo else ""
    t = Text()
    items = [
        ("1", "🏴󠁧󠁢󠁥󠁮󠁧󠁿 EPL    — Analisis + Probabilitas + Rekomendasi"),
        ("2", "🏆 UCL    — Analisis + Probabilitas + Rekomendasi"),
        ("3", "🏀 NBA    — Analisis + Probabilitas + Rekomendasi"),
        ("4", "🏒 NHL    — Analisis + Probabilitas + Rekomendasi"),
        ("5", "📅 Semua Jadwal Pekan Ini"),
        ("6", "🔍 Analisis Satu Pertandingan Spesifik"),
        ("7", "📈 Backtest Report"),     # [G+1]
        ("0", "Keluar"),
    ]
    for k, lbl in items:
        t.append(f"  [{k}]", style="bold cyan")
        t.append(f"  {lbl}\n", style="white")
    console.print(Panel(
        t,
        title=f"[bold white]MENU UTAMA{tag}[/]",
        border_style="blue",
        padding=(1, 2),
    ))

def prompt(msg: str = "Pilih") -> str:
    return console.input(f"\n[bold cyan]{msg}:[/] ").strip()

def loading(msg: str) -> None:
    console.print(f"  [dim cyan]⟳  {msg}…[/]")

def warn(msg: str) -> None:
    console.print(f"  [bold red]✗  {msg}[/]")

def ok(msg: str) -> None:
    console.print(f"  [bold green]✓  {msg}[/]")


# ─────────────────────────────────────────────────────────────────────────────
# [G+1] Data source badge
# ─────────────────────────────────────────────────────────────────────────────

def print_data_sources(sources: dict[str, str], league_key: str) -> None:
    """Tampilkan badge sumber data yang digunakan."""
    t = Text()
    t.append("  Data Sources:  ", style="bold white")
    for dtype, src in sources.items():
        style = _SOURCE_STYLE.get(src, "white")
        t.append(f"[{dtype.upper()}: ", style="dim")
        t.append(_source_label(src), style=style)
        t.append("]  ", style="dim")
    console.print(t)
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
# Team Strength Card
# ─────────────────────────────────────────────────────────────────────────────

def print_strength_card(profile, title_suffix: str = "") -> None:
    from analytics.strength_profiler import TeamProfile
    p: TeamProfile = profile

    body = Text()
    body.append(f"  Power Score  : ", style="bold")
    body.append(f"{p.power_score:.3f}  [{_bar(p.power_score)}]\n", style="yellow")
    body.append(f"  Attack       : ", style="bold")
    body.append(f"{p.attack_rating:.3f}  [{_bar(p.attack_rating)}]\n", style="bright_green")
    body.append(f"  Defense      : ", style="bold")
    body.append(f"{p.defense_rating:.3f}  [{_bar(p.defense_rating)}]\n", style="bright_cyan")
    body.append(f"  Form         : ", style="bold")
    body.append(f"{p.form_score:.3f}  [{_bar(p.form_score)}]\n", style="magenta")

    fat_col = "bright_green" if p.fatigue_index > 0.9 else ("yellow" if p.fatigue_index > 0.75 else "bright_red")
    body.append(f"  Fatigue      : ", style="bold")
    body.append(f"{p.fatigue_index:.3f}  [{_bar(p.fatigue_index)}]\n\n", style=fat_col)

    if p.sport == "soccer":
        body.append(f"  xG/90 : {p.xg_per90:.2f}   xGA/90 : {p.xga_per90:.2f}   Win% : {p.win_pct:.1%}\n", style="dim")
    elif p.sport == "basketball":
        body.append(f"  Pts/G : {p.pts_for_avg:.1f}   Allow/G : {p.pts_against_avg:.1f}   Win% : {p.win_pct:.1%}\n", style="dim")
    elif p.sport == "hockey":
        body.append(f"  GF/G : {p.gf_per_game:.2f}   GA/G : {p.ga_per_game:.2f}   Win% : {p.win_pct:.1%}\n", style="dim")

    if p.strengths:
        body.append("\n  ✅ KEKUATAN\n", style="bold bright_green")
        for s in p.strengths:
            body.append(f"    • {s}\n", style="green")
    if p.weaknesses:
        body.append("\n  ❌ KELEMAHAN\n", style="bold bright_red")
        for w in p.weaknesses:
            body.append(f"    • {w}\n", style="red")
    if p.key_injuries:
        body.append("\n  🚑 CEDERA PEMAIN KUNCI\n", style="bold red")
        for inj in p.key_injuries:
            body.append(f"    • {inj}\n", style="red")

    console.print(Panel(
        body,
        title=f"[bold white]{p.name}[/][dim]  {title_suffix}[/]",
        border_style="blue",
        padding=(0, 2),
    ))


# ─────────────────────────────────────────────────────────────────────────────
# Probability Display
# ─────────────────────────────────────────────────────────────────────────────

def print_probability(prob, home_name: str, away_name: str) -> None:
    from analytics.probability_engine import MatchProbability
    p: MatchProbability = prob

    body = Text()
    body.append("  MODEL PROBABILITY\n\n", style="bold white")
    body.append(f"  {home_name:<24}{_pct(p.p_home_win):>7}  [{_bar(p.p_home_win)}]\n", style="bold bright_green")

    if p.sport == "soccer":
        body.append(f"  {'Draw':<24}{_pct(p.p_draw):>7}  [{_bar(p.p_draw)}]\n", style="bold yellow")

    body.append(f"  {away_name:<24}{_pct(p.p_away_win):>7}  [{_bar(p.p_away_win)}]\n", style="bold bright_red")

    unit = "Goals" if p.sport == "soccer" else ("Pts" if p.sport == "basketball" else "Goals")
    body.append(f"\n  Expected {unit}: ", style="dim")
    body.append(f"{p.expected_home:.2f} — {p.expected_away:.2f}", style="white")
    body.append(f"   (Total: {p.expected_home + p.expected_away:.2f})\n", style="dim")

    # [G+1] Dixon-Coles badge
    if getattr(p, "dixon_coles_applied", False):
        body.append(f"  [DC] Dixon-Coles ρ={getattr(p, 'rho_used', 0):.2f} applied\n", style="dim cyan")

    if p.market_p_home is not None:
        body.append("\n  MARKET IMPLIED (vig-removed)\n\n", style="bold white")
        body.append(f"  {home_name:<24}{_pct(p.market_p_home):>7}\n")
        body.append(f"  {away_name:<24}{_pct(p.market_p_away):>7}\n")
        body.append("\n  EDGE vs MARKET\n\n", style="bold white")
        if p.edge_moneyline_home is not None:
            body.append(f"  {home_name:<24}", style="bold")
            body.append(f"{p.edge_moneyline_home:+.1%}\n", style=_edge_color(p.edge_moneyline_home))
        if p.edge_moneyline_away is not None:
            body.append(f"  {away_name:<24}", style="bold")
            body.append(f"{p.edge_moneyline_away:+.1%}\n", style=_edge_color(p.edge_moneyline_away))

    console.print(Panel(
        body,
        title=f"[bold white]PROBABILITY  {home_name} vs {away_name}[/]",
        border_style="cyan",
        padding=(0, 2),
    ))


# ─────────────────────────────────────────────────────────────────────────────
# Bet Recommendation
# ─────────────────────────────────────────────────────────────────────────────

def print_recommendation(rec, home_name: str, away_name: str) -> None:
    from analytics.bet_selector import BetRecommendation
    r: BetRecommendation = rec

    body = Text()
    body.append("  REKOMENDASI BET\n\n", style="bold white")
    body.append(f"  Tipe       : ", style="bold")
    body.append(f"{r.bet_type}\n", style=_bet_style(r.bet_type))
    body.append(f"  Pilihan    : ", style="bold")
    body.append(f"{r.selection}\n", style="bold white")
    body.append(f"  Confidence : ", style="bold")
    body.append(f"{r.confidence}\n", style=_conf_style(r.confidence))
    if r.edge is not None:
        body.append(f"  Edge       : ", style="bold")
        body.append(f"{r.edge:+.1%}\n", style=_edge_color(r.edge))

    body.append("\n  REASONING\n", style="bold white")
    for line in r.reasoning:
        body.append(f"  → {line}\n", style="dim white")

    if r.caution:
        body.append("\n  ⚠  PERHATIAN\n", style="bold yellow")
        for c in r.caution:
            body.append(f"  {c}\n", style="yellow")

    border = "bright_green" if r.bet_type != "PASS" else "dim"
    console.print(Panel(
        body,
        title=f"[bold white]BET RECOMMENDATION  {home_name} vs {away_name}[/]",
        border_style=border,
        padding=(0, 2),
    ))


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures Table
# ─────────────────────────────────────────────────────────────────────────────

def print_fixtures(fixtures: list[dict], league_name: str) -> None:
    if not fixtures:
        console.print(f"  [dim]Tidak ada jadwal {league_name} dalam waktu dekat.[/]")
        return
    t = Table(
        title=f"[bold]{league_name} — Jadwal[/]",
        box=box.SIMPLE_HEAD, header_style="bold cyan",
        border_style="dim", padding=(0, 1),
    )
    t.add_column("Tanggal", width=17)
    t.add_column("Home",    width=24, justify="right", style="bold white")
    t.add_column("",        width=4,  justify="center", style="dim")
    t.add_column("Away",    width=24, style="bold white")
    t.add_column("Venue",   width=24, style="dim")
    for f in fixtures:
        t.add_row(f.get("date",""), f.get("home",""), "vs", f.get("away",""), f.get("venue","-"))
    console.print(t)


# ─────────────────────────────────────────────────────────────────────────────
# Summary table
# ─────────────────────────────────────────────────────────────────────────────

def print_match_summary_table(rows: list[dict], league_name: str) -> None:
    if not rows:
        return
    t = Table(
        title=f"[bold]{league_name} — Ringkasan Rekomendasi[/]",
        box=box.ROUNDED, header_style="bold cyan",
        border_style="blue", padding=(0, 1),
    )
    t.add_column("Home",       width=22, style="bold white", justify="right")
    t.add_column("Away",       width=22, style="bold white")
    t.add_column("P(H)",       width=6,  justify="center")
    t.add_column("P(A)",       width=6,  justify="center")
    t.add_column("Bet",        width=11, justify="center")
    t.add_column("Pilihan",    width=28)
    t.add_column("Confidence", width=8,  justify="center")
    t.add_column("Edge",       width=7,  justify="right")
    t.add_column("DC",         width=3,  justify="center")  # [G+1]

    for r in rows:
        bet_s  = _bet_style(r.get("bet_type", ""))
        conf_s = _conf_style(r.get("confidence", "LOW"))
        edge   = r.get("edge")
        edge_s = f"{edge:+.1%}" if edge is not None else "-"
        edge_c = _edge_color(edge) if edge is not None else "dim"
        dc_s   = "✓" if r.get("dixon_coles") else " "

        t.add_row(
            r.get("home", ""), r.get("away", ""),
            _pct(r.get("p_home", 0)), _pct(r.get("p_away", 0)),
            Text(r.get("bet_type", ""), style=bet_s),
            r.get("selection", ""),
            Text(r.get("confidence", ""), style=conf_s),
            Text(edge_s, style=edge_c),
            Text(dc_s, style="dim cyan"),
        )
    console.print(t)