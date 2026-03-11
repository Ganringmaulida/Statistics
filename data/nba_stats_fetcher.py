"""
data/nba_stats_fetcher.py
─────────────────────────────────────────────────────────────────────────────
NBA Stats API (stats.nba.com) — Free, no API key required.
Memerlukan header HTTP yang tepat untuk menghindari blokir Akamai.

Endpoint:
  Standings : /stats/leaguestandingsv3
  Schedule  : /stats/scoreboard (atau ESPN sebagai fallback)
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Header wajib untuk stats.nba.com — tanpa ini akan 403
_NBA_HEADERS = {
    "Host":                "stats.nba.com",
    "User-Agent":          (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept":              "application/json, text/plain, */*",
    "Accept-Language":     "en-US,en;q=0.9",
    "Accept-Encoding":     "gzip, deflate, br",
    "x-nba-stats-origin":  "stats",
    "x-nba-stats-token":   "true",
    "Connection":          "keep-alive",
    "Referer":             "https://www.nba.com/",
    "Origin":              "https://www.nba.com",
    "Sec-Fetch-Dest":      "empty",
    "Sec-Fetch-Mode":      "cors",
    "Sec-Fetch-Site":      "same-site",
}

_BASE    = "https://stats.nba.com"
_TIMEOUT = 20


def _nba_get(endpoint: str, params: dict) -> Optional[dict]:
    try:
        time.sleep(0.5)   # rate-limit courtesy
        r = requests.get(
            f"{_BASE}{endpoint}",
            params=params,
            headers=_NBA_HEADERS,
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning(f"[NBA Stats] {endpoint}: {exc}")
        return None


def _parse_resultset(data: dict, set_index: int = 0) -> list[dict]:
    """
    stats.nba.com mengembalikan data dalam format:
    {resultSets: [{headers: [...], rowSet: [[...], ...]}]}
    Fungsi ini flatten-kan ke list of dict.
    """
    try:
        rs      = data["resultSets"][set_index]
        headers = rs["headers"]
        rows    = rs["rowSet"]
        return [dict(zip(headers, row)) for row in rows]
    except (KeyError, IndexError):
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Standings
# ─────────────────────────────────────────────────────────────────────────────

def fetch_nba_standings(season: str = "2024-25") -> list[dict]:
    """
    Ambil NBA standings via stats.nba.com.
    Returns list of {team, pts_for, pts_against, wins, loses, matches}.
    """
    data = _nba_get("/stats/leaguestandingsv3", {
        "LeagueID":   "00",
        "Season":     season,
        "SeasonType": "Regular Season",
    })
    if not data:
        return []

    rows    = _parse_resultset(data)
    results = []

    for row in rows:
        team    = row.get("TeamName", "") or row.get("TeamCity", "")
        city    = row.get("TeamCity", "")
        if city and team and city not in team:
            team = f"{city} {team}"

        wins    = int(row.get("WINS",   row.get("W",  0)))
        losses  = int(row.get("LOSSES", row.get("L",  0)))
        gp      = int(row.get("G",      wins + losses))

        # NBA standings v3 mungkin tidak menyertakan pts total secara langsung
        # kita gunakan PointsPg jika tersedia
        ppg  = float(row.get("PointsPg",  row.get("PTS",  0)) or 0)
        papg = float(row.get("OppPointsPg", row.get("OPP_PTS", 0)) or 0)

        results.append({
            "team":         team,
            "pts_for":      round(ppg * gp, 1),
            "pts_against":  round(papg * gp, 1),
            "wins":         wins,
            "loses":        losses,
            "matches":      gp,
        })

    logger.info(f"[NBA Stats] Standings: {len(results)} teams")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Standings via LeagueDashTeamStats (lebih detail — PPG tersedia)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_nba_team_stats(season: str = "2024-25") -> list[dict]:
    """
    Ambil statistik per-game tim NBA via LeagueDashTeamStats.
    Lebih detail: PPG, PAPG, W, L tersedia langsung.
    """
    data = _nba_get("/stats/leaguedashteamstats", {
        "MeasureType":    "Base",
        "PerMode":        "PerGame",
        "PlusMinus":      "N",
        "PaceAdjust":     "N",
        "Rank":           "N",
        "LeagueID":       "00",
        "Season":         season,
        "SeasonType":     "Regular Season",
        "PORound":        "0",
        "Outcome":        "",
        "Location":       "",
        "Month":          "0",
        "SeasonSegment":  "",
        "DateFrom":       "",
        "DateTo":         "",
        "OpponentTeamID": "0",
        "VsConference":   "",
        "VsDivision":     "",
        "TeamID":         "0",
        "Conference":     "",
        "Division":       "",
        "GameSegment":    "",
        "Period":         "0",
        "ShotClockRange": "",
        "LastNGames":     "0",
    })
    if not data:
        return []

    rows    = _parse_resultset(data)
    results = []

    for row in rows:
        team  = row.get("TEAM_NAME", "")
        gp    = int(row.get("GP",    0))
        wins  = int(row.get("W",     0))
        losses= int(row.get("L",     0))
        ppg   = float(row.get("PTS", 0))

        # PAPG tidak tersedia di Base, ambil via Opponent stats
        # Untuk sementara, kita gunakan nilai 0 dan isi dari opponent stats
        results.append({
            "team":        team,
            "pts_for":     round(ppg * gp, 1),
            "pts_against": 0.0,          # diisi oleh fetch_nba_opponent_stats
            "wins":        wins,
            "loses":       losses,
            "matches":     gp,
            "_ppg":        ppg,
            "_papg":       0.0,
        })

    # Ambil opponent stats untuk PAPG
    opp_map = _fetch_nba_opponent_stats(season)
    for r in results:
        opp = opp_map.get(r["team"], {})
        papg = float(opp.get("OPP_PTS", 0))
        r["pts_against"] = round(papg * r["matches"], 1)
        r["_papg"] = papg

    logger.info(f"[NBA Stats] Team stats: {len(results)} teams")
    return results


def _fetch_nba_opponent_stats(season: str) -> dict[str, dict]:
    """Ambil opponent scoring stats untuk PAPG."""
    data = _nba_get("/stats/leaguedashteamstats", {
        "MeasureType":    "Opponent",
        "PerMode":        "PerGame",
        "PlusMinus":      "N",
        "PaceAdjust":     "N",
        "Rank":           "N",
        "LeagueID":       "00",
        "Season":         season,
        "SeasonType":     "Regular Season",
        "PORound":        "0",
        "Outcome":        "",
        "Location":       "",
        "Month":          "0",
        "SeasonSegment":  "",
        "DateFrom":       "",
        "DateTo":         "",
        "OpponentTeamID": "0",
        "VsConference":   "",
        "VsDivision":     "",
        "TeamID":         "0",
        "Conference":     "",
        "Division":       "",
        "GameSegment":    "",
        "Period":         "0",
        "ShotClockRange": "",
        "LastNGames":     "0",
    })
    if not data:
        return {}
    rows = _parse_resultset(data)
    return {r.get("TEAM_NAME", ""): r for r in rows}