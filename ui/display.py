"""
ui/display.py — Rich CLI rendering untuk Sports Predictor
"""
from __future__ import annotations

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Header & Menu
# ─────────────────────────────────────────────────────────────────────────────

def print_header() -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    console.print(Panel(
        Text("⚽🏀🏒  SPORTS PREDICTION ENGINE\n"
             "Strength · Probability · Bet Recommendation\n"
             f"[dim]{now}[/]", justify="center", style="bold white"),
        style="bold blue", padding=(1, 4),
    ))

def print_section(title: str) -> None:
    console.print(f"\n[bold cyan]{'━' * 64}[/]")
    console.print(f"[bold white]  {title}[/]")
    console.print(f"[bold cyan]{'━' * 64}[/]\n")

def print_main_menu(is_demo: bool = False) -> None:
    tag = " [dim yellow](DEMO MODE — tanpa API key)[/]" if is_demo else ""
    t = Text()
    items = [
        ("1", "🏴󠁧󠁢󠁥󠁮󠁧󠁿 EPL    — Analisis + Probabilitas + Rekomendasi"),
        ("2", "🏆 UCL    — Analisis + Probabilitas + Rekomendasi"),
        ("3", "🏀 NBA    — Analisis + Probabilitas + Rekomendasi"),
        ("4", "🏒 NHL    — Analisis + Probabilitas + Rekomendasi"),
        ("5", "📅 Semua Jadwal Pekan Ini"),
        ("6", "🔍 Analisis Satu Pertandingan Spesifik"),
        ("0", "Keluar"),
    ]
    for k, lbl in items:
        t.append(f"  [{k}]", style="bold cyan")
        t.append(f"  {lbl}\n", style="white")
    console.print(Panel(t, title=f"[bold white]MENU UTAMA{tag}[/]",
                        border_style="blue", padding=(1, 2)))

def prompt(msg: str = "Pilih") -> str:
    return console.input(f"\n[bold cyan]{msg}:[/] ").strip()

def loading(msg: str) -> None:
    console.print(f"  [dim cyan]⟳  {msg}…[/]")

def warn(msg: str) -> None:
    console.print(f"  [bold red]✗  {msg}[/]")

def ok(msg: str) -> None:
    console.print(f"  [bold green]✓  {msg}[/]")


# ─────────────────────────────────────────────────────────────────────────────
# Team Strength Card
# ─────────────────────────────────────────────────────────────────────────────

def print_strength_card(profile, title_suffix: str = "") -> None:
    from analytics.strength_profiler import TeamProfile
    p: TeamProfile = profile

    # Rating bars
    atk_bar = _bar(p.attack_rating)
    def_bar = _bar(p.defense_rating)
    frm_bar = _bar(p.form_score)
    fat_bar = _bar(p.fatigue_index)
    pwr_bar = _bar(p.power_score)

    body = Text()
    body.append(f"  Power Score  : ", style="bold")
    body.append(f"{p.power_score:.3f}  ", style="bold yellow")
    body.append(f"[{pwr_bar}]\n", style="yellow")

    body.append(f"  Attack       : ", style="bold")
    body.append(f"{p.attack_rating:.3f}  ", style="bright_green")
    body.append(f"[{atk_bar}]\n", style="green")

    body.append(f"  Defense      : ", style="bold")
    body.append(f"{p.defense_rating:.3f}  ", style="bright_cyan")
    body.append(f"[{def_bar}]\n", style="cyan")

    body.append(f"  Form         : ", style="bold")
    body.append(f"{p.form_score:.3f}  ", style="magenta")
    body.append(f"[{frm_bar}]\n", style="magenta")

    body.append(f"  Fatigue      : ", style="bold")
    fat_col = "bright_green" if p.fatigue_index > 0.9 else ("yellow" if p.fatigue_index > 0.75 else "bright_red")
    body.append(f"{p.fatigue_index:.3f}  ", style=fat_col)
    body.append(f"[{fat_bar}]\n\n", style=fat_col)

    # Raw stats
    if p.sport == "soccer":
        body.append(f"  xG/90 : {p.xg_per90:.2f}   xGA/90 : {p.xga_per90:.2f}   "
                    f"Win% : {p.win_pct:.1%}\n", style="dim")
    elif p.sport == "basketball":
        body.append(f"  Pts/G : {p.pts_for_avg:.1f}   Allow/G : {p.pts_against_avg:.1f}   "
                    f"Win% : {p.win_pct:.1%}\n", style="dim")
    elif p.sport == "hockey":
        body.append(f"  GF/G : {p.gf_per_game:.2f}   GA/G : {p.ga_per_game:.2f}   "
                    f"Win% : {p.win_pct:.1%}\n", style="dim")

    # Strengths
    if p.strengths:
        body.append("\n  ✅ KEKUATAN\n", style="bold bright_green")
        for s in p.strengths:
            body.append(f"    • {s}\n", style="green")

    # Weaknesses
    if p.weaknesses:
        body.append("\n  ❌ KELEMAHAN\n", style="bold bright_red")
        for w in p.weaknesses:
            body.append(f"    • {w}\n", style="red")

    # Injuries
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

    # Win probabilities
    body.append("  MODEL PROBABILITY\n\n", style="bold white")
    body.append(f"  {home_name:<24}", style="bold")
    body.append(f"{_pct(p.p_home_win):>7}  ", style="bold bright_green")
    body.append(f"[{_bar(p.p_home_win)}]\n")

    if p.sport == "soccer":
        body.append(f"  {'Draw':<24}", style="bold")
        body.append(f"{_pct(p.p_draw):>7}  ", style="bold yellow")
        body.append(f"[{_bar(p.p_draw)}]\n")

    body.append(f"  {away_name:<24}", style="bold")
    body.append(f"{_pct(p.p_away_win):>7}  ", style="bold bright_red")
    body.append(f"[{_bar(p.p_away_win)}]\n")

    # Expected score
    unit = "Goals" if p.sport == "soccer" else ("Pts" if p.sport == "basketball" else "Goals")
    body.append(f"\n  Expected {unit}: ", style="dim")
    body.append(f"{p.expected_home:.2f} — {p.expected_away:.2f}", style="white")
    body.append(f"   (Total: {p.expected_home + p.expected_away:.2f})\n", style="dim")

    # Market comparison
    if p.market_p_home is not None:
        body.append("\n  MARKET IMPLIED (vig-removed)\n\n", style="bold white")
        body.append(f"  {home_name:<24}", style="bold")
        body.append(f"{_pct(p.market_p_home):>7}\n")
        body.append(f"  {away_name:<24}", style="bold")
        body.append(f"{_pct(p.market_p_away):>7}\n")

        body.append("\n  EDGE vs MARKET\n\n", style="bold white")
        e_h = p.edge_moneyline_home
        e_a = p.edge_moneyline_away
        if e_h is not None:
            col_h = _edge_color(e_h)
            body.append(f"  {home_name:<24}", style="bold")
            body.append(f"{e_h:+.1%}\n", style=col_h)
        if e_a is not None:
            col_a = _edge_color(e_a)
            body.append(f"  {away_name:<24}", style="bold")
            body.append(f"{e_a:+.1%}\n", style=col_a)

    console.print(Panel(
        body,
        title=f"[bold white]PROBABILITY  {home_name} vs {away_name}[/]",
        border_style="cyan",
        padding=(0, 2),
    ))


# ─────────────────────────────────────────────────────────────────────────────
# Bet Recommendation Display
# ─────────────────────────────────────────────────────────────────────────────

def print_recommendation(rec, home_name: str, away_name: str) -> None:
    from analytics.bet_selector import BetRecommendation
    r: BetRecommendation = rec

    bet_s  = _bet_style(r.bet_type)
    conf_s = _conf_style(r.confidence)

    body = Text()
    body.append("  REKOMENDASI BET\n\n", style="bold white")
    body.append(f"  Tipe    : ", style="bold")
    body.append(f"{r.bet_type}\n", style=bet_s)
    body.append(f"  Pilihan : ", style="bold")
    body.append(f"{r.selection}\n", style="bold white")
    body.append(f"  Confidence : ", style="bold")
    body.append(f"{r.confidence}\n", style=conf_s)

    if r.edge is not None:
        body.append(f"  Edge vs Market : ", style="bold")
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
    t = Table(title=f"[bold]{league_name} — Jadwal[/]",
              box=box.SIMPLE_HEAD, header_style="bold cyan",
              border_style="dim", padding=(0, 1))
    t.add_column("Tanggal",  width=17)
    t.add_column("Home",     width=24, justify="right", style="bold white")
    t.add_column("",         width=4,  justify="center", style="dim")
    t.add_column("Away",     width=24, style="bold white")
    t.add_column("Venue",    width=24, style="dim")
    for f in fixtures:
        t.add_row(f.get("date",""), f.get("home",""), "vs", f.get("away",""), f.get("venue","-"))
    console.print(t)


# ─────────────────────────────────────────────────────────────────────────────
# Summary table for all matches in a league
# ─────────────────────────────────────────────────────────────────────────────

def print_match_summary_table(rows: list[dict], league_name: str) -> None:
    """
    rows: list of {home, away, bet_type, selection, confidence, edge, p_home, p_away}
    """
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

    for r in rows:
        bet_s  = _bet_style(r.get("bet_type", ""))
        conf_s = _conf_style(r.get("confidence", "LOW"))
        edge   = r.get("edge")
        edge_s = f"{edge:+.1%}" if edge is not None else "-"
        edge_c = _edge_color(edge) if edge is not None else "dim"

        t.add_row(
            r.get("home", ""), r.get("away", ""),
            _pct(r.get("p_home", 0)), _pct(r.get("p_away", 0)),
            Text(r.get("bet_type", ""), style=bet_s),
            r.get("selection", ""),
            Text(r.get("confidence", ""), style=conf_s),
            Text(edge_s, style=edge_c),
        )
    console.print(t)