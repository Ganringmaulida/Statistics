"""
analytics/ensemble.py  [Gen 3]
═══════════════════════════════════════════════════════════════════════════
Ensemble — gabungkan semua sinyal prediksi menjadi probabilitas final.

Analoginya: seperti tiga analis independen diminta pendapat sebelum
keputusan investasi:
  1. Model utama (Poisson/Pythagorean) → statistik musim berjalan
  2. ELO rating                        → rekam jejak historis lintas musim
  3. H2H history                       → pola psikologis head-to-head

Bobot default (konfigurasikan di config.yaml → ensemble:):
  model : 65%
  elo   : 20%
  h2h   : 15%

Bobot menyesuaikan DINAMIS:
  - ELO confidence LOW  → bobot ELO dipotong 50%, sisanya ke model
  - ELO tidak ada       → seluruh bobot ELO dialihkan ke model
  - H2H < 4 pertandingan → bobot H2H dialihkan ke model
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class EnsembleResult:
    """Hasil penggabungan semua sinyal beserta metadata transparansi."""
    p_home:         float
    p_draw:         float
    p_away:         float

    # Bobot aktual yang dipakai setelah penyesuaian dinamis
    w_model:        float
    w_elo:          float
    w_h2h:          float

    elo_confidence: str = "N/A"
    h2h_matches:    int = 0
    mode:           str = "model_only"  # "model_only" | "model+elo" | "full"


def blend(
    p_model_home: float,
    p_model_draw: float,
    p_model_away: float,
    elo_matchup=None,   # analytics.elo_model.EloMatchup | None
    h2h=None,           # data.h2h_fetcher.H2HRecord | None
    cfg: Optional[dict] = None,
) -> EnsembleResult:
    """
    Gabungkan probabilitas model, ELO, dan H2H dengan bobot dinamis.
    Output selalu valid (jumlah probabilitas = 1.0).
    """
    cfg     = cfg or {}
    ens_cfg = cfg.get("ensemble", {})

    w_model = float(ens_cfg.get("model_weight", 0.65))
    w_elo   = float(ens_cfg.get("elo_weight",   0.20))
    w_h2h   = float(ens_cfg.get("h2h_weight",   0.15))
    mode    = "model_only"

    # ── ELO weight adjustment ────────────────────────────────────────────────
    elo_conf  = "N/A"
    h2h_n     = 0

    if elo_matchup is None:
        w_model += w_elo
        w_elo    = 0.0
    else:
        elo_conf = getattr(elo_matchup, "confidence", "LOW")
        if elo_conf == "LOW":
            shift    = w_elo * 0.5
            w_model += shift
            w_elo   -= shift
        mode = "model+elo"

    # ── H2H weight adjustment ────────────────────────────────────────────────
    h2h_n = getattr(h2h, "matches_analyzed", 0) if h2h else 0
    if not h2h or h2h_n < 4:
        w_model += w_h2h
        w_h2h    = 0.0
    else:
        mode = "full"

    # ── Normalize weights ────────────────────────────────────────────────────
    total_w  = w_model + w_elo + w_h2h or 1.0
    w_model /= total_w
    w_elo   /= total_w
    w_h2h   /= total_w

    # ── Weighted blend ───────────────────────────────────────────────────────
    ph = p_model_home * w_model
    pd = p_model_draw * w_model
    pa = p_model_away * w_model

    if elo_matchup and w_elo > 0:
        ph += getattr(elo_matchup, "p_home_elo", 0.0) * w_elo
        pd += getattr(elo_matchup, "p_draw_elo", 0.0) * w_elo
        pa += getattr(elo_matchup, "p_away_elo", 0.0) * w_elo

    if h2h and w_h2h > 0:
        h_total = h2h.home_win_pct + h2h.draw_pct + h2h.away_win_pct
        if h_total > 0:
            ph += (h2h.home_win_pct / h_total) * w_h2h
            pd += (h2h.draw_pct     / h_total) * w_h2h
            pa += (h2h.away_win_pct / h_total) * w_h2h

    # ── Re-normalize output ──────────────────────────────────────────────────
    total = ph + pd + pa or 1.0
    return EnsembleResult(
        p_home         = round(ph / total, 4),
        p_draw         = round(pd / total, 4),
        p_away         = round(pa / total, 4),
        w_model        = round(w_model, 3),
        w_elo          = round(w_elo,   3),
        w_h2h          = round(w_h2h,   3),
        elo_confidence = elo_conf,
        h2h_matches    = h2h_n,
        mode           = mode,
    )


def apply_to_prob(prob, elo_matchup=None, h2h=None, cfg=None) -> EnsembleResult:
    """
    Terapkan ensemble langsung ke objek MatchProbability (mutate in-place).
    Kembalikan EnsembleResult untuk logging/transparansi.
    """
    result          = blend(prob.p_home_win, prob.p_draw, prob.p_away_win,
                            elo_matchup=elo_matchup, h2h=h2h, cfg=cfg)
    prob.p_home_win = result.p_home
    prob.p_draw     = result.p_draw
    prob.p_away_win = result.p_away
    return result