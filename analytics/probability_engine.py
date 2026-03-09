"""
analytics/probability_engine.py
─────────────────────────────────────────────────────────────────────────────
Layer 3: Kalkulasi probabilitas hasil pertandingan.

Soccer  → Bivariate Poisson Distribution
          Seperti dua mesin pencetak gol yang independen.
          Dari rata-rata xG masing-masing tim, kita hitung distribusi
          kemungkinan skor (0-0, 1-0, 1-1, dst.) lalu akumulasi:
          P(home win) = sum semua skor di mana home > away

NBA/NHL → Pythagorean Expectation
          Diperkenalkan oleh Bill James untuk baseball, diadaptasi
          untuk setiap olahraga dengan eksponent berbeda.
          Win% = pts_for^exp / (pts_for^exp + pts_against^exp)
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from analytics.strength_profiler import TeamProfile


@dataclass
class MatchProbability:
    """Hasil kalkulasi probabilitas untuk satu pertandingan."""
    home_team:      str
    away_team:      str
    sport:          str

    # Probabilitas hasil (sum ~ 1.0)
    p_home_win:     float
    p_draw:         float        # None untuk NBA/NHL
    p_away_win:     float

    # Expected score / total
    expected_home:  float        # Expected goals/points home
    expected_away:  float

    # Implied win% dari odds pasar (untuk perbandingan)
    market_p_home:  Optional[float] = None
    market_p_away:  Optional[float] = None

    # Edge vs pasar
    edge_moneyline_home: Optional[float] = None   # model - market (positif = value)
    edge_moneyline_away: Optional[float] = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _poisson_pmf(k: int, lam: float) -> float:
    """P(X = k) untuk distribusi Poisson dengan mean=lam."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _american_to_prob(american: float) -> float:
    """Konversi American odds ke implied probability (tanpa vig removal)."""
    if american > 0:
        return 100 / (american + 100)
    return abs(american) / (abs(american) + 100)


def _remove_vig_two_way(p1: float, p2: float) -> tuple[float, float]:
    """Buang vig dari dua implied probability."""
    total = p1 + p2
    if total <= 0:
        return 0.5, 0.5
    return p1 / total, p2 / total


def _remove_vig_three_way(
    p_home: float, p_draw: float, p_away: float
) -> tuple[float, float, float]:
    total = p_home + p_draw + p_away
    if total <= 0:
        return 1/3, 1/3, 1/3
    return p_home / total, p_draw / total, p_away / total


# ─────────────────────────────────────────────────────────────────────────────
# Soccer — Bivariate Poisson
# ─────────────────────────────────────────────────────────────────────────────

def _expected_goals(
    home: TeamProfile,
    away: TeamProfile,
    home_adv: float,
    league_avg_xg: float = 1.35,
) -> tuple[float, float]:
    """
    Hitung expected goals masing-masing tim.

    Formula:
      xG_home = league_avg × (home.attack / league_avg_attack)
                           × (away.defense_concede_rate)
                           × home_advantage_multiplier

    Karena kita sudah punya rating 0-1, kita sederhanakan:
      λ_home = league_avg × (0.5 + home.attack) × (1.2 - away.defense_rating)
               × (1 + home_adv) × home.fatigue
    """
    lam_home = (
        league_avg_xg
        * (0.5 + home.attack_rating)
        * (1.2 - away.defense_rating * 0.4)
        * (1.0 + home_adv)
        * home.fatigue_index
    )
    lam_away = (
        league_avg_xg
        * (0.5 + away.attack_rating)
        * (1.2 - home.defense_rating * 0.4)
        * away.fatigue_index
    )
    return max(0.3, lam_home), max(0.2, lam_away)


def calc_soccer_probability(
    home: TeamProfile,
    away: TeamProfile,
    cfg:  dict,
    odds: Optional[dict] = None,
) -> MatchProbability:
    """
    Hitung probabilitas H/D/A via Bivariate Poisson.
    Simulasi skor 0-0 sampai 8-8 (cukup untuk cover 99.9%+ kasus).
    """
    mp        = cfg.get("model", {})
    home_adv  = float(mp.get("home_advantage_goals", 0.35)) / 3.0

    lam_h, lam_a = _expected_goals(home, away, home_adv)

    MAX_GOALS = 9
    p_home_win = p_draw = p_away_win = 0.0

    for gh in range(MAX_GOALS):
        for ga in range(MAX_GOALS):
            p = _poisson_pmf(gh, lam_h) * _poisson_pmf(ga, lam_a)
            if gh > ga:
                p_home_win += p
            elif gh == ga:
                p_draw += p
            else:
                p_away_win += p

    # Normalisasi (minor floating point drift)
    total = p_home_win + p_draw + p_away_win
    p_home_win /= total
    p_draw     /= total
    p_away_win /= total

    # Market comparison
    market_ph = market_pa = edge_h = edge_a = None
    if odds:
        ml_h = odds.get("moneyline_home")
        ml_d = odds.get("moneyline_draw")
        ml_a = odds.get("moneyline_away")
        if ml_h and ml_a and ml_d:
            raw_h = _american_to_prob(ml_h)
            raw_d = _american_to_prob(ml_d)
            raw_a = _american_to_prob(ml_a)
            market_ph, _, market_pa = _remove_vig_three_way(raw_h, raw_d, raw_a)
            edge_h = round(p_home_win - market_ph, 4)
            edge_a = round(p_away_win - market_pa, 4)

    return MatchProbability(
        home_team=home.name, away_team=away.name, sport="soccer",
        p_home_win=round(p_home_win, 4),
        p_draw=round(p_draw, 4),
        p_away_win=round(p_away_win, 4),
        expected_home=round(lam_h, 2),
        expected_away=round(lam_a, 2),
        market_p_home=round(market_ph, 4) if market_ph else None,
        market_p_away=round(market_pa, 4) if market_pa else None,
        edge_moneyline_home=edge_h,
        edge_moneyline_away=edge_a,
    )


# ─────────────────────────────────────────────────────────────────────────────
# NBA — Pythagorean Expectation
# ─────────────────────────────────────────────────────────────────────────────

def calc_nba_probability(
    home: TeamProfile,
    away: TeamProfile,
    cfg:  dict,
    odds: Optional[dict] = None,
) -> MatchProbability:
    exp = float(cfg.get("model", {}).get("nba_pythagorean_exp", 13.91))
    mp  = float(cfg.get("model", {}).get("home_advantage_goals", 0.35))

    # Expected points per game dengan home advantage
    exp_h = home.pts_for_avg * (1 + mp * 0.02)
    exp_a = away.pts_for_avg

    # Pythagorean win% model untuk matchup ini
    # P(home win) berdasarkan relative offensive/defensive strength
    home_off = home.pts_for_avg ** exp
    home_def = home.pts_against_avg ** exp
    away_off = away.pts_for_avg ** exp
    away_def = away.pts_against_avg ** exp

    # Log5 formula (Bill James) untuk head-to-head win probability
    wp_home = home.win_pct * home.fatigue_index
    wp_away = away.win_pct * away.fatigue_index
    wp_home = max(0.01, min(0.99, wp_home))
    wp_away = max(0.01, min(0.99, wp_away))

    # Home court advantage: tambah ~3% untuk tim home
    p_home = (wp_home * (1 - wp_away)) / (
        wp_home * (1 - wp_away) + wp_away * (1 - wp_home)
    )
    p_home = _clamp_p(p_home + 0.03)
    p_away = 1.0 - p_home

    # Market
    market_ph = market_pa = edge_h = edge_a = None
    if odds:
        ml_h = odds.get("moneyline_home")
        ml_a = odds.get("moneyline_away")
        if ml_h and ml_a:
            raw_h = _american_to_prob(ml_h)
            raw_a = _american_to_prob(ml_a)
            market_ph, market_pa = _remove_vig_two_way(raw_h, raw_a)
            edge_h = round(p_home - market_ph, 4)
            edge_a = round(p_away - market_pa, 4)

    return MatchProbability(
        home_team=home.name, away_team=away.name, sport="basketball",
        p_home_win=round(p_home, 4), p_draw=0.0, p_away_win=round(p_away, 4),
        expected_home=round(exp_h, 1), expected_away=round(exp_a, 1),
        market_p_home=round(market_ph, 4) if market_ph else None,
        market_p_away=round(market_pa, 4) if market_pa else None,
        edge_moneyline_home=edge_h, edge_moneyline_away=edge_a,
    )


# ─────────────────────────────────────────────────────────────────────────────
# NHL — Pythagorean (exp=2.37)
# ─────────────────────────────────────────────────────────────────────────────

def calc_nhl_probability(
    home: TeamProfile,
    away: TeamProfile,
    cfg:  dict,
    odds: Optional[dict] = None,
) -> MatchProbability:
    exp = float(cfg.get("model", {}).get("nhl_pythagorean_exp", 2.37))

    gf_h = home.gf_per_game * home.fatigue_index * 1.05   # home ice +5%
    gf_a = away.gf_per_game * away.fatigue_index
    ga_h = home.ga_per_game
    ga_a = away.ga_per_game

    # Expected total goals
    exp_total_h = (gf_h + ga_a) / 2
    exp_total_a = (gf_a + ga_h) / 2

    # Win probability via Pythagorean
    py_home = home.gf_per_game ** exp / (
        home.gf_per_game ** exp + home.ga_per_game ** exp
    )
    py_away = away.gf_per_game ** exp / (
        away.gf_per_game ** exp + away.ga_per_game ** exp
    )
    py_home = max(0.01, min(0.99, py_home))
    py_away = max(0.01, min(0.99, py_away))

    p_home = (py_home * (1 - py_away)) / (
        py_home * (1 - py_away) + py_away * (1 - py_home)
    )
    p_home = _clamp_p(p_home + 0.025)
    p_away = 1.0 - p_home

    # Market
    market_ph = market_pa = edge_h = edge_a = None
    if odds:
        ml_h = odds.get("moneyline_home")
        ml_a = odds.get("moneyline_away")
        if ml_h and ml_a:
            raw_h = _american_to_prob(ml_h)
            raw_a = _american_to_prob(ml_a)
            market_ph, market_pa = _remove_vig_two_way(raw_h, raw_a)
            edge_h = round(p_home - market_ph, 4)
            edge_a = round(p_away - market_pa, 4)

    return MatchProbability(
        home_team=home.name, away_team=away.name, sport="hockey",
        p_home_win=round(p_home, 4), p_draw=0.0, p_away_win=round(p_away, 4),
        expected_home=round(exp_total_h, 2), expected_away=round(exp_total_a, 2),
        market_p_home=round(market_ph, 4) if market_ph else None,
        market_p_away=round(market_pa, 4) if market_pa else None,
        edge_moneyline_home=edge_h, edge_moneyline_away=edge_a,
    )


def _clamp_p(v: float) -> float:
    return max(0.01, min(0.99, v))


# ─────────────────────────────────────────────────────────────────────────────
# Dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def calculate_probability(
    home: TeamProfile,
    away: TeamProfile,
    cfg:  dict,
    odds: Optional[dict] = None,
) -> MatchProbability:
    sport = home.sport
    if sport == "soccer":
        return calc_soccer_probability(home, away, cfg, odds)
    elif sport == "basketball":
        return calc_nba_probability(home, away, cfg, odds)
    elif sport == "hockey":
        return calc_nhl_probability(home, away, cfg, odds)
    raise ValueError(f"Unknown sport: {sport}")