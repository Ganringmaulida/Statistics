"""
analytics/bet_selector.py
─────────────────────────────────────────────────────────────────────────────
Layer 4: Tentukan BET TYPE terbaik dan berikan rekomendasi final.

Logic keputusan (seperti pohon keputusan):

  1. Jika ada edge besar vs moneyline → MONEYLINE
     Alasan: probabilitas model jauh lebih tinggi dari yang diimplikasikan
             pasar, artinya pasar salah menilai tim ini.

  2. Jika model setuju siapa yang menang TAPI moneyline terlalu pendek
     (tim favorit terlalu murah untuk dibeli) → SPREAD
     Alasan: mengambil spread lebih baik daripada moneyline -250 yang
             memberikan return kecil untuk risk yang sama.

  3. Jika kedua tim sama-sama bagus atau sama-sama buruk secara ofensif
     → OVER/UNDER
     Alasan: ketidakpastian pemenang tinggi, tapi total gol/poin
             lebih mudah diprediksi dari kekuatan ofensif kolektif.

  4. Jika tidak ada bet yang menarik → PASS (tidak ada value)
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from analytics.probability_engine import MatchProbability
from analytics.strength_profiler  import TeamProfile


@dataclass
class BetRecommendation:
    """Rekomendasi bet final untuk satu pertandingan."""
    bet_type:       str               # "MONEYLINE" | "SPREAD" | "OVER" | "UNDER" | "PASS"
    selection:      str               # "Arsenal ML" / "Over 2.5" / "PASS"
    confidence:     str               # "HIGH" | "MEDIUM" | "LOW"
    edge:           Optional[float]   # Edge vs market (jika ada odds)
    reasoning:      list[str]         # Penjelasan langkah per langkah
    caution:        list[str]         # Risiko / hal yang perlu diperhatikan


def _american_to_return(american: float) -> float:
    """Berapa dollar return per $100 taruhan."""
    if american > 0:
        return american
    return 10_000 / abs(american)


def _edge_label(edge: Optional[float]) -> str:
    if edge is None:
        return ""
    if edge >= 0.10:
        return "edge sangat besar"
    if edge >= 0.06:
        return "edge signifikan"
    if edge >= 0.03:
        return "edge moderat"
    return "edge kecil"


def _confidence_from_edge(edge: Optional[float]) -> str:
    if edge is None:
        return "LOW"
    if edge >= 0.08:
        return "HIGH"
    if edge >= 0.04:
        return "MEDIUM"
    return "LOW"


# ─────────────────────────────────────────────────────────────────────────────
# Soccer bet selector
# ─────────────────────────────────────────────────────────────────────────────

def _select_soccer(
    prob:  MatchProbability,
    home:  TeamProfile,
    away:  TeamProfile,
    odds:  Optional[dict],
    cfg:   dict,
) -> BetRecommendation:
    mp        = cfg.get("model", {})
    min_edge  = float(mp.get("min_edge_moneyline", 0.05))
    min_ou    = float(mp.get("min_edge_ou", 0.04))

    reasoning: list[str] = []
    caution:   list[str] = []

    p_h  = prob.p_home_win
    p_d  = prob.p_draw
    p_a  = prob.p_away_win
    e_h  = prob.edge_moneyline_home
    e_a  = prob.edge_moneyline_away

    reasoning.append(
        f"Model probability: {home.name} {p_h:.1%} | Draw {p_d:.1%} | {away.name} {p_a:.1%}"
    )
    reasoning.append(
        f"Expected goals: {home.name} {prob.expected_home:.2f} — {away.name} {prob.expected_away:.2f}"
    )

    # Cedera
    if home.key_injuries:
        caution.append(f"⚠ {home.name} kehilangan pemain kunci: {', '.join(home.key_injuries)}")
    if away.key_injuries:
        caution.append(f"⚠ {away.name} kehilangan pemain kunci: {', '.join(away.key_injuries)}")

    # Tidak ada odds — hanya rekomendasi berdasarkan model
    if not odds:
        if p_h > 0.55:
            return BetRecommendation(
                "MONEYLINE", f"{home.name} Moneyline", "MEDIUM", None,
                reasoning + [f"{home.name} unggul probability ({p_h:.1%}) — tidak ada odds untuk konfirmasi edge"],
                caution + ["Tidak ada data odds pasar — verifikasi manual"]
            )
        if p_a > 0.55:
            return BetRecommendation(
                "MONEYLINE", f"{away.name} Moneyline", "MEDIUM", None,
                reasoning + [f"{away.name} unggul probability ({p_a:.1%}) — tidak ada odds"],
                caution + ["Tidak ada data odds pasar — verifikasi manual"]
            )
        # Pertandingan ketat — cek total
        exp_total = prob.expected_home + prob.expected_away
        if exp_total > 2.8:
            return BetRecommendation(
                "OVER", f"Over {exp_total:.1f}", "LOW", None,
                reasoning + [f"Expected total {exp_total:.2f} goals — kedua tim ofensif"],
                caution + ["Tanpa odds pasar, tidak bisa hitung edge"]
            )
        return BetRecommendation("PASS", "PASS — Tidak ada value jelas", "LOW", None, reasoning, caution)

    # Ada odds
    ml_h = odds.get("moneyline_home", 0)
    ml_a = odds.get("moneyline_away", 0)
    total_line = odds.get("total_line", 2.5)
    exp_total  = prob.expected_home + prob.expected_away

    # 1. Moneyline edge
    best_edge = None
    best_team = None
    if e_h and e_h >= min_edge:
        best_edge, best_team = e_h, ("HOME", home.name, ml_h)
    if e_a and e_a >= min_edge:
        if best_edge is None or e_a > best_edge:
            best_edge, best_team = e_a, ("AWAY", away.name, ml_a)

    if best_team:
        side, name, ml_odds = best_team
        reasoning.append(
            f"Market implied: {home.name} {prob.market_p_home:.1%} | {away.name} {prob.market_p_away:.1%}"
        )
        reasoning.append(
            f"Model vs Market edge: {best_edge:.1%} ({_edge_label(best_edge)})"
        )
        # Cek apakah moneyline terlalu pendek (return < $35 per $100)
        ret = _american_to_return(ml_odds)
        if ret < 40 and side == "HOME":
            # Moneyline murah — sarankan spread
            spread_h  = odds.get("spread_home")
            spread_odds = odds.get("spread_home_odds")
            if spread_h is not None:
                reasoning.append(
                    f"Moneyline {ml_odds} terlalu pendek (return ${ret:.0f}/$100) — "
                    f"spread lebih efisien"
                )
                return BetRecommendation(
                    "SPREAD", f"{name} {spread_h:+.1f} ({spread_odds:+d})",
                    _confidence_from_edge(best_edge), best_edge,
                    reasoning, caution
                )
        return BetRecommendation(
            "MONEYLINE", f"{name} Moneyline ({ml_odds:+d})",
            _confidence_from_edge(best_edge), best_edge,
            reasoning, caution
        )

    # 2. Over/Under
    ou_edge = abs(exp_total - total_line)
    if exp_total > total_line + 0.4:
        reasoning.append(
            f"Model expected total {exp_total:.2f} > line {total_line} "
            f"(+{exp_total - total_line:.2f} goals) — OVER"
        )
        return BetRecommendation(
            "OVER", f"Over {total_line} ({odds.get('over_odds', 0):+d})",
            "MEDIUM" if ou_edge > 0.6 else "LOW", None,
            reasoning, caution
        )
    if exp_total < total_line - 0.4:
        reasoning.append(
            f"Model expected total {exp_total:.2f} < line {total_line} "
            f"({total_line - exp_total:.2f} goals under) — UNDER"
        )
        return BetRecommendation(
            "UNDER", f"Under {total_line} ({odds.get('under_odds', 0):+d})",
            "MEDIUM" if ou_edge > 0.6 else "LOW", None,
            reasoning, caution
        )

    reasoning.append("Tidak ada bet type dengan edge yang cukup — PASS")
    return BetRecommendation("PASS", "PASS", "LOW", None, reasoning, caution)


# ─────────────────────────────────────────────────────────────────────────────
# NBA / NHL bet selector
# ─────────────────────────────────────────────────────────────────────────────

def _select_nba_nhl(
    prob:  MatchProbability,
    home:  TeamProfile,
    away:  TeamProfile,
    odds:  Optional[dict],
    cfg:   dict,
) -> BetRecommendation:
    mp       = cfg.get("model", {})
    min_edge = float(mp.get("min_edge_moneyline", 0.05))

    reasoning: list[str] = []
    caution:   list[str] = []

    p_h = prob.p_home_win
    p_a = prob.p_away_win
    e_h = prob.edge_moneyline_home
    e_a = prob.edge_moneyline_away

    sport_unit = "pts" if home.sport == "basketball" else "goals"

    reasoning.append(
        f"Model probability: {home.name} {p_h:.1%} | {away.name} {p_a:.1%}"
    )
    reasoning.append(
        f"Expected {sport_unit}: {home.name} {prob.expected_home:.1f} — "
        f"{away.name} {prob.expected_away:.1f}"
    )

    if home.key_injuries:
        caution.append(f"⚠ {home.name}: {', '.join(home.key_injuries)} cedera")
    if away.key_injuries:
        caution.append(f"⚠ {away.name}: {', '.join(away.key_injuries)} cedera")

    if not odds:
        winner = home.name if p_h > p_a else away.name
        p_win  = max(p_h, p_a)
        if p_win > 0.60:
            return BetRecommendation(
                "MONEYLINE", f"{winner} Moneyline", "LOW", None,
                reasoning + [f"{winner} unggul model ({p_win:.1%}) — tidak ada odds pasar"],
                caution + ["Verifikasi odds manual"]
            )
        return BetRecommendation("PASS", "PASS", "LOW", None, reasoning, caution)

    ml_h = odds.get("moneyline_home", 0)
    ml_a = odds.get("moneyline_away", 0)
    spread_h = odds.get("spread_home")
    spread_h_odds = odds.get("spread_home_odds")
    spread_a = odds.get("spread_away")
    spread_a_odds = odds.get("spread_away_odds")
    total_line = odds.get("total_line", 0)
    exp_total  = prob.expected_home + prob.expected_away

    if prob.market_p_home:
        reasoning.append(
            f"Market implied: {home.name} {prob.market_p_home:.1%} | "
            f"{away.name} {prob.market_p_away:.1%}"
        )

    # 1. Moneyline edge
    best_edge = None
    best_team_info = None
    if e_h and e_h >= min_edge:
        best_edge, best_team_info = e_h, ("HOME", home.name, ml_h, spread_h, spread_h_odds)
    if e_a and e_a >= min_edge:
        if best_edge is None or e_a > best_edge:
            best_edge, best_team_info = e_a, ("AWAY", away.name, ml_a, spread_a, spread_a_odds)

    if best_team_info:
        side, name, ml_odds, spr, spr_odds = best_team_info
        reasoning.append(f"Edge: {best_edge:.1%} ({_edge_label(best_edge)})")
        ret = _american_to_return(ml_odds)
        if ret < 35 and spr is not None:
            reasoning.append(
                f"Moneyline {ml_odds:+d} return rendah (${ret:.0f}/$100) — spread lebih efisien"
            )
            return BetRecommendation(
                "SPREAD", f"{name} {spr:+.1f} ({spr_odds:+d})",
                _confidence_from_edge(best_edge), best_edge, reasoning, caution
            )
        return BetRecommendation(
            "MONEYLINE", f"{name} Moneyline ({ml_odds:+d})",
            _confidence_from_edge(best_edge), best_edge, reasoning, caution
        )

    # 2. Over/Under
    if total_line > 0:
        diff = exp_total - total_line
        if diff > total_line * 0.02:
            reasoning.append(
                f"Expected total {exp_total:.1f} > line {total_line} (+{diff:.1f}) — OVER"
            )
            return BetRecommendation(
                "OVER", f"Over {total_line} ({odds.get('over_odds', 0):+d})",
                "MEDIUM" if diff > total_line * 0.03 else "LOW",
                None, reasoning, caution
            )
        if diff < -total_line * 0.02:
            reasoning.append(
                f"Expected total {exp_total:.1f} < line {total_line} ({diff:.1f}) — UNDER"
            )
            return BetRecommendation(
                "UNDER", f"Under {total_line} ({odds.get('under_odds', 0):+d})",
                "MEDIUM", None, reasoning, caution
            )

    reasoning.append("Tidak ada edge yang signifikan — PASS")
    return BetRecommendation("PASS", "PASS", "LOW", None, reasoning, caution)


# ─────────────────────────────────────────────────────────────────────────────
# Dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def recommend_bet(
    prob:  MatchProbability,
    home:  TeamProfile,
    away:  TeamProfile,
    odds:  Optional[dict],
    cfg:   dict,
) -> BetRecommendation:
    if home.sport == "soccer":
        return _select_soccer(prob, home, away, odds, cfg)
    return _select_nba_nhl(prob, home, away, odds, cfg)