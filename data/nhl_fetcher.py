"""
data/nhl_fetcher.py
─────────────────────────────────────────────────────────────────────────────
NHL Official API (api-web.nhle.com) — Completely free, no API key required.

Endpoints yang digunakan:
  Standings : GET /v1/standings/now
  Schedule  : GET /v1/schedule/now   (+ /v1/schedule/{date})
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

_BASE    = "https://api-web.nhle.com"
_UA      = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept":     "application/json",
}
_TIMEOUT = 15


def _get(path: str, params: dict | None = None) -> dict | None:
    try:
        r = requests.get(
            f"{_BASE}{path}",
            params=params or {},
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning(f"[NHL API] {path}: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Standings
# ─────────────────────────────────────────────────────────────────────────────

def fetch_nhl_standings() -> list[dict]:
    """
    Ambil standings NHL saat ini.
    Returns list of {team, gf, ga, wins, loses, otl, pts, matches}.
    """
    data = _get("/v1/standings/now")
    if not data:
        return []

    results: list[dict] = []
    for t in data.get("standings", []):
        team_name = (
            t.get("teamName", {}).get("default", "")
            or t.get("teamCommonName", {}).get("default", "")
        )
        # Beberapa field memakai key berbeda bergantung versi API
        gp  = int(t.get("gamesPlayed", 0))
        wins = int(t.get("wins",        0))
        loss = int(t.get("losses",      0))
        otl  = int(t.get("otLosses",    0))
        gf   = int(t.get("goalFor",     t.get("goalsFor",    0)))
        ga   = int(t.get("goalAgainst", t.get("goalsAgainst", 0)))
        pts  = int(t.get("points",      wins * 2 + otl))

        if team_name:
            results.append({
                "team":    team_name,
                "gf":      gf,
                "ga":      ga,
                "wins":    wins,
                "loses":   loss,
                "otl":     otl,
                "pts":     pts,
                "matches": gp,
            })

    logger.info(f"[NHL API] Standings: {len(results)} teams")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Schedule / Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _parse_game(game: dict) -> dict | None:
    """Parse satu game dari NHL schedule API."""
    state = game.get("gameState", "")  # "FUT", "LIVE", "FINAL", "OFF"
    if state not in ("FUT", "PRE", "PREVIEW"):
        return None

    home = game.get("homeTeam", {})
    away = game.get("awayTeam", {})

    home_name = home.get("name", {}).get("default", "") or home.get("commonName", {}).get("default", "")
    away_name = away.get("name", {}).get("default", "") or away.get("commonName", {}).get("default", "")

    if not home_name or not away_name:
        return None

    date_str = game.get("startTimeUTC", game.get("gameDate", ""))[:16].replace("T", " ")
    venue    = game.get("venue", {}).get("default", "-")

    return {
        "home":  home_name,
        "away":  away_name,
        "date":  date_str,
        "venue": venue,
    }


def fetch_nhl_fixtures(days_ahead: int = 7) -> list[dict]:
    """
    Ambil jadwal NHL mendatang.
    NHL API mengembalikan minggu berjalan — kita iterasi beberapa tanggal jika perlu.
    """
    fixtures: list[dict] = []
    seen: set = set()

    today = datetime.now(timezone.utc)
    for delta in range(0, days_ahead, 1):
        date_str = (today + timedelta(days=delta)).strftime("%Y-%m-%d")
        data = _get(f"/v1/schedule/{date_str}")
        if not data:
            continue
        for day in data.get("gameWeek", []):
            for game in day.get("games", []):
                parsed = _parse_game(game)
                if parsed:
                    key = (parsed["home"], parsed["away"])
                    if key not in seen:
                        seen.add(key)
                        fixtures.append(parsed)

    logger.info(f"[NHL API] Fixtures: {len(fixtures)} upcoming games")
    return sorted(fixtures, key=lambda x: x["date"])