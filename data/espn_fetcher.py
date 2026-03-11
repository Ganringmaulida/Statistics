"""
data/espn_fetcher.py
─────────────────────────────────────────────────────────────────────────────
ESPN Public API — Fixtures + Standings (no API key required).

Endpoint map:
  Fixtures  → site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard
  Standings → site.web.api.espn.com/apis/v2/sports/{sport}/{league}/standings

Didukung:
  EPL   → soccer / eng.1
  UCL   → soccer / uefa.champions
  NBA   → basketball / nba
  NHL   → hockey / nhl
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _UA, "Accept": "application/json"}
_TIMEOUT = 15

# ── League config map ─────────────────────────────────────────────────────────
_ESPN_MAP = {
    "epl": {
        "sport": "soccer",
        "league": "eng.1",
        "scoreboard_dates": True,   # EPL needs ?dates= param
        "stat_pts_for":  None,
        "stat_pts_against": None,
    },
    "ucl": {
        "sport": "soccer",
        "league": "uefa.champions",
        "scoreboard_dates": True,
        "stat_pts_for":  None,
        "stat_pts_against": None,
    },
    "nba": {
        "sport": "basketball",
        "league": "nba",
        "scoreboard_dates": False,
        "stat_pts_for":  "pointsFor",
        "stat_pts_against": "pointsAgainst",
    },
    "nhl": {
        "sport": "hockey",
        "league": "nhl",
        "scoreboard_dates": False,
        "stat_pts_for":  "goalsFor",
        "stat_pts_against": "goalsAgainst",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def fetch_espn_fixtures(league_key: str, days_ahead: int = 7) -> list[dict]:
    """
    Ambil jadwal pertandingan mendatang dari ESPN scoreboard API.
    Returns list of {home, away, date, venue}.
    """
    cfg = _ESPN_MAP.get(league_key)
    if not cfg:
        return []

    sport  = cfg["sport"]
    league = cfg["league"]
    url    = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"

    params: dict = {"limit": 50}
    if cfg["scoreboard_dates"]:
        now = datetime.now(timezone.utc)
        from datetime import timedelta
        end = now + timedelta(days=days_ahead)
        params["dates"] = f"{now.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"

    try:
        r = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.warning(f"[ESPN] fixtures {league_key}: {exc}")
        return []

    fixtures: list[dict] = []
    for ev in data.get("events", []):
        comps = ev.get("competitions", [{}])[0]
        competitors = comps.get("competitors", [])
        if len(competitors) < 2:
            continue

        home_team = away_team = ""
        for c in competitors:
            name = c.get("team", {}).get("displayName", "")
            if c.get("homeAway") == "home":
                home_team = name
            else:
                away_team = name

        date_raw = ev.get("date", "")[:16].replace("T", " ")
        venue    = comps.get("venue", {}).get("fullName", "-")
        status   = ev.get("status", {}).get("type", {}).get("state", "pre")

        # Hanya ambil pertandingan yang belum dimulai (pre)
        if status == "pre" and home_team and away_team:
            fixtures.append({
                "home":  home_team,
                "away":  away_team,
                "date":  date_raw,
                "venue": venue,
            })

    return sorted(fixtures, key=lambda x: x["date"])


# ─────────────────────────────────────────────────────────────────────────────
# Standings → team stats (NBA / NHL)
# ─────────────────────────────────────────────────────────────────────────────

def _stat_val(stats: list[dict], name: str) -> float:
    for s in stats:
        if s.get("name") == name:
            try:
                return float(s.get("value", s.get("displayValue", 0)))
            except (ValueError, TypeError):
                return 0.0
    return 0.0


def fetch_espn_soccer_standings(league_key: str) -> list[dict]:
    """
    Ambil standings liga sepakbola dari ESPN.
    Digunakan sebagai fallback ketika Understat gagal.
    Returns list of {team, xg, xga, scored, missed, matches, wins, draws, loses, pts}
    Catatan: ESPN tidak punya xG — kita gunakan scored/missed sebagai proxy.
    """
    espn_league = {"epl": "eng.1", "ucl": "uefa.champions"}.get(league_key)
    if not espn_league:
        return []

    url = f"https://site.web.api.espn.com/apis/v2/sports/soccer/{espn_league}/standings"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.warning(f"[ESPN] Soccer standings {league_key}: {exc}")
        return []

    results: list[dict] = []
    for group in data.get("children", []):
        for entry in group.get("standings", {}).get("entries", []):
            team_name = entry.get("team", {}).get("displayName", "")
            stats     = entry.get("stats", [])

            gp    = int(_stat_val(stats, "gamesPlayed"))
            wins  = int(_stat_val(stats, "wins"))
            draws = int(_stat_val(stats, "ties"))
            loses = int(_stat_val(stats, "losses"))
            gf    = int(_stat_val(stats, "pointsFor"))    # ESPN pakai "pointsFor" untuk GF
            ga    = int(_stat_val(stats, "pointsAgainst"))
            pts   = int(_stat_val(stats, "points"))

            if not gp:
                gp = wins + draws + loses or 1

            results.append({
                "team":    team_name,
                # Gunakan GF/GA sebagai proxy xG (tidak ideal tapi fungsional)
                "xg":      round(gf, 1),
                "xga":     round(ga, 1),
                "scored":  gf,
                "missed":  ga,
                "matches": gp,
                "wins":    wins,
                "draws":   draws,
                "loses":   loses,
                "pts":     pts,
            })

    logger.info(f"[ESPN] Soccer standings {league_key}: {len(results)} teams")
    return sorted(results, key=lambda x: x["pts"], reverse=True)


def fetch_espn_nba_standings(season: int = 2025) -> list[dict]:
    """
    Ambil NBA standings dari ESPN.
    Returns list of {team, pts_for, pts_against, wins, loses, matches}.
    """
    url = (
        f"https://site.web.api.espn.com/apis/v2/sports/basketball/nba/standings"
        f"?season={season}&type=0"
    )
    try:
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.warning(f"[ESPN] NBA standings: {exc}")
        return []

    results: list[dict] = []
    for conf in data.get("children", []):
        for entry in conf.get("standings", {}).get("entries", []):
            team_name = entry.get("team", {}).get("displayName", "")
            stats     = entry.get("stats", [])

            wins    = int(_stat_val(stats, "wins"))
            losses  = int(_stat_val(stats, "losses"))
            gp      = int(_stat_val(stats, "gamesPlayed")) or (wins + losses)
            pts_for = _stat_val(stats, "pointsFor")
            pts_ag  = _stat_val(stats, "pointsAgainst")

            # ESPN menyimpan total, kita konversi ke per-game
            ppg     = round(pts_for / max(gp, 1), 1)
            papg    = round(pts_ag  / max(gp, 1), 1)

            results.append({
                "team":         team_name,
                "pts_for":      pts_for,
                "pts_against":  pts_ag,
                "wins":         wins,
                "loses":        losses,
                "matches":      gp,
                # per-game untuk convenience
                "ppg":          ppg,
                "papg":         papg,
            })

    logger.info(f"[ESPN] NBA standings: {len(results)} teams")
    return results


def fetch_espn_nhl_standings(season: int = 2025) -> list[dict]:
    """
    Ambil NHL standings dari ESPN.
    Returns list of {team, gf, ga, wins, loses, otl, matches}.
    """
    url = (
        f"https://site.web.api.espn.com/apis/v2/sports/hockey/nhl/standings"
        f"?season={season}&type=0"
    )
    try:
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.warning(f"[ESPN] NHL standings: {exc}")
        return []

    results: list[dict] = []
    for conf in data.get("children", []):
        for entry in conf.get("standings", {}).get("entries", []):
            team_name = entry.get("team", {}).get("displayName", "")
            stats     = entry.get("stats", [])

            wins = int(_stat_val(stats, "wins"))
            losses = int(_stat_val(stats, "losses"))
            otl  = int(_stat_val(stats, "otLosses"))
            gp   = int(_stat_val(stats, "gamesPlayed")) or (wins + losses + otl)
            gf   = int(_stat_val(stats, "goalsFor"))
            ga   = int(_stat_val(stats, "goalsAgainst"))

            results.append({
                "team":    team_name,
                "gf":      gf,
                "ga":      ga,
                "wins":    wins,
                "loses":   losses,
                "otl":     otl,
                "matches": gp,
                "pts":     wins * 2 + otl,
            })

    logger.info(f"[ESPN] NHL standings: {len(results)} teams")
    return results