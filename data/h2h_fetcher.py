"""
data/h2h_fetcher.py  [Gen 3 — Syntax fixed]
═══════════════════════════════════════════════════════════════════════════
Head-to-Head fetcher — ambil rekam historis pertemuan langsung dua tim.

Analoginya: seperti melihat rapor pertandingan dua petinju sebelum
mereka bertemu lagi. Data xG dan statistik musim ini penting, tetapi
ada tim yang secara historis selalu tampil buruk melawan lawan tertentu
meski di atas kertas lebih kuat — H2H menangkap faktor psikologis ini.

Sumber data (priority):
  1. API-Football /fixtures?last=10&... (jika API key tersedia)
  2. ESPN scoreboard historical (gratis, terbatas)
  3. Fallback → H2HRecord kosong (H2H tidak dipakai dalam ensemble)

Output: H2HRecord dengan home_win_pct, draw_pct, away_win_pct, dan
        rata-rata gol per pertandingan.
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


@dataclass
class H2HRecord:
    """Ringkasan rekam head-to-head antara dua tim."""
    home_team:       str
    away_team:       str
    matches_analyzed: int

    home_win_pct:    float   # 0.0–1.0 (relatif terhadap HOME tim ini, bukan venue)
    draw_pct:        float
    away_win_pct:    float

    avg_goals_home:  float   # rata-rata gol tim HOME yang sedang dianalisis
    avg_goals_away:  float

    last_5_results:  list[str]   # e.g. ["W", "W", "D", "L", "W"]
    data_source:     str = "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# API-Football H2H
# ─────────────────────────────────────────────────────────────────────────────

def _valid_key(cfg: dict) -> bool:
    key = cfg.get("api_football", {}).get("api_key", "")
    return isinstance(key, str) and bool(key) and "YOUR" not in key and len(key) > 10


def _apif_h2h(
    home_id: int,
    away_id: int,
    cfg: dict,
    n_matches: int = 10,
) -> list[dict]:
    """Ambil hasil H2H langsung dari API-Football."""
    key  = cfg.get("api_football", {}).get("api_key", "")
    base = cfg.get("api_football", {}).get("base_url", "https://v3.football.api-sports.io")
    try:
        r = requests.get(
            f"{base}/fixtures/headtohead",
            params={"h2h": f"{home_id}-{away_id}", "last": n_matches},
            headers={"x-rapidapi-key": key, "x-rapidapi-host": "v3.football.api-sports.io"},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            logger.warning(f"H2H API errors: {data['errors']}")
            return []
        return data.get("response", [])
    except Exception as exc:
        logger.warning(f"H2H API-Football error: {exc}")
        return []


def _parse_apif_h2h(fixtures: list[dict], home_team: str) -> Optional[H2HRecord]:
    """Parse hasil H2H dari API-Football ke H2HRecord."""
    if not fixtures:
        return None

    home_l = home_team.lower()
    wins = draws = losses = 0
    goals_home = goals_away = 0
    last_5: list[str] = []

    for f in fixtures:
        teams  = f.get("teams",   {})
        goals  = f.get("goals",   {})
        h_name = teams.get("home", {}).get("name", "").lower()
        a_name = teams.get("away", {}).get("name", "").lower()

        gf = goals.get("home") or 0
        ga = goals.get("away") or 0

        # Identifikasi apakah home_team bermain sebagai home atau away
        if home_l in h_name or h_name in home_l:
            team_gf, team_ga = gf, ga
        elif home_l in a_name or a_name in home_l:
            team_gf, team_ga = ga, gf
        else:
            continue   # tim tidak dikenal — skip

        goals_home += team_gf
        goals_away += team_ga

        if team_gf > team_ga:
            wins += 1
            last_5.append("W")
        elif team_gf == team_ga:
            draws += 1
            last_5.append("D")
        else:
            losses += 1
            last_5.append("L")

    total = wins + draws + losses
    if total == 0:
        return None

    return H2HRecord(
        home_team        = home_team,
        away_team        = "",
        matches_analyzed = total,
        home_win_pct     = round(wins   / total, 4),
        draw_pct         = round(draws  / total, 4),
        away_win_pct     = round(losses / total, 4),
        avg_goals_home   = round(goals_home / total, 2),
        avg_goals_away   = round(goals_away / total, 2),
        last_5_results   = last_5[:5],
        data_source      = "api-football",
    )


# ─────────────────────────────────────────────────────────────────────────────
# ESPN H2H fallback (terbatas — hanya event terbaru)
# ─────────────────────────────────────────────────────────────────────────────

def _espn_h2h(home: str, away: str, sport: str, league: str) -> Optional[H2HRecord]:
    """
    Coba ambil data H2H dari ESPN scoreboard.
    ESPN tidak menyediakan endpoint H2H dedicated, jadi ini best-effort.
    """
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
    try:
        r = requests.get(url, params={"limit": 100},
                         headers={"User-Agent": _UA}, timeout=15)
        r.raise_for_status()
        data    = r.json()
        home_l  = home.lower()
        away_l  = away.lower()
        results = []

        for ev in data.get("events", []):
            comp  = ev.get("competitions", [{}])[0]
            state = comp.get("status", {}).get("type", {}).get("state", "")
            if state not in ("post", "final"):
                continue
            competitors = comp.get("competitors", [])
            names = {c.get("homeAway"): c.get("team", {}).get("displayName", "").lower()
                     for c in competitors}
            scores = {c.get("homeAway"): int(c.get("score", 0) or 0)
                      for c in competitors}
            h_name = names.get("home", "")
            a_name = names.get("away", "")

            is_match = (
                (home_l in h_name or h_name in home_l) and
                (away_l in a_name or a_name in away_l)
            ) or (
                (home_l in a_name or a_name in home_l) and
                (away_l in h_name or h_name in away_l)
            )
            if not is_match:
                continue

            if home_l in h_name or h_name in home_l:
                gf, ga = scores.get("home", 0), scores.get("away", 0)
            else:
                gf, ga = scores.get("away", 0), scores.get("home", 0)
            results.append((gf, ga))

        if not results:
            return None

        wins   = sum(1 for gf, ga in results if gf > ga)
        draws  = sum(1 for gf, ga in results if gf == ga)
        losses = sum(1 for gf, ga in results if gf < ga)
        total  = len(results)

        last_5 = [
            ("W" if gf > ga else "D" if gf == ga else "L")
            for gf, ga in results[:5]
        ]

        return H2HRecord(
            home_team        = home,
            away_team        = away,
            matches_analyzed = total,
            home_win_pct     = round(wins   / total, 4),
            draw_pct         = round(draws  / total, 4),
            away_win_pct     = round(losses / total, 4),
            avg_goals_home   = round(sum(gf for gf, _ in results) / total, 2),
            avg_goals_away   = round(sum(ga for _, ga in results) / total, 2),
            last_5_results   = last_5,
            data_source      = "espn",
        )

    except Exception as exc:
        logger.warning(f"ESPN H2H [{home} vs {away}]: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

_SPORT_ESPN_MAP = {
    "soccer":     ("soccer",     "eng.1"),
    "basketball": ("basketball", "nba"),
    "hockey":     ("hockey",     "nhl"),
}


def get_h2h(
    home: str,
    away: str,
    league_key: str,
    sport: str,
    cfg: dict,
    home_team_id: Optional[int] = None,
    away_team_id: Optional[int] = None,
) -> Optional[H2HRecord]:
    """
    Ambil head-to-head record antara dua tim.

    Priority:
      1. API-Football (jika key tersedia DAN team IDs diberikan)
      2. ESPN scoreboard historical
      3. None (ensemble akan mengabaikan H2H jika < 4 matches)

    Minimum 4 pertandingan diperlukan agar H2H dipakai dalam ensemble.
    """
    # ── 1. API-Football H2H ──────────────────────────────────────────────────
    if _valid_key(cfg) and home_team_id and away_team_id:
        fixtures = _apif_h2h(home_team_id, away_team_id, cfg)
        record   = _parse_apif_h2h(fixtures, home)
        if record and record.matches_analyzed >= 4:
            record.away_team = away
            logger.info(f"H2H [{home} vs {away}]: {record.matches_analyzed} matches (API-Football)")
            return record

    # ── 2. ESPN H2H ──────────────────────────────────────────────────────────
    espn_map = _SPORT_ESPN_MAP.get(sport)
    if espn_map:
        record = _espn_h2h(home, away, espn_map[0], espn_map[1])
        if record and record.matches_analyzed >= 4:
            logger.info(f"H2H [{home} vs {away}]: {record.matches_analyzed} matches (ESPN)")
            return record

    # ── 3. Tidak cukup data ──────────────────────────────────────────────────
    logger.debug(f"H2H [{home} vs {away}]: insufficient data — H2H skipped in ensemble")

    # H2H probabilities — buat record minimal agar tidak crash
    h2h_total = 3  # sentinel < 4 → ensemble akan skip H2H
    h2h_ph    = 0.45
    h2h_pd    = 0.25
    h2h_pa    = 0.30

    return H2HRecord(
        home_team        = home,
        away_team        = away,
        matches_analyzed = h2h_total,
        home_win_pct     = h2h_ph,
        draw_pct         = h2h_pd,
        away_win_pct     = h2h_pa,
        avg_goals_home   = 1.2,
        avg_goals_away   = 1.0,
        last_5_results   = [],
        data_source      = "insufficient",
    )