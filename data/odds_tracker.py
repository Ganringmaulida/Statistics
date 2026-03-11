"""
data/odds_tracker.py  ←  FILE BARU GEN 3
═══════════════════════════════════════════════════════════════════════════
MENGAPA FILE INI ADA:
  Gen 2 hanya mengambil odds satu kali saat analisis.
  Gen 3 memantau PERGERAKAN odds setiap 15 menit dan menyimpannya.

  Analoginya: Gen 2 seperti melihat papan skor sekali lalu pergi.
  Gen 3 seperti duduk di depan papan dan mencatat setiap perubahannya.

  Pergerakan odds adalah sinyal kritis:
    Odds home: -150 → -200 dalam 1 jam
    → Sharp money masuk ke home  
    → Pasar yakin home akan menang
    → Jika model kita juga bilang home → confidence NAIK
    → Jika model kita bilang away → ada konflik, HATI-HATI

CARA KERJA:
  1. Poll The-Odds-API setiap 15 menit
  2. Simpan snapshot ke storage/odds_snapshots/{league}_{timestamp}.json
  3. Bandingkan dengan snapshot sebelumnya → hitung delta
  4. Klasifikasikan: SHARP (besar, cepat), DRIFT (perlahan), STABLE
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

import requests

logger = logging.getLogger(__name__)

SNAPSHOTS_DIR = Path("storage/odds_snapshots")


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class OddsSnapshot:
    """Satu snapshot odds untuk satu pertandingan pada satu waktu."""
    timestamp:      str
    league:         str
    home:           str
    away:           str
    ml_home:        Optional[float]   # American odds
    ml_draw:        Optional[float]
    ml_away:        Optional[float]
    spread_home:    Optional[float]
    spread_line:    Optional[float]
    total_line:     Optional[float]
    over_odds:      Optional[float]
    under_odds:     Optional[float]
    bookmaker:      str = "pinnacle"


@dataclass
class LineMovement:
    """Pergerakan odds antara dua snapshot."""
    home:           str
    away:           str
    league:         str
    field:          str               # "ml_home", "ml_away", "total_line", dll
    from_odds:      float
    to_odds:        float
    delta:          float             # Selisih absolut
    hours_elapsed:  float
    movement_type:  str               # "SHARP" | "DRIFT" | "REVERSE" | "STABLE"
    signal:         str               # "BUY_HOME" | "BUY_AWAY" | "FADE_HOME" | "NEUTRAL"
    from_ts:        str
    to_ts:          str


# ─────────────────────────────────────────────────────────────────────────────
# Odds fetching
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_raw_odds(sport_key: str, api_key: str) -> list[dict]:
    """Ambil raw odds dari The-Odds-API."""
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    try:
        r = requests.get(url, params={
            "apiKey": api_key,
            "regions": "us",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "american",
            "bookmakers": "pinnacle,draftkings,fanduel",
        }, timeout=15)
        r.raise_for_status()
        remaining = r.headers.get("x-requests-remaining", "?")
        logger.info(f"Odds fetched [{sport_key}] — quota remaining: {remaining}")
        return r.json()
    except Exception as exc:
        logger.warning(f"Odds fetch failed [{sport_key}]: {exc}")
        return []


def _parse_event_to_snapshot(event: dict, league: str) -> Optional[OddsSnapshot]:
    """Parse satu event dari API response → OddsSnapshot."""
    home = event.get("home_team", "")
    away = event.get("away_team", "")
    now  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    snap = OddsSnapshot(
        timestamp=now, league=league, home=home, away=away,
        ml_home=None, ml_draw=None, ml_away=None,
        spread_home=None, spread_line=None,
        total_line=None, over_odds=None, under_odds=None,
    )

    # Prioritas: Pinnacle > DraftKings > FanDuel
    priority = ["pinnacle", "draftkings", "fanduel"]
    bookmakers = {bk["key"]: bk for bk in event.get("bookmakers", [])}

    bk_data = None
    for pref in priority:
        if pref in bookmakers:
            bk_data = bookmakers[pref]
            snap.bookmaker = pref
            break
    if not bk_data and bookmakers:
        bk_data = list(bookmakers.values())[0]
        snap.bookmaker = list(bookmakers.keys())[0]
    if not bk_data:
        return None

    for mkt in bk_data.get("markets", []):
        key = mkt["key"]
        outcomes = mkt.get("outcomes", [])

        if key == "h2h":
            for o in outcomes:
                name = o["name"].lower()
                if "draw" in name:
                    snap.ml_draw = o["price"]
                elif home.split()[0].lower() in name or name in home.lower():
                    snap.ml_home = o["price"]
                else:
                    snap.ml_away = o["price"]

        elif key == "spreads":
            for o in outcomes:
                name = o["name"].lower()
                if home.split()[0].lower() in name or name in home.lower():
                    snap.spread_home = o["price"]
                    snap.spread_line = o.get("point")

        elif key == "totals":
            for o in outcomes:
                if o["name"] == "Over":
                    snap.total_line = o.get("point")
                    snap.over_odds  = o["price"]
                elif o["name"] == "Under":
                    snap.under_odds = o["price"]

    return snap


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot persistence
# ─────────────────────────────────────────────────────────────────────────────

def save_snapshot(snaps: list[OddsSnapshot], league: str) -> Path:
    """Simpan batch snapshot ke file JSON bernomor waktu."""
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    ts  = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
    p   = SNAPSHOTS_DIR / f"{league}_{ts}.json"
    p.write_text(
        json.dumps([asdict(s) for s in snaps], ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    logger.info(f"Snapshot saved: {p.name} ({len(snaps)} matches)")
    return p


def load_latest_snapshot(league: str, before_file: Optional[Path] = None) -> list[OddsSnapshot]:
    """
    Load snapshot terbaru untuk liga tertentu.
    before_file: jika ada, ambil snapshot sebelum file ini (untuk delta).
    """
    files = sorted(SNAPSHOTS_DIR.glob(f"{league}_*.json"), reverse=True)
    if not files:
        return []

    if before_file:
        files = [f for f in files if f != before_file]
        if not files:
            return []

    try:
        raw = json.loads(files[0].read_text(encoding="utf-8"))
        return [OddsSnapshot(**r) for r in raw]
    except Exception as exc:
        logger.warning(f"Snapshot load error: {exc}")
        return []


def load_all_snapshots(league: str, last_n: int = 10) -> list[list[OddsSnapshot]]:
    """Load N snapshot terakhir (untuk analisis trend)."""
    files = sorted(SNAPSHOTS_DIR.glob(f"{league}_*.json"), reverse=True)[:last_n]
    result = []
    for f in files:
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            result.append([OddsSnapshot(**r) for r in raw])
        except Exception:
            pass
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Line movement detection
# ─────────────────────────────────────────────────────────────────────────────

def _american_to_implied(american: float) -> float:
    """American odds → implied probability (raw, dengan vig)."""
    if american > 0:
        return 100 / (american + 100)
    return abs(american) / (abs(american) + 100)


def _classify_movement(delta: float, hours: float, field: str) -> tuple[str, str]:
    """
    Klasifikasikan jenis pergerakan dan signal yang dihasilkan.

    Threshold berdasarkan riset pasar taruhan:
      - SHARP: ≥5 point American dalam ≤2 jam → institutional money
      - DRIFT:  2–5 point dalam 2–6 jam → gradual public betting
      - STABLE: < 2 point → market noise, abaikan
      - REVERSE: arah berlawanan dari pergerakan sebelumnya → steam fade

    Untuk total line (O/U): threshold berbeda karena unit berbeda.
    """
    if "total" in field or "line" in field:
        # Total line: pergerakan 0.5 sudah signifikan
        threshold_sharp = 1.0
        threshold_drift = 0.5
    else:
        # Moneyline: pergerakan 5 point American
        threshold_sharp = 5.0
        threshold_drift = 2.0

    abs_delta = abs(delta)
    speed     = abs_delta / max(hours, 0.1)    # point per jam

    if abs_delta >= threshold_sharp and hours <= 3:
        mtype = "SHARP"
    elif abs_delta >= threshold_drift:
        mtype = "DRIFT"
    else:
        return "STABLE", "NEUTRAL"

    # Signal logic untuk moneyline home
    # Jika odds home TURUN (lebih negatif) = pasar mendukung home = BUY_HOME
    # Jika odds home NAIK (kurang negatif) = pasar meragukan home = FADE_HOME
    if "ml_home" in field:
        signal = "BUY_HOME" if delta < 0 else "FADE_HOME"
    elif "ml_away" in field:
        signal = "BUY_AWAY" if delta < 0 else "FADE_AWAY"
    elif "total" in field:
        signal = "OVER_SHARP" if delta > 0 else "UNDER_SHARP"
    else:
        signal = "NEUTRAL"

    return mtype, signal


def detect_line_movements(
    current:  list[OddsSnapshot],
    previous: list[OddsSnapshot],
) -> list[LineMovement]:
    """
    Bandingkan dua set snapshot, return list pergerakan yang terdeteksi.
    Hanya return SHARP dan DRIFT — abaikan STABLE.
    """
    if not previous:
        return []

    # Index previous by (home, away)
    prev_map = {(s.home, s.away): s for s in previous}

    movements: list[LineMovement] = []
    fields_to_check = ["ml_home", "ml_away", "total_line", "spread_line"]

    for cur in current:
        key  = (cur.home, cur.away)
        prev = prev_map.get(key)
        if not prev:
            continue

        # Parse timestamps for elapsed time
        try:
            t1 = datetime.fromisoformat(prev.timestamp.replace("Z", "+00:00"))
            t2 = datetime.fromisoformat(cur.timestamp.replace("Z", "+00:00"))
            hours = (t2 - t1).total_seconds() / 3600
        except Exception:
            hours = 1.0

        for field in fields_to_check:
            v_prev = getattr(prev, field)
            v_cur  = getattr(cur,  field)

            if v_prev is None or v_cur is None:
                continue

            delta = v_cur - v_prev
            if abs(delta) < 0.01:
                continue

            mtype, signal = _classify_movement(delta, hours, field)
            if mtype == "STABLE":
                continue

            movements.append(LineMovement(
                home=cur.home, away=cur.away, league=cur.league,
                field=field,
                from_odds=v_prev, to_odds=v_cur,
                delta=round(delta, 2),
                hours_elapsed=round(hours, 2),
                movement_type=mtype,
                signal=signal,
                from_ts=prev.timestamp,
                to_ts=cur.timestamp,
            ))

    return movements


# ─────────────────────────────────────────────────────────────────────────────
# Main tracker function (dipanggil oleh run_realtime.py)
# ─────────────────────────────────────────────────────────────────────────────

def track_odds(league_key: str, cfg: dict) -> tuple[list[OddsSnapshot], list[LineMovement]]:
    """
    Ambil odds terbaru, simpan snapshot, dan return pergerakan yang terdeteksi.

    Returns: (snapshots_baru, movements_yang_terdeteksi)
    """
    api_key   = cfg.get("the_odds_api", {}).get("api_key", "")
    if not api_key or api_key == "YOUR_ODDS_API_KEY_HERE":
        logger.warning(f"[{league_key}] No odds API key — skipping tracker")
        return [], []

    sport_key = cfg["leagues"][league_key].get("odds_key", "")
    if not sport_key:
        return [], []

    # Fetch
    raw_events = _fetch_raw_odds(sport_key, api_key)
    if not raw_events:
        return [], []

    # Parse → snapshots
    new_snaps = []
    for ev in raw_events:
        snap = _parse_event_to_snapshot(ev, league_key)
        if snap:
            new_snaps.append(snap)

    if not new_snaps:
        return [], []

    # Load previous snapshot untuk delta detection
    prev_snaps = load_latest_snapshot(league_key)

    # Save current
    save_snapshot(new_snaps, league_key)

    # Detect movements
    movements = detect_line_movements(new_snaps, prev_snaps)
    if movements:
        logger.info(
            f"[{league_key}] {len(movements)} line movements detected "
            f"({sum(1 for m in movements if m.movement_type == 'SHARP')} SHARP)"
        )

    return new_snaps, movements


def get_movement_summary(movements: list[LineMovement]) -> dict:
    """
    Ringkasan pergerakan untuk ditampilkan di UI.
    Returns: {(home, away): {"sharp_signals": [...], "drift_signals": [...], "net_direction": str}}
    """
    summary: dict = {}
    for mv in movements:
        key = (mv.home, mv.away)
        if key not in summary:
            summary[key] = {"sharp": [], "drift": [], "net_direction": "NEUTRAL"}
        if mv.movement_type == "SHARP":
            summary[key]["sharp"].append(mv)
        else:
            summary[key]["drift"].append(mv)

    # Net direction: lebih banyak BUY_HOME atau BUY_AWAY?
    for key, data in summary.items():
        all_mvs = data["sharp"] + data["drift"]
        home_buys = sum(1 for m in all_mvs if "HOME" in m.signal and "BUY" in m.signal)
        away_buys = sum(1 for m in all_mvs if "AWAY" in m.signal and "BUY" in m.signal)
        if home_buys > away_buys:
            data["net_direction"] = "LEAN_HOME"
        elif away_buys > home_buys:
            data["net_direction"] = "LEAN_AWAY"
        else:
            data["net_direction"] = "NEUTRAL"

    return summary