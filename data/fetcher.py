"""
data/fetcher.py  —  Production Data Fetcher  [Gen 3 Final]
═══════════════════════════════════════════════════════════════════════════
Sumber data realtime per liga:

  EPL  stats    → Understat (GRATIS, no key)
  EPL  fixtures → API-Football (100 req/day gratis, key di config.yaml)
  UCL  stats    → API-Football standings
  UCL  fixtures → API-Football
  NBA  stats    → BallDontLie (GRATIS setelah daftar di balldontlie.io)
  NBA  fixtures → BallDontLie games
  NHL  stats    → NHL Official API (100% GRATIS, no key)
  NHL  fixtures → NHL Official API (100% GRATIS, no key)
  Odds          → The-Odds-API (500 req/month gratis, key required)

Perbaikan dari Gen 2:
  ✅ NHL + Understat EPL jalan TANPA key apapun — realtime sekarang
  ✅ Fixtures hanya menampilkan pertandingan MENDATANG (1 jam – 7 hari)
  ✅ Cache diinvalidasi otomatis jika semua fixtures sudah lewat tanggal
  ✅ UCL stats dari API-Football bukan Understat (Understat tidak support UCL)
  ✅ NBA stats + schedule dari BallDontLie
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests

from data.demo_data import DEMO_TEAM_STATS, DEMO_FIXTURES, DEMO_INJURIES, DEMO_ODDS

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# ─────────────────────────────────────────────────────────────────────────────
# Cache helpers
# ─────────────────────────────────────────────────────────────────────────────

def _cache_path(cache_dir: str, key: str) -> Path:
    return Path(cache_dir) / f"{key.replace('/', '_')}.json"


def _read_cache(cache_dir: str, key: str, ttl_h: float) -> Optional[Any]:
    p = _cache_path(cache_dir, key)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if (time.time() - d["ts"]) / 3600 < ttl_h:
            return d["v"]
    except Exception:
        pass
    return None


def _write_cache(cache_dir: str, key: str, value: Any) -> None:
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    _cache_path(cache_dir, key).write_text(
        json.dumps({"ts": time.time(), "v": value}, ensure_ascii=False),
        encoding="utf-8",
    )


def _invalidate_cache(cache_dir: str, key: str) -> None:
    p = _cache_path(cache_dir, key)
    if p.exists():
        p.unlink()
        logger.debug(f"Cache invalidated: {key}")


def _fixtures_are_stale(fixtures: list[dict]) -> bool:
    """FIX: Invalidate cache jika semua fixtures sudah lewat tanggal."""
    if not fixtures:
        return True
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    future_count = sum(1 for f in fixtures if f.get("date", "") >= now_str)
    if future_count == 0:
        logger.warning(f"Semua {len(fixtures)} cached fixtures sudah lewat — invalidating")
        return True
    return False


def _read_fixtures_cache(cache_dir: str, key: str, ttl_h: float) -> Optional[list]:
    cached = _read_cache(cache_dir, key, ttl_h)
    if cached is None:
        return None
    if _fixtures_are_stale(cached):
        _invalidate_cache(cache_dir, key)
        return None
    return cached


# ─────────────────────────────────────────────────────────────────────────────
# API key checks
# ─────────────────────────────────────────────────────────────────────────────

def _has_odds_key(cfg: dict) -> bool:
    k = cfg.get("the_odds_api", {}).get("api_key", "")
    return bool(k) and "YOUR" not in k and len(k) > 10


def _has_football_key(cfg: dict) -> bool:
    k = cfg.get("api_football", {}).get("api_key", "")
    return bool(k) and "YOUR" not in k and len(k) > 10


def _has_balldontlie_key(cfg: dict) -> bool:
    k = cfg.get("balldontlie", {}).get("api_key", "")
    return bool(k) and "YOUR" not in k and len(k) > 10


# ─────────────────────────────────────────────────────────────────────────────
# Understat — EPL/domestic soccer xG  (GRATIS, no key)
# Support: EPL, La_liga, Bundesliga, Serie_A, Ligue_1, RFPL
# TIDAK support: UCL — Understat hanya liga domestik
# ─────────────────────────────────────────────────────────────────────────────

_UNDERSTAT_LEAGUES = {"EPL", "La_liga", "Bundesliga", "Serie_A", "Ligue_1", "RFPL"}


def _fetch_understat(understat_name: str, season: int) -> list[dict]:
    if understat_name not in _UNDERSTAT_LEAGUES:
        return []

    url = f"https://understat.com/league/{understat_name}/{season}"
    try:
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=20)
        r.raise_for_status()

        m = re.search(r"var\s+teamsData\s*=\s*JSON\.parse\('(.+?)'\)", r.text)
        if not m:
            logger.warning(f"Understat: teamsData pattern tidak ditemukan untuk {understat_name}")
            return []

        raw  = m.group(1)
        raw  = raw.replace("\\'", "'")
        data = json.loads(raw.encode().decode("unicode_escape"))

        out = []
        for _, td in data.items():
            hist   = td.get("history", [])
            if not hist:
                continue
            n      = len(hist)
            xg     = sum(float(h.get("xG",     0)) for h in hist)
            xga    = sum(float(h.get("xGA",    0)) for h in hist)
            scored = sum(int(h.get("scored",   0)) for h in hist)
            missed = sum(int(h.get("missed",   0)) for h in hist)
            pts    = sum(int(h.get("pts",      0)) for h in hist)
            wins   = sum(1 for h in hist if int(h.get("pts", 0)) == 3)
            draws  = sum(1 for h in hist if int(h.get("pts", 0)) == 1)
            losses = sum(1 for h in hist if int(h.get("pts", 0)) == 0)
            out.append({
                "team":    td.get("title", ""),
                "xg":      round(xg,  2),
                "xga":     round(xga, 2),
                "scored":  scored,
                "missed":  missed,
                "matches": n,
                "pts":     pts,
                "wins":    wins,
                "draws":   draws,
                "loses":   losses,
            })
        return sorted(out, key=lambda x: x["pts"], reverse=True)

    except requests.HTTPError as e:
        logger.warning(f"Understat fetch failed [{understat_name}]: {e}")
        return []
    except Exception as e:
        logger.warning(f"Understat parse error [{understat_name}]: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# ESPN Standings — soccer stats backup (GRATIS, no key needed)
# Source: site.api.espn.com — tersedia untuk EPL dan UCL
# Memberikan: W/D/L, GF, GA, GP untuk semua tim (20 EPL, 36 UCL grup)
# Kelebihan vs Understat: tidak pernah timeout, data stabil, nama tim lengkap
# ─────────────────────────────────────────────────────────────────────────────

_ESPN_SOCCER_LEAGUES = {
    "epl":  "https://site.api.espn.com/apis/v2/sports/soccer/eng.1/standings",
    "ucl":  "https://site.api.espn.com/apis/v2/sports/soccer/UEFA.CHAMPIONS/standings",
}


def _fetch_espn_soccer_stats(league_key: str) -> list[dict]:
    """
    Ambil standings dari ESPN API — gratis, tidak butuh key apapun.
    Converts GF/GA ke format yang sama dengan Understat (xg/xga proxy).
    Ibarat menggunakan ensiklopedia sebagai referensi saat buku utama habis tinta.
    """
    url = _ESPN_SOCCER_LEAGUES.get(league_key)
    if not url:
        return []

    try:
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.warning(f"ESPN stats fetch failed [{league_key}]: {exc}")
        return []

    # ESPN returns children[] for group stages (UCL) or single entry (EPL)
    entries = []
    children = data.get("children", [data])  # EPL has no children wrapper
    for child in children:
        standings = child.get("standings", {})
        if not standings:
            # Try direct entries
            standings = child
        grp_entries = standings.get("entries", [])
        entries.extend(grp_entries)

    if not entries:
        # Fallback: try top-level standings
        entries = data.get("standings", {}).get("entries", [])

    if not entries:
        logger.warning(f"ESPN stats: no entries found for [{league_key}]")
        return []

    def _stat(stats_list: list, name: str) -> float:
        for s in stats_list:
            if s.get("name") == name:
                return float(s.get("value", 0))
        return 0.0

    out = []
    seen = set()
    for entry in entries:
        team_obj = entry.get("team", {})
        name = team_obj.get("displayName", team_obj.get("name", ""))
        if not name or name in seen:
            continue
        seen.add(name)

        stats = entry.get("stats", [])
        wins   = int(_stat(stats, "wins"))
        draws  = int(_stat(stats, "ties"))
        losses = int(_stat(stats, "losses"))
        gf     = _stat(stats, "pointsFor")    # goals for (proxy for xG)
        ga     = _stat(stats, "pointsAgainst") # goals against (proxy for xGA)
        gp     = int(_stat(stats, "gamesPlayed")) or max(wins + draws + losses, 1)
        pts    = wins * 3 + draws

        out.append({
            "team":    name,
            "xg":      round(gf, 1),   # GF sebagai xG proxy
            "xga":     round(ga, 1),   # GA sebagai xGA proxy
            "scored":  int(gf),
            "missed":  int(ga),
            "matches": gp,
            "pts":     pts,
            "wins":    wins,
            "draws":   draws,
            "loses":   losses,
        })

    logger.info(f"ESPN stats [{league_key}]: {len(out)} teams")
    return sorted(out, key=lambda x: x["pts"], reverse=True)


# ─────────────────────────────────────────────────────────────────────────────
# API-Football — soccer stats, fixtures, injuries
# Gratis 100 req/day — daftar di api-football.com
# ─────────────────────────────────────────────────────────────────────────────

def _apif_get(cfg: dict, endpoint: str, params: dict) -> Optional[dict]:
    key  = cfg.get("api_football", {}).get("api_key", "")
    base = cfg.get("api_football", {}).get(
        "base_url", "https://v3.football.api-sports.io"
    )
    try:
        r = requests.get(
            f"{base}/{endpoint}",
            params=params,
            headers={
                "x-rapidapi-key":  key,
                "x-rapidapi-host": "v3.football.api-sports.io",
            },
            timeout=20,
        )
        r.raise_for_status()
        remaining = r.headers.get("x-ratelimit-requests-remaining", "?")
        logger.info(f"  API-Football /{endpoint} OK  (quota remaining: {remaining})")
        data = r.json()
        errors = data.get("errors", {})
        if errors:
            logger.warning(f"  API-Football errors: {errors}")
            return None
        return data
    except Exception as exc:
        logger.warning(f"  API-Football /{endpoint}: {exc}")
        return None


def _apif_soccer_stats(league_id: int, season: int, cfg: dict) -> list[dict]:
    data = _apif_get(cfg, "standings", {"league": league_id, "season": season})
    if not data:
        return []
    out = []
    try:
        for standing_group in data["response"][0]["league"]["standings"]:
            for entry in standing_group:
                team   = entry.get("team", {}).get("name", "")
                all_   = entry.get("all",  {})
                goals  = all_.get("goals", {})
                played = all_.get("played", 1) or 1
                wins   = all_.get("win",   0)
                draws  = all_.get("draw",  0)
                losses = all_.get("lose",  0)
                scored = goals.get("for",     0) or 0
                missed = goals.get("against", 0) or 0
                xg_approx  = round((scored / played) * 0.90, 2)
                xga_approx = round((missed / played) * 0.90, 2)
                out.append({
                    "team":    team,
                    "xg":      round(xg_approx  * played, 2),
                    "xga":     round(xga_approx * played, 2),
                    "scored":  scored,
                    "missed":  missed,
                    "matches": played,
                    "pts":     entry.get("points", 0),
                    "wins":    wins,
                    "draws":   draws,
                    "loses":   losses,
                })
    except (KeyError, IndexError) as exc:
        logger.warning(f"  API-Football standings parse error: {exc}")
    return sorted(out, key=lambda x: x["pts"], reverse=True)


def _apif_fixtures(league_id: int, season: int, days: int, cfg: dict) -> list[dict]:
    now    = datetime.now(timezone.utc)
    from_d = (now + timedelta(hours=1)).strftime("%Y-%m-%d")
    to_d   = (now + timedelta(days=days)).strftime("%Y-%m-%d")

    data = _apif_get(cfg, "fixtures", {
        "league":   league_id,
        "season":   season,
        "from":     from_d,
        "to":       to_d,
        "status":   "NS",
        "timezone": "UTC",
    })
    if not data:
        return []

    out     = []
    now_str = now.strftime("%Y-%m-%d %H:%M")
    for f in data.get("response", []):
        fix   = f.get("fixture", {})
        teams = f.get("teams",   {})
        venue = (fix.get("venue") or {}).get("name", "-")
        dt    = (fix.get("date") or "")[:16].replace("T", " ")
        home  = teams.get("home", {}).get("name", "")
        away  = teams.get("away", {}).get("name", "")
        if home and away and dt >= now_str:
            out.append({"home": home, "away": away, "date": dt, "venue": venue})
    return sorted(out, key=lambda x: x["date"])


def _apif_injuries(league_id: int, season: int, cfg: dict) -> list[dict]:
    data = _apif_get(cfg, "injuries", {"league": league_id, "season": season})
    if not data:
        return []
    return [
        {
            "team":   (item.get("team")   or {}).get("name", ""),
            "player": (item.get("player") or {}).get("name", ""),
            "type":   (item.get("player") or {}).get("type", ""),
            "key":    False,
        }
        for item in data.get("response", [])
    ]


# ─────────────────────────────────────────────────────────────────────────────
# BallDontLie — NBA stats + schedule (GRATIS setelah daftar di balldontlie.io)
# ─────────────────────────────────────────────────────────────────────────────

def _bdl_get(cfg: dict, endpoint: str, params: dict) -> Optional[dict]:
    key  = cfg.get("balldontlie", {}).get("api_key", "")
    base = cfg.get("balldontlie", {}).get(
        "base_url", "https://api.balldontlie.io/v1"
    )
    headers = {"Authorization": key} if key else {}
    try:
        r = requests.get(
            f"{base}/{endpoint}",
            params=params,
            headers=headers,
            timeout=20,
        )
        if r.status_code == 401:
            logger.warning(
                "BallDontLie: API key invalid atau tidak ada. "
                "Daftar GRATIS di https://www.balldontlie.io"
            )
            return None
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning(f"BallDontLie /{endpoint}: {exc}")
        return None


def _nba_stats_live(season: int, cfg: dict) -> list[dict]:
    data = _bdl_get(cfg, "standings", {"season": season})
    if not data:
        return []
    out = []
    for entry in data.get("data", []):
        team   = entry.get("team", {})
        wins   = entry.get("wins",   0) or 0
        losses = entry.get("losses", 0) or 0
        played = wins + losses or 1
        name   = team.get("full_name", "")
        win_pct     = wins / played
        pts_for     = round(105 + win_pct * 20, 1)
        pts_against = round(105 + (1 - win_pct) * 20, 1)
        out.append({
            "team":        name,
            "pts_for":     pts_for,
            "pts_against": pts_against,
            "wins":        wins,
            "loses":       losses,
            "matches":     played,
        })
    return sorted(out, key=lambda x: x["wins"], reverse=True)


def _nba_games_live(days: int, cfg: dict) -> list[dict]:
    now     = datetime.now(timezone.utc)
    start   = (now + timedelta(hours=1)).strftime("%Y-%m-%d")
    end     = (now + timedelta(days=days)).strftime("%Y-%m-%d")
    now_str = now.strftime("%Y-%m-%d %H:%M")

    data = _bdl_get(cfg, "games", {
        "start_date": start,
        "end_date":   end,
        "per_page":   25,
    })
    if not data:
        return []

    out = []
    for g in data.get("data", []):
        home   = g.get("home_team",    {}).get("full_name", "")
        away   = g.get("visitor_team", {}).get("full_name", "")
        date   = (g.get("date") or "")[:10] + " 00:00"
        status = g.get("status", "")
        is_sched = isinstance(status, str) and not any(
            c.isdigit() for c in status.replace(":", "")
        )
        if home and away and date >= now_str[:10] and is_sched:
            out.append({"home": home, "away": away, "date": date, "venue": "-"})
    return sorted(out, key=lambda x: x["date"])


# ─────────────────────────────────────────────────────────────────────────────
# NHL Official API — 100% GRATIS, no key needed
# https://api-web.nhle.com/v1/
# ─────────────────────────────────────────────────────────────────────────────

_NHL_NAMES: dict[str, str] = {
    "ANA": "Anaheim Ducks",        "BOS": "Boston Bruins",
    "BUF": "Buffalo Sabres",       "CGY": "Calgary Flames",
    "CAR": "Carolina Hurricanes",  "CHI": "Chicago Blackhawks",
    "COL": "Colorado Avalanche",   "CBJ": "Columbus Blue Jackets",
    "DAL": "Dallas Stars",         "DET": "Detroit Red Wings",
    "EDM": "Edmonton Oilers",      "FLA": "Florida Panthers",
    "LAK": "Los Angeles Kings",    "MIN": "Minnesota Wild",
    "MTL": "Montreal Canadiens",   "NSH": "Nashville Predators",
    "NJD": "New Jersey Devils",    "NYI": "New York Islanders",
    "NYR": "New York Rangers",     "OTT": "Ottawa Senators",
    "PHI": "Philadelphia Flyers",  "PIT": "Pittsburgh Penguins",
    "SEA": "Seattle Kraken",       "SJS": "San Jose Sharks",
    "STL": "St. Louis Blues",      "TBL": "Tampa Bay Lightning",
    "TOR": "Toronto Maple Leafs",  "UTA": "Utah Hockey Club",
    "VAN": "Vancouver Canucks",    "VGK": "Vegas Golden Knights",
    "WSH": "Washington Capitals",  "WPG": "Winnipeg Jets",
}


def _nhl_get(endpoint: str) -> Optional[dict]:
    base = "https://api-web.nhle.com/v1"
    try:
        r = requests.get(
            f"{base}/{endpoint}",
            headers={"User-Agent": _UA},
            timeout=20,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning(f"NHL API /{endpoint}: {exc}")
        return None


def _nhl_stats_live() -> list[dict]:
    data = _nhl_get("standings/now")
    if not data:
        return []
    out = []
    for entry in data.get("standings", []):
        abbr       = (entry.get("teamAbbrev")      or {}).get("default", "")
        team_name  = (entry.get("teamName")         or {}).get("default", "")
        full_name  = (entry.get("teamCommonName")   or {}).get("default", "")
        name  = full_name or team_name or _NHL_NAMES.get(abbr, abbr)
        wins  = entry.get("wins",       0)
        losses = entry.get("losses",    0)
        otl   = entry.get("otLosses",   0)
        pts   = entry.get("points",     0)
        gf    = entry.get("goalFor",    0)
        ga    = entry.get("goalAgainst",0)
        played = wins + losses + otl or 1
        out.append({
            "team":    name,
            "gf":      gf,
            "ga":      ga,
            "wins":    wins,
            "loses":   losses,
            "otl":     otl,
            "pts":     pts,
            "matches": played,
        })
    return sorted(out, key=lambda x: x["pts"], reverse=True)


def _nhl_schedule_live(days: int) -> list[dict]:
    now     = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M")
    cutoff  = (now + timedelta(days=days)).strftime("%Y-%m-%d")

    data = _nhl_get(f"schedule/{now.strftime('%Y-%m-%d')}")
    if not data:
        return []

    out = []
    for day in data.get("gameWeek", []):
        game_date = day.get("date", "")
        if game_date > cutoff:
            break
        for g in day.get("games", []):
            state = g.get("gameState", "")
            if state in ("FINAL", "LIVE", "OVER", "CRIT", "OFF"):
                continue

            home_info = g.get("homeTeam", {})
            away_info = g.get("awayTeam", {})
            home_abbr = home_info.get("abbrev", "")
            away_abbr = away_info.get("abbrev", "")

            home_place  = (home_info.get("placeName")  or {}).get("default", "")
            away_place  = (away_info.get("placeName")  or {}).get("default", "")
            home_common = (home_info.get("commonName") or {}).get("default", "")
            away_common = (away_info.get("commonName") or {}).get("default", "")

            home = (
                f"{home_place} {home_common}".strip()
                or _NHL_NAMES.get(home_abbr, home_abbr)
            )
            away = (
                f"{away_place} {away_common}".strip()
                or _NHL_NAMES.get(away_abbr, away_abbr)
            )

            start_utc = g.get("startTimeUTC", "")
            dt_str    = (
                start_utc[:16].replace("T", " ")
                if start_utc else f"{game_date} 00:00"
            )

            if dt_str < now_str:
                continue

            venue = (g.get("venue") or {}).get("default", "-")
            if home and away:
                out.append({"home": home, "away": away, "date": dt_str, "venue": venue})

    return sorted(out, key=lambda x: x["date"])


# ─────────────────────────────────────────────────────────────────────────────
# The-Odds-API — market odds
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_odds_live(sport_key: str, cfg: dict) -> list[dict]:
    key = cfg.get("the_odds_api", {}).get("api_key", "")
    url = (
        cfg.get("the_odds_api", {}).get("base_url", "https://api.the-odds-api.com/v4")
        + f"/sports/{sport_key}/odds"
    )
    try:
        r = requests.get(url, params={
            "apiKey":     key,
            "regions":    "us,uk",
            "markets":    "h2h,spreads,totals",
            "oddsFormat": "american",
        }, timeout=20)
        r.raise_for_status()
        remaining = r.headers.get("x-requests-remaining", "?")
        logger.info(f"  The-Odds-API [{sport_key}] quota remaining: {remaining}")
        return r.json()
    except Exception as exc:
        logger.warning(f"  The-Odds-API [{sport_key}]: {exc}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Demo fixture date refresher
# ─────────────────────────────────────────────────────────────────────────────

def _refresh_demo_dates(fixtures: list[dict]) -> list[dict]:
    """Assign tanggal fresh ke demo fixtures yang sudah lewat."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    fresh   = []
    offset  = 1
    for f in fixtures:
        if f.get("date", "") < now_str:
            new_date = (
                datetime.now(timezone.utc) + timedelta(days=offset)
            ).strftime("%Y-%m-%d 19:00")
            f = dict(f, date=new_date)
            offset += 1
        fresh.append(f)
    return fresh


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def get_team_stats(league_key: str, cfg: dict) -> list[dict]:
    lcfg      = cfg["leagues"][league_key]
    sport     = lcfg.get("sport", "soccer")
    cache_dir = cfg["cache"]["dir"]
    ttl       = cfg["cache"]["ttl_hours"]["stats"]
    ckey      = f"stats_{league_key}"

    cached = _read_cache(cache_dir, ckey, ttl)
    if cached:
        logger.info(f"  [{league_key}] Stats from cache ({len(cached)} teams)")
        return cached

    result: list[dict] = []

    if sport == "soccer":
        uname  = lcfg.get("understat_name", "")
        season = lcfg.get("season", 2024)

        if uname in _UNDERSTAT_LEAGUES:
            logger.info(f"  [{league_key}] Fetching Understat ({uname}/{season})…")
            result = _fetch_understat(uname, season)
            if result:
                logger.info(f"  [{league_key}] ✅ Understat: {len(result)} teams (realtime)")
            else:
                logger.warning(f"  [{league_key}] Understat gagal — mencoba ESPN backup…")

        # ESPN stats sebagai fallback — gratis, no key, stabil
        if not result and league_key in _ESPN_SOCCER_LEAGUES:
            logger.info(f"  [{league_key}] Fetching ESPN standings (gratis, no key)…")
            result = _fetch_espn_soccer_stats(league_key)
            if result:
                logger.info(f"  [{league_key}] ✅ ESPN: {len(result)} teams (realtime)")
            else:
                logger.warning(f"  [{league_key}] ESPN stats gagal")

        else:
            if not result:
                logger.info(f"  [{league_key}] '{uname}' tidak di Understat — mencoba ESPN…")
                if league_key in _ESPN_SOCCER_LEAGUES:
                    result = _fetch_espn_soccer_stats(league_key)
                    if result:
                        logger.info(f"  [{league_key}] ✅ ESPN: {len(result)} teams (realtime)")

        if not result:
            if _has_football_key(cfg):
                league_id = lcfg.get("api_football_id")
                if league_id:
                    logger.info(f"  [{league_key}] Fetching API-Football standings (id={league_id})…")
                    result = _apif_soccer_stats(league_id, season, cfg)
                    if result:
                        logger.info(f"  [{league_key}] ✅ API-Football: {len(result)} teams (realtime)")
            else:
                logger.warning(
                    f"  [{league_key}] ⚠  API-Football key tidak ada.\n"
                    f"           Daftar GRATIS di api-football.com\n"
                    f"           Tambahkan ke config.yaml:\n"
                    f"             api_football:\n"
                    f"               api_key: <key-anda>"
                )

    elif sport == "basketball":
        season = lcfg.get("season", 2024)
        if _has_balldontlie_key(cfg):
            logger.info(f"  [{league_key}] Fetching BallDontLie standings…")
            result = _nba_stats_live(season, cfg)
            if result:
                logger.info(f"  [{league_key}] ✅ BallDontLie: {len(result)} teams (realtime)")
        else:
            logger.warning(
                f"  [{league_key}] ⚠  BallDontLie key tidak ada.\n"
                f"           Daftar GRATIS di https://www.balldontlie.io\n"
                f"           Tambahkan ke config.yaml:\n"
                f"             balldontlie:\n"
                f"               api_key: <key-anda>"
            )

    elif sport == "hockey":
        logger.info(f"  [{league_key}] Fetching NHL Official API (gratis, no key)…")
        result = _nhl_stats_live()
        if result:
            logger.info(f"  [{league_key}] ✅ NHL API: {len(result)} teams (realtime)")
        else:
            logger.warning(f"  [{league_key}] NHL API tidak merespons")

    if not result:
        logger.info(f"  [{league_key}] ⚠  Menggunakan data DEMO")
        result = DEMO_TEAM_STATS.get(league_key, [])

    _write_cache(cache_dir, ckey, result)
    return result


def get_fixtures(league_key: str, cfg: dict) -> list[dict]:
    lcfg      = cfg["leagues"][league_key]
    sport     = lcfg.get("sport", "soccer")
    cache_dir = cfg["cache"]["dir"]
    ttl       = cfg["cache"]["ttl_hours"]["fixtures"]
    days      = cfg["display"]["fixtures_days_ahead"]
    ckey      = f"fixtures_{league_key}"

    cached = _read_fixtures_cache(cache_dir, ckey, ttl)
    if cached:
        logger.info(f"  [{league_key}] Fixtures from cache ({len(cached)} upcoming)")
        return cached

    result: list[dict] = []

    if sport == "soccer":
        if _has_football_key(cfg):
            league_id = lcfg.get("api_football_id")
            season    = lcfg.get("season", 2024)
            if league_id:
                logger.info(f"  [{league_key}] Fetching upcoming fixtures (next {days}d) dari API-Football…")
                result = _apif_fixtures(league_id, season, days, cfg)
                if result:
                    logger.info(
                        f"  [{league_key}] ✅ {len(result)} upcoming fixtures "
                        f"({result[0]['date']} – {result[-1]['date']})"
                    )
        else:
            logger.warning(f"  [{league_key}] ⚠  Soccer fixtures butuh API-Football key")

    elif sport == "basketball":
        if _has_balldontlie_key(cfg):
            logger.info(f"  [{league_key}] Fetching NBA games (next {days}d)…")
            result = _nba_games_live(days, cfg)
            if result:
                logger.info(f"  [{league_key}] ✅ {len(result)} upcoming NBA games")
        else:
            logger.warning(f"  [{league_key}] ⚠  NBA games butuh BallDontLie key")

    elif sport == "hockey":
        logger.info(f"  [{league_key}] Fetching NHL schedule (next {days}d, gratis)…")
        result = _nhl_schedule_live(days)
        if result:
            logger.info(
                f"  [{league_key}] ✅ {len(result)} upcoming NHL games "
                f"({result[0]['date']} – {result[-1]['date']})"
            )

    if not result:
        raw    = DEMO_FIXTURES.get(league_key, [])
        result = _refresh_demo_dates(raw)
        logger.info(f"  [{league_key}] ⚠  Menggunakan DEMO fixtures (tanggal di-refresh)")

    _write_cache(cache_dir, ckey, result)
    return result


def get_injuries(league_key: str, cfg: dict) -> list[dict]:
    lcfg      = cfg["leagues"][league_key]
    sport     = lcfg.get("sport", "soccer")
    cache_dir = cfg["cache"]["dir"]
    ttl       = cfg["cache"]["ttl_hours"]["injuries"]
    ckey      = f"injuries_{league_key}"

    cached = _read_cache(cache_dir, ckey, ttl)
    if cached:
        return cached

    result: list[dict] = []
    if sport == "soccer" and _has_football_key(cfg):
        league_id = lcfg.get("api_football_id")
        season    = lcfg.get("season", 2024)
        if league_id:
            logger.info(f"  [{league_key}] Fetching injuries dari API-Football…")
            result = _apif_injuries(league_id, season, cfg)
            if result:
                logger.info(f"  [{league_key}] ✅ {len(result)} injury records")

    if not result:
        result = DEMO_INJURIES.get(league_key, [])

    _write_cache(cache_dir, ckey, result)
    return result


def get_odds(home: str, away: str, league_key: str, cfg: dict) -> Optional[dict]:
    demo = DEMO_ODDS.get((home, away))
    if demo:
        return demo

    if not _has_odds_key(cfg):
        return None

    sport_key = cfg["leagues"][league_key].get("odds_key", "")
    if not sport_key:
        return None

    events = _fetch_odds_live(sport_key, cfg)
    for ev in events:
        ev_home = ev.get("home_team", "")
        ev_away = ev.get("away_team", "")
        home_match = (
            home.lower() in ev_home.lower()
            or ev_home.lower() in home.lower()
            or home.split()[-1].lower() in ev_home.lower()
        )
        away_match = (
            away.lower() in ev_away.lower()
            or ev_away.lower() in away.lower()
            or away.split()[-1].lower() in ev_away.lower()
        )
        if not (home_match and away_match):
            continue

        result: dict = {}
        for bk in ev.get("bookmakers", [])[:3]:
            for mkt in bk.get("markets", []):
                k        = mkt["key"]
                outcomes = mkt.get("outcomes", [])
                if k == "h2h":
                    for o in outcomes:
                        n = o["name"].lower()
                        if "draw" in n:
                            result["moneyline_draw"] = o["price"]
                        elif ev_home.split()[0].lower() in n:
                            result["moneyline_home"] = o["price"]
                        else:
                            result["moneyline_away"] = o["price"]
                elif k == "spreads":
                    for o in outcomes:
                        if ev_home.split()[0].lower() in o["name"].lower():
                            result["spread_home"]      = o.get("point", 0)
                            result["spread_home_odds"] = o["price"]
                        else:
                            result["spread_away"]      = o.get("point", 0)
                            result["spread_away_odds"] = o["price"]
                elif k == "totals":
                    for o in outcomes:
                        if o["name"] == "Over":
                            result["total_line"] = o.get("point", 0)
                            result["over_odds"]  = o["price"]
                        else:
                            result["under_odds"] = o["price"]
            if result:
                break
        return result if result else None

    return None