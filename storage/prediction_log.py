"""
storage/prediction_log.py  [Gen 3]
═══════════════════════════════════════════════════════════════════════════
Persistent prediction log — rekam semua prediksi + hasil aktual.

Analoginya: seperti buku jurnal trader profesional. Setiap prediksi
dicatat SEBELUM pertandingan, hasil diisi SETELAH selesai, sehingga
performa model bisa dievaluasi secara objektif dari waktu ke waktu.
Tanpa log ini, kita tidak tahu apakah model kita profitable atau
sekadar terlihat bagus di atas kertas.

Digunakan oleh run_realtime.py:
  save_prediction(entry)        → catat prediksi sebelum match
  make_match_id(...)            → buat ID unik per pertandingan
  load_predictions()            → muat semua record
  get_performance_summary()     → ringkasan akurasi + ROI
  update_result(match_id, ...)  → isi hasil aktual setelah match selesai
  pending_results()             → prediksi yang belum ada hasilnya
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_LOG_PATH = Path("storage/predictions_log.json")


# ─────────────────────────────────────────────────────────────────────────────
# Data structure
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PredictionEntry:
    """Satu record prediksi lengkap — model output + konteks + hasil aktual."""
    match_id:       str
    created_at:     str
    league:         str
    sport:          str
    home:           str
    away:           str
    match_date:     str

    # Probabilitas dari model utama (Poisson / Pythagorean)
    p_home_model:   float
    p_draw_model:   float
    p_away_model:   float

    # Probabilitas final setelah ensemble (ELO + H2H blend)
    p_home_final:   float
    p_draw_final:   float
    p_away_final:   float

    # ELO context
    elo_home:       Optional[float] = None
    elo_away:       Optional[float] = None
    elo_confidence: str             = "N/A"

    # Expected score
    expected_home:  float = 0.0
    expected_away:  float = 0.0

    # Bet recommendation
    bet_type:       str             = "PASS"
    selection:      str             = "PASS"
    confidence:     str             = "LOW"
    edge:           Optional[float] = None

    # Market odds (American format)
    ml_home_odds:   Optional[float] = None
    ml_away_odds:   Optional[float] = None
    ml_draw_odds:   Optional[float] = None
    total_line:     Optional[float] = None

    # Line movement signal dari odds_tracker
    line_movement:  str = "NEUTRAL"

    # Hasil aktual (diisi setelah pertandingan selesai via update_result())
    actual_home:    Optional[int]   = None
    actual_away:    Optional[int]   = None
    actual_result:  Optional[str]   = None   # "HOME" | "DRAW" | "AWAY"
    bet_won:        Optional[bool]  = None
    pnl:            Optional[float] = None   # profit/loss per 100 unit taruhan


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_raw() -> list[dict]:
    if not _LOG_PATH.exists():
        return []
    try:
        return json.loads(_LOG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"prediction_log load error: {exc}")
        return []


def _save_raw(entries: list[dict]) -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LOG_PATH.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _american_to_pnl(american: float, won: bool, stake: float = 100.0) -> float:
    """Hitung profit/loss dari American odds."""
    if won:
        return (american * stake / 100) if american > 0 else (stake * 100 / abs(american))
    return -stake


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def make_match_id(league: str, home: str, away: str, date: str) -> str:
    """
    Buat ID unik per pertandingan.
    Format: {league}_{home}_{away}_{date}
    """
    date_part = (date or "")[:10] or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    h = home.replace(" ", "_")[:15]
    a = away.replace(" ", "_")[:15]
    return f"{league}_{h}_{a}_{date_part}"


def save_prediction(entry: PredictionEntry) -> None:
    """
    Simpan prediksi sebelum pertandingan dimulai.
    Idempotent — skip jika match_id sudah ada (tidak overwrite).
    """
    raw = _load_raw()
    if any(r.get("match_id") == entry.match_id for r in raw):
        logger.debug(f"prediction_log: duplicate skip {entry.match_id}")
        return
    raw.append(asdict(entry))
    _save_raw(raw)
    logger.debug(f"prediction_log: saved {entry.match_id}")


def load_predictions() -> list[PredictionEntry]:
    """Muat semua prediksi dari file log."""
    raw    = _load_raw()
    result = []
    for r in raw:
        try:
            # Filter hanya field yang dikenal agar backward-compatible
            known = {f.name for f in PredictionEntry.__dataclass_fields__.values()}
            filtered = {k: v for k, v in r.items() if k in known}
            result.append(PredictionEntry(**filtered))
        except TypeError as exc:
            logger.debug(f"prediction_log: skip malformed entry: {exc}")
    return result


def update_result(match_id: str, home_score: int, away_score: int) -> bool:
    """
    Update hasil aktual setelah pertandingan selesai.
    Otomatis menghitung apakah bet menang dan berapa P&L-nya.

    Returns True jika record ditemukan dan berhasil diupdate.
    """
    raw = _load_raw()
    for r in raw:
        if r.get("match_id") != match_id:
            continue

        r["actual_home"]   = home_score
        r["actual_away"]   = away_score
        r["actual_result"] = (
            "HOME" if home_score > away_score else
            "AWAY" if home_score < away_score else "DRAW"
        )

        bt = r.get("bet_type", "PASS")
        if bt == "MONEYLINE":
            sel  = r.get("selection", "")
            home = r.get("home", "")
            side = "HOME" if home in sel else "AWAY"
            won  = (r["actual_result"] == side)
            odds = r.get("ml_home_odds") if side == "HOME" else r.get("ml_away_odds")
            r["bet_won"] = won
            r["pnl"]     = _american_to_pnl(float(odds), won) if odds else (100.0 if won else -100.0)

        elif bt in ("OVER", "UNDER"):
            total = home_score + away_score
            line  = r.get("total_line")
            if line:
                won = (total > line) if bt == "OVER" else (total < line)
                r["bet_won"] = won
                r["pnl"]     = 90.0 if won else -100.0  # implied -110 vig
            else:
                r["bet_won"] = None
                r["pnl"]     = 0.0

        elif bt == "SPREAD":
            # Spread evaluation membutuhkan skor aktual vs spread line
            # Disederhanakan: tandai sebagai perlu evaluasi manual
            r["bet_won"] = None
            r["pnl"]     = 0.0

        else:  # PASS
            r["bet_won"] = None
            r["pnl"]     = 0.0

        _save_raw(raw)
        logger.info(f"prediction_log: result updated {match_id} → {r['actual_result']}")
        return True

    logger.warning(f"prediction_log: match_id not found: {match_id}")
    return False


def get_performance_summary() -> dict:
    """
    Hitung ringkasan performa dari semua prediksi yang sudah ada hasil aktual.
    Digunakan oleh morning_report di run_realtime.py.

    Returns dict: total, correct, accuracy, bets, total_pnl, roi
    """
    entries   = load_predictions()
    completed = [e for e in entries if e.actual_result is not None]

    if not completed:
        return {
            "total": 0, "correct": 0, "accuracy": 0.0,
            "bets": 0, "total_pnl": 0.0, "roi": 0.0,
        }

    # Direction accuracy
    correct = sum(
        1 for e in completed
        if max(
            ("HOME", e.p_home_final),
            ("DRAW", e.p_draw_final),
            ("AWAY", e.p_away_final),
            key=lambda x: x[1],
        )[0] == e.actual_result
    )

    # ROI simulasi flat bet
    bet_entries = [e for e in completed if e.bet_type != "PASS" and e.pnl is not None]
    total_pnl   = sum(e.pnl for e in bet_entries) if bet_entries else 0.0
    roi         = total_pnl / (len(bet_entries) * 100) if bet_entries else 0.0

    return {
        "total":     len(completed),
        "correct":   correct,
        "accuracy":  round(correct / len(completed), 4),
        "bets":      len(bet_entries),
        "total_pnl": round(total_pnl, 2),
        "roi":       round(roi, 4),
    }


def pending_results() -> list[PredictionEntry]:
    """Return prediksi yang belum ada hasil aktualnya — untuk follow-up."""
    return [e for e in load_predictions() if e.actual_result is None]