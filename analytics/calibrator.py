"""
analytics/calibrator.py  [Gen 3]
═══════════════════════════════════════════════════════════════════════════
Platt Scaling — kalibrasi probabilitas model agar lebih akurat.

Analoginya: seperti mengkalibrasi timbangan sebelum digunakan.
Timbangan yang menunjukkan 1.0 kg belum tentu tepat 1.0 kg —
perlu kalibrasi dengan benda berbobot diketahui.

Masalah yang diselesaikan:
  Model Poisson bisa overconfident (prediksi 80% padahal win rate aktual 65%)
  atau underconfident. Platt scaling mempelajari koreksi dari data historis
  menggunakan regresi logistik sederhana.

  Input  : p_raw (probabilitas dari model)
  Output : p_cal (probabilitas setelah kalibrasi)
  Formula: p_cal = 1 / (1 + exp(-(A * p_raw + B)))

Dipanggil oleh run_realtime.py setelah cukup prediksi terkumpul (≥30).
Sebelum itu, calibrator mengembalikan probabilitas tanpa perubahan.
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CAL_PATH  = Path("storage/calibration_params.json")
_MIN_SAMPLE = 30   # minimum records sebelum kalibrasi aktif


@dataclass
class CalibrationParams:
    """Parameter Platt scaling untuk satu sport."""
    sport:      str
    A:          float = 1.0   # slope
    B:          float = 0.0   # intercept
    n_samples:  int   = 0
    last_fit:   str   = ""
    active:     bool  = False  # False = pass-through (belum cukup data)


# ─────────────────────────────────────────────────────────────────────────────
# Storage
# ─────────────────────────────────────────────────────────────────────────────

def _load_params() -> dict[str, CalibrationParams]:
    if not _CAL_PATH.exists():
        return {}
    try:
        raw = json.loads(_CAL_PATH.read_text(encoding="utf-8"))
        return {k: CalibrationParams(**v) for k, v in raw.items()}
    except Exception as exc:
        logger.warning(f"calibrator load error: {exc}")
        return {}


def _save_params(params: dict[str, CalibrationParams]) -> None:
    _CAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CAL_PATH.write_text(
        json.dumps({k: asdict(v) for k, v in params.items()}, indent=2),
        encoding="utf-8",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Calibration
# ─────────────────────────────────────────────────────────────────────────────

def _sigmoid(x: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def _platt_fit(p_raw: list[float], y: list[int], n_iter: int = 100) -> tuple[float, float]:
    """
    Fit parameter A dan B via gradient descent sederhana.
    p_raw : list probabilitas dari model (0–1)
    y     : list label aktual (1 = event terjadi, 0 = tidak)
    """
    A, B = 1.0, 0.0
    lr   = 0.01

    for _ in range(n_iter):
        dA = dB = 0.0
        for p, yi in zip(p_raw, y):
            p_cal = _sigmoid(A * p + B)
            err   = p_cal - yi
            dA   += err * p
            dB   += err
        A -= lr * dA / len(p_raw)
        B -= lr * dB / len(p_raw)

    return round(A, 6), round(B, 6)


def fit_calibration(sport: str, predictions_with_results) -> CalibrationParams:
    """
    Fit kalibrasi dari predictions_with_results.
    Dipanggil secara berkala (misal: setiap 30 prediksi baru terkumpul).

    predictions_with_results : list PredictionEntry dengan actual_result != None
    """
    from datetime import datetime, timezone

    completed = [p for p in predictions_with_results
                 if p.sport == sport and p.actual_result is not None]

    params_map = _load_params()

    if len(completed) < _MIN_SAMPLE:
        logger.info(f"calibrator [{sport}]: {len(completed)} samples < {_MIN_SAMPLE} min — pass-through")
        params_map[sport] = CalibrationParams(sport=sport, n_samples=len(completed), active=False)
        _save_params(params_map)
        return params_map[sport]

    # Gunakan p_home_final sebagai sinyal kalibrasi (home win probability)
    p_raw = [e.p_home_final for e in completed]
    y     = [1 if e.actual_result == "HOME" else 0 for e in completed]

    A, B  = _platt_fit(p_raw, y)
    now   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    cp = CalibrationParams(sport=sport, A=A, B=B, n_samples=len(completed),
                           last_fit=now, active=True)
    params_map[sport] = cp
    _save_params(params_map)
    logger.info(f"calibrator [{sport}]: fitted A={A:.4f} B={B:.4f} n={len(completed)}")
    return cp


def calibrate(p: float, sport: str) -> float:
    """
    Kalibrasi satu probabilitas.
    Jika kalibrasi belum aktif (data kurang), kembalikan p tanpa perubahan.
    """
    params_map = _load_params()
    cp         = params_map.get(sport)
    if not cp or not cp.active:
        return p
    return round(_sigmoid(cp.A * p + cp.B), 4)


def calibrate_triplet(
    p_home: float, p_draw: float, p_away: float, sport: str
) -> tuple[float, float, float]:
    """
    Kalibrasi tiga probabilitas dan renormalisasi sehingga jumlahnya = 1.
    """
    ph = calibrate(p_home, sport)
    pd = calibrate(p_draw, sport)
    pa = calibrate(p_away, sport)
    total = ph + pd + pa or 1.0
    return round(ph/total, 4), round(pd/total, 4), round(pa/total, 4)