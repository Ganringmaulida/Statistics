"""
data/odds_tracker.py  [Gen 3]
═══════════════════════════════════════════════════════════════════════════
Odds Tracker — rekam pergerakan odds dari waktu ke waktu.

Analoginya: seperti memperhatikan pergerakan saham sebelum membeli.
Jika odds moneyline Arsenal bergerak dari +150 ke +120 dalam 24 jam,
itu berarti uang besar masuk ke Arsenal — pasar "tahu sesuatu."
Pergerakan yang signifikan adalah sinyal kuat yang harus dipertimbangkan
bahkan jika model kita sendiri tidak menangkapnya.

Sinyal yang dihasilkan:
  SHARP_HOME  → uang tajam (smart money) masuk ke home team
  SHARP_AWAY  → uang tajam masuk ke away team
  STEAM_OVER  → gerakan cepat ke Over
  STEAM_UNDER → gerakan cepat ke Under
  NEUTRAL     → tidak ada pergerakan signifikan

Storage: storage/odds_snapshots/{league}_{home}_{away}_{date}.json
  Disimpan setiap kali odds difetch, dibandingkan dengan snapshot sebelumnya.
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SNAPSHOT_DIR = Path("storage/odds_snapshots")

# Threshold pergerakan odds (dalam implied probability points)
_SHARP_THRESHOLD = 0.03   # ≥3pp movement → sharp money signal
_STEAM_THRESHOLD = 0.04   # ≥4pp pada totals → steam move


@dataclass
class OddsSnapshot:
    """Satu snapshot odds pada waktu tertentu."""
    match_id:      str
    timestamp:     float
    moneyline_home: Optional[float]
    moneyline_away: Optional[float]
    moneyline_draw: Optional[float]
    total_line:    Optional[float]
    over_odds:     Optional[float]
    under_odds:    Optional[float]
    spread_home:   Optional[float]


@dataclass
class LineMovement:
    """Analisis pergerakan odds antara dua snapshot."""
    signal:       str     # SHARP_HOME | SHARP_AWAY | STEAM_OVER | STEAM_UNDER | NEUTRAL
    ml_home_move: float   # perubahan implied prob home (positif = odds turun / lebih difavoritkan)
    ml_away_move: float
    total_move:   float   # perubahan total line
    snapshots:    int     # jumlah snapshot tersimpan


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _american_to_prob(american: Optional[float]) -> float:
    if american is None:
        return 0.0
    if american > 0:
        return 100.0 / (american + 100.0)
    return abs(american) / (abs(american) + 100.0)


def _snap_path(match_id: str) -> Path:
    safe = match_id.replace(" ", "_").replace("/", "_")[:80]
    return _SNAPSHOT_DIR / f"{safe}.json"


def _load_snaps(match_id: str) -> list[dict]:
    p = _snap_path(match_id)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_snap(match_id: str, snaps: list[dict]) -> None:
    _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    _snap_path(match_id).write_text(
        json.dumps(snaps, ensure_ascii=False), encoding="utf-8"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def record_odds(match_id: str, odds: dict) -> None:
    """
    Simpan snapshot odds baru untuk match ini.
    Dipanggil setiap kali odds baru difetch (run_realtime.py).
    Hanya simpan jika ada perubahan signifikan vs snapshot terakhir.
    """
    snap = OddsSnapshot(
        match_id       = match_id,
        timestamp      = time.time(),
        moneyline_home = odds.get("moneyline_home"),
        moneyline_away = odds.get("moneyline_away"),
        moneyline_draw = odds.get("moneyline_draw"),
        total_line     = odds.get("total_line"),
        over_odds      = odds.get("over_odds"),
        under_odds     = odds.get("under_odds"),
        spread_home    = odds.get("spread_home"),
    )

    snaps = _load_snaps(match_id)

    # Jangan duplikasi jika odds tidak berubah
    if snaps:
        last = snaps[-1]
        if (last.get("moneyline_home") == snap.moneyline_home and
                last.get("moneyline_away") == snap.moneyline_away and
                last.get("total_line")     == snap.total_line):
            return

    snaps.append(asdict(snap))
    # Simpan maksimal 24 snapshot terakhir per match
    _save_snap(match_id, snaps[-24:])
    logger.debug(f"odds_tracker: snapshot #{len(snaps)} saved for {match_id}")


def analyze_movement(match_id: str) -> LineMovement:
    """
    Bandingkan snapshot terbaru vs snapshot pertama untuk match ini.
    Return LineMovement dengan sinyal pergerakan.
    """
    snaps = _load_snaps(match_id)

    if len(snaps) < 2:
        return LineMovement(signal="NEUTRAL", ml_home_move=0.0,
                            ml_away_move=0.0, total_move=0.0, snapshots=len(snaps))

    first = snaps[0]
    last  = snaps[-1]

    # Perubahan implied probability (positif = lebih difavoritkan)
    ml_home_move = (_american_to_prob(last.get("moneyline_home")) -
                    _american_to_prob(first.get("moneyline_home")))
    ml_away_move = (_american_to_prob(last.get("moneyline_away")) -
                    _american_to_prob(first.get("moneyline_away")))

    # Perubahan total line
    tl_first = first.get("total_line") or 0
    tl_last  = last.get("total_line")  or 0
    total_move = tl_last - tl_first

    # Tentukan sinyal
    signal = "NEUTRAL"
    if ml_home_move >= _SHARP_THRESHOLD:
        signal = "SHARP_HOME"
    elif ml_away_move >= _SHARP_THRESHOLD:
        signal = "SHARP_AWAY"
    elif total_move >= _STEAM_THRESHOLD:
        signal = "STEAM_OVER"
    elif total_move <= -_STEAM_THRESHOLD:
        signal = "STEAM_UNDER"

    return LineMovement(
        signal       = signal,
        ml_home_move = round(ml_home_move, 4),
        ml_away_move = round(ml_away_move, 4),
        total_move   = round(total_move,   2),
        snapshots    = len(snaps),
    )


def get_latest_odds(match_id: str) -> Optional[dict]:
    """Return snapshot odds terbaru untuk match ini."""
    snaps = _load_snaps(match_id)
    if not snaps:
        return None
    last = snaps[-1]
    return {
        "moneyline_home": last.get("moneyline_home"),
        "moneyline_away": last.get("moneyline_away"),
        "moneyline_draw": last.get("moneyline_draw"),
        "total_line":     last.get("total_line"),
        "over_odds":      last.get("over_odds"),
        "under_odds":     last.get("under_odds"),
        "spread_home":    last.get("spread_home"),
    }


def cleanup_old_snapshots(days_ago: int = 7) -> int:
    """Hapus snapshot yang lebih lama dari N hari. Return jumlah file dihapus."""
    cutoff  = time.time() - days_ago * 86400
    deleted = 0
    for p in _SNAPSHOT_DIR.glob("*.json"):
        try:
            snaps = json.loads(p.read_text(encoding="utf-8"))
            if snaps and snaps[-1].get("timestamp", 0) < cutoff:
                p.unlink()
                deleted += 1
        except Exception:
            continue
    if deleted:
        logger.info(f"odds_tracker: cleaned {deleted} old snapshot files")
    return deleted