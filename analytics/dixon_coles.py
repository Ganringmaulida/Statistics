"""
analytics/dixon_coles.py  [Gen 3]
═══════════════════════════════════════════════════════════════════════════
Dixon-Coles low-score correction — modul standalone.

Referensi: Dixon & Coles (1997) "Modelling Association Football Scores
and Inefficiencies in the Football Betting Market"

Koreksi ini hanya berlaku untuk soccer (Poisson). NBA/NHL tidak perlu
karena skor tidak pernah 0-0, 1-0, 0-1, atau 1-1 dalam konteks yang
sama dengan sepak bola.

rho (parameter korelasi) default = -0.13 (nilai empiris dari paper asli).
Dikonfigurasikan via config.yaml → model.dixon_coles_rho.
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations


def tau(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    """
    Faktor koreksi Dixon-Coles untuk skor rendah.
    Hanya berlaku untuk x,y ∈ {0,1}. Skor lain → 1.0 (tidak dikoreksi).

    Parameter:
        x   : gol home
        y   : gol away
        lam : expected gol home (lambda)
        mu  : expected gol away (mu)
        rho : parameter korelasi (biasanya negatif, default -0.13)
    """
    if x == 0 and y == 0:
        return 1.0 - lam * mu * rho
    elif x == 0 and y == 1:
        return 1.0 + lam * rho
    elif x == 1 and y == 0:
        return 1.0 + mu * rho
    elif x == 1 and y == 1:
        return 1.0 - rho
    return 1.0


def apply_correction(
    score_matrix: list[list[float]],
    lam: float,
    mu: float,
    rho: float = -0.13,
) -> list[list[float]]:
    """
    Terapkan koreksi DC ke matriks probabilitas skor.

    score_matrix[i][j] = P(home=i, away=j) dari Poisson murni.
    Fungsi ini mengkoreksi sel (0,0), (0,1), (1,0), (1,1) dan
    renormalisasi seluruh matriks agar jumlah = 1.
    """
    corrected = [row[:] for row in score_matrix]
    for i in range(min(2, len(corrected))):
        for j in range(min(2, len(corrected[i]))):
            corrected[i][j] *= tau(i, j, lam, mu, rho)

    # Renormalisasi
    total = sum(p for row in corrected for p in row)
    if total > 0:
        corrected = [[p / total for p in row] for row in corrected]
    return corrected