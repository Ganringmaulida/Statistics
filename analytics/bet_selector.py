"""
analytics/bet_selector.py  [Gen 3]
═══════════════════════════════════════════════════════════════════════════
Bet Selector — mengkonversi probabilitas model menjadi rekomendasi taruhan.

Analoginya: seperti filter saringan emas. Bukan setiap prediksi layak
dijadikan taruhan — hanya yang punya EDGE positif setelah vig bookmaker
dikurangkan yang lolos ke tahap rekomendasi. Filter ini memastikan sistem
tidak overbet dan hanya menarget situasi di mana model punya keunggulan
nyata terhadap pasar.

Logic:
  1. Hitung implied prob dari American odds (dengan vig)
  2. Bandingkan dengan probabilitas model (tanpa vig)
  3. Edge = model_prob - implied_prob
  4. Jika edge ≥ min_edge_moneyline (default 5%), rekomendasikan bet
  5. Confidence: HIGH (edge ≥ 12%), MEDIUM (edge ≥ 7%), LOW (edge ≥ 5%)

Tipe bet yang dievaluasi:
  MONEYLINE (H/A)  — win/lose
  OVER/UNDER       — total gol/poin
  SPREAD           — handicap (basketball/hockey)
  PASS             — tidak ada rekomendasi
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from analytics.probability_engine import MatchProbability


@dataclass
class BetRecommendation:
    """Output akhir bet selector untuk satu pertandingan."""
    bet_type:   str            # MONEYLINE | SPREAD | OVER | UNDER | PASS
    selection:  str            # deskripsi pilihan ("Arsenal ML", "Over 2.5", dll)
    confidence: str            # HIGH | MEDIUM | LOW
    edge:       Optional[float] = None     # selisih prob model vs pasar

    # Detail odds yang dipakai
    odds_used:  Optional[float] = None
    model_prob: Optional[float] = None
    market_prob: Optional[float] = None

    # Kelly criterion stake suggestion (% bankroll, capped 5%)
    kelly_pct:  Optional[float] = None

    notes: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _american_to_prob(american: float) -> float:
    """American odds → implied probability (DENGAN vig, sebelum removal)."""
    if american > 0:
        return 100.0 / (american + 100.0)
    return abs(american) / (abs(american) + 100.0)


def _kelly(edge: float, odds_american: float, fraction: float = 0.25) -> float:
    """
    Kelly criterion (fractional: default 25% Kelly untuk konservatif).
    Returns % bankroll yang direkomendasikan untuk dipertaruhkan.
    Capped di 5% untuk manajemen risiko.
    """
    if odds_american > 0:
        b = odds_american / 100.0
    else:
        b = 100.0 / abs(odds_american)

    # Kelly formula: f = (b*p - q) / b
    p = edge + _american_to_prob(odds_american)  # approx model prob
    q = 1.0 - p
    if b <= 0:
        return 0.0
    k = (b * p - q) / b
    if k <= 0:
        return 0.0
    return round(min(k * fraction, 0.05), 4)  # cap 5%


def _conf_label(edge: float, cfg: dict) -> str:
    t_high = cfg.get("model", {}).get("edge_high_confidence",   0.12)
    t_med  = cfg.get("model", {}).get("edge_medium_confidence", 0.07)
    if edge >= t_high:
        return "HIGH"
    if edge >= t_med:
        return "MEDIUM"
    return "LOW"


# ─────────────────────────────────────────────────────────────────────────────
# Evaluators
# ─────────────────────────────────────────────────────────────────────────────

def _eval_moneyline(
    prob: MatchProbability,
    odds: dict,
    cfg: dict,
    min_edge: float,
) -> Optional[BetRecommendation]:
    """Evaluasi moneyline home dan away."""
    best_edge = 0.0
    best_rec  = None

    candidates = [
        (prob.p_home_win, odds.get("moneyline_home"), prob.home_team, "Home"),
        (prob.p_away_win, odds.get("moneyline_away"), prob.away_team, "Away"),
    ]

    for model_p, american, team_name, side in candidates:
        if american is None or model_p is None:
            continue
        imp_p = _american_to_prob(float(american))
        edge  = model_p - imp_p
        if edge >= min_edge and edge > best_edge:
            best_edge = edge
            best_rec  = BetRecommendation(
                bet_type    = "MONEYLINE",
                selection   = f"{team_name} ML ({side})",
                confidence  = _conf_label(edge, cfg),
                edge        = round(edge, 4),
                odds_used   = float(american),
                model_prob  = round(model_p, 4),
                market_prob = round(imp_p, 4),
                kelly_pct   = _kelly(edge, float(american)),
            )
    return best_rec


def _eval_totals(
    prob: MatchProbability,
    odds: dict,
    cfg: dict,
    min_edge: float,
) -> Optional[BetRecommendation]:
    """Evaluasi OVER/UNDER total skor."""
    line      = odds.get("total_line")
    over_odds = odds.get("over_odds")
    und_odds  = odds.get("under_odds")

    if not line or not over_odds or not und_odds:
        return None

    expected = prob.expected_home + prob.expected_away
    if expected <= 0:
        return None

    import math

    lam  = float(expected)
    line = float(line)

    def p_over_logspace(lam: float, line: float) -> float:
        """
        P(total > line) — dua metode tergantung ukuran lambda:

        Soccer  (lam ≤ 15) : Poisson CDF via log-space → tidak overflow
        NBA/NHL (lam > 15)  : Normal approximation (CLT valid untuk lam besar)
                              N(μ=lam, σ=√lam) — akurasi ±1% untuk lam > 20
        """
        k = int(line)

        if lam > 15:
            # Normal approximation: P(X > k) = P(Z > (k+0.5-lam)/√lam)
            sigma = math.sqrt(lam)
            z     = (k + 0.5 - lam) / sigma
            # Erfc approximation untuk P(Z > z)
            return max(0.0, min(1.0, 0.5 * math.erfc(z / math.sqrt(2))))

        # Log-space Poisson CDF — aman untuk lam ≤ 15
        log_lam = math.log(lam) if lam > 0 else 0.0
        log_exp = -lam
        cdf     = 0.0
        log_pmf = log_exp   # log P(X=0) = -lam + 0*log(lam) - log(0!) = -lam
        for i in range(k + 1):
            cdf += math.exp(log_pmf)
            if i < k:
                log_pmf += log_lam - math.log(i + 1)
        return max(0.0, 1.0 - cdf)

    p_over  = p_over_logspace(lam, line)
    p_under = 1.0 - p_over

    best_rec = None
    for model_p, american, label in [
        (p_over,  over_odds, f"Over {line}"),
        (p_under, und_odds,  f"Under {line}"),
    ]:
        imp_p = _american_to_prob(float(american))
        edge  = model_p - imp_p
        if edge >= min_edge:
            best_rec = BetRecommendation(
                bet_type    = "OVER" if "Over" in label else "UNDER",
                selection   = label,
                confidence  = _conf_label(edge, cfg),
                edge        = round(edge, 4),
                odds_used   = float(american),
                model_prob  = round(model_p, 4),
                market_prob = round(imp_p, 4),
                kelly_pct   = _kelly(edge, float(american)),
            )
            break

    return best_rec


def _eval_spread(
    prob: MatchProbability,
    odds: dict,
    cfg: dict,
    min_edge: float,
) -> Optional[BetRecommendation]:
    """Evaluasi spread/handicap (basketball & hockey)."""
    spread_home = odds.get("spread_home")
    spread_odds = odds.get("spread_home_odds")

    if spread_home is None or spread_odds is None:
        return None

    expected_diff = prob.expected_home - prob.expected_away
    # Sederhana: jika expected_diff > spread_home → team home cover spread
    cover_p = 0.55 if expected_diff > float(spread_home) else 0.45
    imp_p   = _american_to_prob(float(spread_odds))
    edge    = cover_p - imp_p

    if edge < min_edge:
        return None

    return BetRecommendation(
        bet_type    = "SPREAD",
        selection   = f"{prob.home_team} {spread_home:+.1f}",
        confidence  = _conf_label(edge, cfg),
        edge        = round(edge, 4),
        odds_used   = float(spread_odds),
        model_prob  = round(cover_p, 4),
        market_prob = round(imp_p, 4),
        kelly_pct   = _kelly(edge, float(spread_odds)),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main selector
# ─────────────────────────────────────────────────────────────────────────────

_PASS = BetRecommendation(bet_type="PASS", selection="PASS", confidence="LOW",
                          notes="No edge found vs market")


def select_bet(
    prob: MatchProbability,
    odds: Optional[dict],
    cfg: dict,
) -> BetRecommendation:
    """
    Evaluasi semua tipe bet dan pilih yang punya edge terbaik.

    Prioritas: MONEYLINE > TOTALS > SPREAD
    Kembalikan PASS jika tidak ada yang memenuhi threshold.
    """
    if not odds:
        return BetRecommendation(
            bet_type="PASS", selection="PASS", confidence="LOW",
            notes="No market odds available"
        )

    min_edge = float(cfg.get("model", {}).get("min_edge_moneyline", 0.05))

    candidates = [
        _eval_moneyline(prob, odds, cfg, min_edge),
        _eval_totals(   prob, odds, cfg, min_edge),
        _eval_spread(   prob, odds, cfg, min_edge),
    ]

    # Pilih edge tertinggi di antara semua kandidat valid
    valid = [c for c in candidates if c is not None]
    if not valid:
        return _PASS

    return max(valid, key=lambda c: c.edge or 0.0)