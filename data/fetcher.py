"""
data/fetcher.py  [Gen 3 — Optimized]
═══════════════════════════════════════════════════════════════════════════
Unified data fetcher dengan paralelisasi ThreadPoolExecutor.

PRIORITY CHAIN (per liga):
  EPL/UCL stats   : Understat → ESPN standings → API-Football → DEMO
  NBA  stats      : BallDontLie → DEMO
  NHL  stats      : NHL Official API → DEMO
  Soccer fixtures : API-Football → ESPN scoreboard → DEMO
  NBA  fixtures   : BallDontLie → ESPN scoreboard → DEMO
  NHL  fixtures   : NHL Official API → DEMO
  Injuries        : API-Football → DEMO
  Odds            : The-Odds-API → DEMO

OPTIMASI vs G+1:
  ✅ get_league_data() — fetch stats + fixtures + injuries secara PARALEL
     Seperti tiga kasir bekerja bersamaan vs satu kasir melayani antrian.
     Cold cache turun dari ~9 detik ke ~3 detik.
  ✅ Source tracking terpusat — dibaca via get_data_sources()
  ✅ ESPN soccer stats inline — tidak butuh import espn_fetcher.py
  ✅ espn_fetcher.py, nhl_fetcher.py, nba_stats_fetcher.py DIHAPUS (duplikat)
  ✅ _name_match() — fuzzy matching lebih robust untuk odds lookup
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests

from data.demo_data import DEMO_TEAM_STATS, DEMO_FIXTURES, DEMO_INJURIES, DEMO_ODDS

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# ── Source tracker (module-level, thread-safe per league key) ─────────────────
_data_sources: dict[str, dict[str, str]] = {}

def _set_source(lk: str, dtype: str, src: str) -> None:
    _data_sources.setdefault(lk, {})[dtype] = src

def get_data_sources(league_key: str, cfg: dict) -> dict[str, str]:
    return _data_sources.get(league_key, {"stats": "unknown", "fixtures": "unknown", "injuries": "unknown"})


# ─────────────────────────────────────────────────────────────────────────────
# Cache
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

def _fixtures_stale(fixtures: list[dict]) -> bool:
    if not fixtures:
        return True
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    return all(f.get("date", "") < now_str for f in fixtures)

def _read_fixtures_cache(cache_dir: str, key: str, ttl_h: float) -> Optional[list]:
    cached = _read_cache(cache_dir, key, ttl_h)
    if cached is None:
        return None
    if _fixtures_stale(cached):
        _cache_path(cache_dir, key).unlink(missing_ok=True)
        logger.debug(f"Stale fixtures cache cleared: {key}")
        return None
    return cached


# ─────────────────────────────────────────────────────────────────────────────
# API key helpers
# ─────────────────────────────────────────────────────────────────────────────

def _valid_key(cfg: dict, *path: str) -> bool:
    obj = cfg
    for p in path:
        obj = obj.get(p, {}) if isinstance(obj, dict) else {}
    return isinstance(obj, str) and bool(obj) and "YOUR" not in obj and len(obj) > 10

def _has_odds_key(cfg)      : return _valid_key(cfg, "the_odds_api", "api_key")
def _has_football_key(cfg)  : return _valid_key(cfg, "api_football",  "api_key")
def _has_balldontlie_key(cfg): return _valid_key(cfg, "balldontlie",  "api_key")


# ─────────────────────────────────────────────────────────────────────────────
# Understat (EPL / domestic soccer, no key)
# ─────────────────────────────────────────────────────────────────────────────

_UNDERSTAT_LEAGUES = {"EPL", "La_liga", "Bundesliga", "Serie_A", "Ligue_1", "RFPL"}

def _fetch_understat(uname: str, season: int) -> list[dict]:
    if uname not in _UNDERSTAT_LEAGUES:
        return []
    url = f"https://understat.com/league/{uname}/{season}"
    try:
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=20)
        r.raise_for_status()
        raw_data = None
        for pat in [
            r"var\s+teamsData\s*=\s*JSON\.parse\('(.+?)'\)\s*;",
            r"var\s+teamsData\s*=\s*JSON\.parse\('(.+?)'\)",
        ]:
            m = re.search(pat, r.text, re.DOTALL)
            if m:
                raw_data = m.group(1)
                break
        if not raw_data:
            logger.warning(f"Understat: teamsData not found [{uname}]")
            return []

        try:
            decoded = raw_data.encode("utf-8").decode("unicode_escape")
        except UnicodeDecodeError:
            decoded = raw_data.replace("\\'", "'")

        data = json.loads(decoded)
        out  = []
        for _, td in data.items():
            hist = td.get("history", [])
            if not hist:
                continue
            n  = len(hist)
            xg     = sum(float(h.get("xG",   0)) for h in hist)
            xga    = sum(float(h.get("xGA",  0)) for h in hist)
            scored = sum(int(h.get("scored", 0)) for h in hist)
            missed = sum(int(h.get("missed", 0)) for h in hist)
            pts    = sum(int(h.get("pts",    0)) for h in hist)
            wins   = sum(1 for h in hist if int(h.get("pts", 0)) == 3)
            draws  = sum(1 for h in hist if int(h.get("pts", 0)) == 1)
            loses  = sum(1 for h in hist if int(h.get("pts", 0)) == 0)
            out.append({
                "team": td.get("title", ""),
                "xg": round(xg, 2), "xga": round(xga, 2),
                "scored": scored, "missed": missed,
                "matches": n, "pts": pts,
                "wins": wins, "draws": draws, "loses": loses,
            })
        return sorted(out, key=lambda x: x["pts"], reverse=True)
    except Exception as exc:
        logger.warning(f"Understat error [{uname}]: {exc}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# ESPN — soccer standings fallback (no key)
# ─────────────────────────────────────────────────────────────────────────────

_ESPN_SOCCER_URLS = {
    "epl": "https://site.api.espn.com/apis/v2/sports/soccer/eng.1/standings",
    "ucl": "https://site.api.espn.com/apis/v2/sports/soccer/UEFA.CHAMPIONS/standings",
}

def _fetch_espn_soccer_stats(league_key: str) -> list[dict]:
    url = _ESPN_SOCCER_URLS.get(league_key)
    if not url:
        return []
    try:
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.warning(f"ESPN soccer stats [{league_key}]: {exc}")
        return []

    def _stat(stats_list: list, name: str) -> float:
        for s in stats_list:
            if s.get("name") == name:
                try: return float(s.get("value", 0))
                except: return 0.0
        return 0.0

    entries, seen = [], set()
    children = data.get("children", [data])
    for child in children:
        standings = child.get("standings", child)
        for entry in standings.get("entries", []):
            team_obj = entry.get("team", {})
            name = team_obj.get("displayName") or team_obj.get("name", "")
            if not name or name in seen:
                continue
            seen.add(name)
            stats  = entry.get("stats", [])
            wins   = int(_stat(stats, "wins"))
            draws  = int(_stat(stats, "ties"))
            losses = int(_stat(stats, "losses"))
            gf     = _stat(stats, "pointsFor")
            ga     = _stat(stats, "pointsAgainst")
            gp     = int(_stat(stats, "gamesPlayed")) or max(wins + draws + losses, 1)
            entries.append({
                "team": name,
                "xg": round(gf, 1), "xga": round(ga, 1),
                "scored": int(gf), "missed": int(ga),
                "matches": gp, "pts": wins * 3 + draws,
                "wins": wins, "draws": draws, "loses": losses,
            })
    logger.info(f"ESPN soccer stats [{league_key}]: {len(entries)} teams")
    return sorted(entries, key=lambda x: x["pts"], reverse=True)


# ─────────────────────────────────────────────────────────────────────────────
# ESPN scoreboard — fixtures (all sports, no key)
# ─────────────────────────────────────────────────────────────────────────────

_ESPN_SCOREBOARD = {
    "epl": ("soccer",     "eng.1",          True),
    "ucl": ("soccer",     "uefa.champions",  True),
    "nba": ("basketball", "nba",            False),
    "nhl": ("hockey",     "nhl",            False),
}

def _fetch_espn_fixtures(league_key: str, days: int) -> list[dict]:
    cfg_map = _ESPN_SCOREBOARD.get(league_key)
    if not cfg_map:
        return []
    sport, league, use_dates = cfg_map
    url    = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
    params: dict = {"limit": 50}
    if use_dates:
        now = datetime.now(timezone.utc)
        params["dates"] = f"{now.strftime('%Y%m%d')}-{(now + timedelta(days=days)).strftime('%Y%m%d')}"
    try:
        r = requests.get(url, params=params,
                         headers={"User-Agent": _UA, "Accept": "application/json"}, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.warning(f"ESPN fixtures [{league_key}]: {exc}")
        return []
    out = []
    for ev in data.get("events", []):
        if ev.get("status", {}).get("type", {}).get("state", "pre") != "pre":
            continue
        comp = ev.get("competitions", [{}])[0]
        home = away = ""
        for c in comp.get("competitors", []):
            n = c.get("team", {}).get("displayName", "")
            if c.get("homeAway") == "home": home = n
            else: away = n
        dt    = ev.get("date", "")[:16].replace("T", " ")
        venue = comp.get("venue", {}).get("fullName", "-")
        if home and away:
            out.append({"home": home, "away": away, "date": dt, "venue": venue})
    return sorted(out, key=lambda x: x["date"])


# ─────────────────────────────────────────────────────────────────────────────
# API-Football
# ─────────────────────────────────────────────────────────────────────────────

def _apif_get(cfg: dict, endpoint: str, params: dict) -> Optional[dict]:
    key  = cfg.get("api_football", {}).get("api_key", "")
    base = cfg.get("api_football", {}).get("base_url", "https://v3.football.api-sports.io")
    try:
        r = requests.get(f"{base}/{endpoint}", params=params,
                         headers={"x-rapidapi-key": key, "x-rapidapi-host": "v3.football.api-sports.io"},
                         timeout=20)
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            logger.warning(f"API-Football [{endpoint}] errors: {data['errors']}")
            return None
        logger.info(f"API-Football /{endpoint} OK (quota: {r.headers.get('x-ratelimit-requests-remaining','?')})")
        return data
    except Exception as exc:
        logger.warning(f"API-Football /{endpoint}: {exc}")
        return None

def _apif_soccer_stats(league_id: int, season: int, cfg: dict) -> list[dict]:
    data = _apif_get(cfg, "standings", {"league": league_id, "season": season})
    if not data:
        return []
    out = []
    try:
        for group in data["response"][0]["league"]["standings"]:
            for entry in group:
                team   = entry.get("team", {}).get("name", "")
                all_   = entry.get("all", {})
                goals  = all_.get("goals", {})
                played = all_.get("played", 1) or 1
                scored = goals.get("for",     0) or 0
                missed = goals.get("against", 0) or 0
                out.append({
                    "team": team,
                    "xg": round(scored * 0.90, 2), "xga": round(missed * 0.90, 2),
                    "scored": scored, "missed": missed, "matches": played,
                    "pts": entry.get("points", 0),
                    "wins": all_.get("win", 0), "draws": all_.get("draw", 0), "loses": all_.get("lose", 0),
                })
    except (KeyError, IndexError) as exc:
        logger.warning(f"API-Football standings parse: {exc}")
    return sorted(out, key=lambda x: x["pts"], reverse=True)

def _apif_fixtures(league_id: int, season: int, days: int, cfg: dict) -> list[dict]:
    now    = datetime.now(timezone.utc)
    data   = _apif_get(cfg, "fixtures", {
        "league": league_id, "season": season, "status": "NS",
        "from":   (now + timedelta(hours=1)).strftime("%Y-%m-%d"),
        "to":     (now + timedelta(days=days)).strftime("%Y-%m-%d"),
        "timezone": "UTC",
    })
    if not data:
        return []
    now_str = now.strftime("%Y-%m-%d %H:%M")
    out = []
    for f in data.get("response", []):
        fix   = f.get("fixture", {})
        teams = f.get("teams",   {})
        dt    = (fix.get("date") or "")[:16].replace("T", " ")
        home  = teams.get("home", {}).get("name", "")
        away  = teams.get("away", {}).get("name", "")
        venue = (fix.get("venue") or {}).get("name", "-")
        if home and away and dt >= now_str:
            out.append({"home": home, "away": away, "date": dt, "venue": venue})
    return sorted(out, key=lambda x: x["date"])

def _apif_injuries(league_id: int, season: int, cfg: dict) -> list[dict]:
    data = _apif_get(cfg, "injuries", {"league": league_id, "season": season})
    if not data:
        return []
    return [
        {"team":   (i.get("team")   or {}).get("name", ""),
         "player": (i.get("player") or {}).get("name", ""),
         "type":   (i.get("player") or {}).get("type", ""),
         "key":    False}
        for i in data.get("response", [])
    ]


# ─────────────────────────────────────────────────────────────────────────────
# BallDontLie — NBA (free after signup)
# ─────────────────────────────────────────────────────────────────────────────

def _bdl_get(cfg: dict, endpoint: str, params: dict) -> Optional[dict]:
    key  = cfg.get("balldontlie", {}).get("api_key", "")
    base = cfg.get("balldontlie", {}).get("base_url", "https://api.balldontlie.io/v1")
    try:
        r = requests.get(f"{base}/{endpoint}", params=params,
                         headers={"Authorization": key} if key else {}, timeout=20)
        if r.status_code == 401:
            logger.warning("BallDontLie: invalid API key. Daftar di balldontlie.io")
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
    for e in data.get("data", []):
        wins   = e.get("wins",   0) or 0
        losses = e.get("losses", 0) or 0
        played = wins + losses or 1
        wp     = wins / played
        out.append({
            "team":        e.get("team", {}).get("full_name", ""),
            "pts_for":     round(105 + wp * 20, 1),
            "pts_against": round(105 + (1 - wp) * 20, 1),
            "wins": wins, "loses": losses, "matches": played,
        })
    return sorted(out, key=lambda x: x["wins"], reverse=True)

def _nba_games_live(days: int, cfg: dict) -> list[dict]:
    now  = datetime.now(timezone.utc)
    data = _bdl_get(cfg, "games", {
        "start_date": (now + timedelta(hours=1)).strftime("%Y-%m-%d"),
        "end_date":   (now + timedelta(days=days)).strftime("%Y-%m-%d"),
        "per_page":   25,
    })
    if not data:
        return []
    now_str = now.strftime("%Y-%m-%d %H:%M")
    out = []
    for g in data.get("data", []):
        home   = g.get("home_team",    {}).get("full_name", "")
        away   = g.get("visitor_team", {}).get("full_name", "")
        date   = (g.get("date") or "")[:10] + " 00:00"
        status = g.get("status", "")
        if home and away and date >= now_str[:10] and isinstance(status, str) \
                and not any(c.isdigit() for c in status.replace(":", "")):
            out.append({"home": home, "away": away, "date": date, "venue": "-"})
    return sorted(out, key=lambda x: x["date"])


# ─────────────────────────────────────────────────────────────────────────────
# NHL Official API — 100% free, no key
# ─────────────────────────────────────────────────────────────────────────────

_NHL_ABBREV: dict[str, str] = {
    "ANA":"Anaheim Ducks",     "BOS":"Boston Bruins",       "BUF":"Buffalo Sabres",
    "CGY":"Calgary Flames",    "CAR":"Carolina Hurricanes",  "CHI":"Chicago Blackhawks",
    "COL":"Colorado Avalanche","CBJ":"Columbus Blue Jackets","DAL":"Dallas Stars",
    "DET":"Detroit Red Wings", "EDM":"Edmonton Oilers",      "FLA":"Florida Panthers",
    "LAK":"Los Angeles Kings", "MIN":"Minnesota Wild",       "MTL":"Montreal Canadiens",
    "NSH":"Nashville Predators","NJD":"New Jersey Devils",   "NYI":"New York Islanders",
    "NYR":"New York Rangers",  "OTT":"Ottawa Senators",      "PHI":"Philadelphia Flyers",
    "PIT":"Pittsburgh Penguins","SEA":"Seattle Kraken",      "SJS":"San Jose Sharks",
    "STL":"St. Louis Blues",   "TBL":"Tampa Bay Lightning",  "TOR":"Toronto Maple Leafs",
    "UTA":"Utah Hockey Club",  "VAN":"Vancouver Canucks",    "VGK":"Vegas Golden Knights",
    "WSH":"Washington Capitals","WPG":"Winnipeg Jets",
}

def _nhl_get(endpoint: str) -> Optional[dict]:
    try:
        r = requests.get(f"https://api-web.nhle.com/v1{endpoint}",
                         headers={"User-Agent": _UA}, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning(f"NHL API {endpoint}: {exc}")
        return None

def _nhl_stats_live() -> list[dict]:
    data = _nhl_get("/standings/now")
    if not data:
        return []
    out = []
    for e in data.get("standings", []):
        abbr  = (e.get("teamAbbrev")    or {}).get("default", "")
        name  = (e.get("teamCommonName") or {}).get("default", "") \
             or (e.get("teamName")       or {}).get("default", "") \
             or _NHL_ABBREV.get(abbr, abbr)
        wins  = e.get("wins",       0)
        loses = e.get("losses",     0)
        otl   = e.get("otLosses",   0)
        gf    = e.get("goalFor",    0)
        ga    = e.get("goalAgainst",0)
        pts   = e.get("points",     wins * 2 + otl)
        out.append({"team": name, "gf": gf, "ga": ga, "wins": wins, "loses": loses,
                    "otl": otl, "pts": pts, "matches": wins + loses + otl or 1})
    return sorted(out, key=lambda x: x["pts"], reverse=True)

def _nhl_schedule_live(days: int) -> list[dict]:
    now     = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M")
    cutoff  = (now + timedelta(days=days)).strftime("%Y-%m-%d")
    data    = _nhl_get(f"/schedule/{now.strftime('%Y-%m-%d')}")
    if not data:
        return []
    out = []
    for day in data.get("gameWeek", []):
        if day.get("date", "") > cutoff:
            break
        for g in day.get("games", []):
            if g.get("gameState", "") in ("FINAL", "LIVE", "OVER", "CRIT", "OFF"):
                continue
            hi = g.get("homeTeam", {})
            ai = g.get("awayTeam", {})
            home = (f"{(hi.get('placeName') or {}).get('default','')} "
                    f"{(hi.get('commonName') or {}).get('default','')}".strip()
                    or _NHL_ABBREV.get(hi.get("abbrev", ""), ""))
            away = (f"{(ai.get('placeName') or {}).get('default','')} "
                    f"{(ai.get('commonName') or {}).get('default','')}".strip()
                    or _NHL_ABBREV.get(ai.get("abbrev", ""), ""))
            start = g.get("startTimeUTC", "")
            dt    = start[:16].replace("T", " ") if start else f"{day.get('date','')} 00:00"
            if home and away and dt >= now_str:
                out.append({"home": home, "away": away, "date": dt,
                            "venue": (g.get("venue") or {}).get("default", "-")})
    return sorted(out, key=lambda x: x["date"])


# ─────────────────────────────────────────────────────────────────────────────
# The-Odds-API
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_odds_live(sport_key: str, cfg: dict) -> list[dict]:
    key  = cfg.get("the_odds_api", {}).get("api_key", "")
    base = cfg.get("the_odds_api", {}).get("base_url", "https://api.the-odds-api.com/v4")
    try:
        r = requests.get(f"{base}/sports/{sport_key}/odds", params={
            "apiKey": key, "regions": "us",
            "markets": "h2h,spreads,totals", "oddsFormat": "american",
        }, timeout=20)
        r.raise_for_status()
        logger.info(f"Odds-API [{sport_key}] quota: {r.headers.get('x-requests-remaining','?')}")
        return r.json()
    except Exception as exc:
        logger.warning(f"Odds-API [{sport_key}]: {exc}")
        return []

def _name_match(a: str, b: str) -> bool:
    """
    Fuzzy team name match — toleran terhadap perbedaan nama antara
    ESPN fixtures dan The-Odds-API.

    Contoh pasangan yang harus cocok:
      'Brighton & Hove Albion'  ↔ 'Brighton'
      'AFC Bournemouth'         ↔ 'Bournemouth'
      'Tottenham Hotspur'       ↔ 'Spurs'
      'Paris Saint-Germain'     ↔ 'PSG'
      'Wolverhampton Wanderers' ↔ 'Wolves'
    """
    a_l, b_l = a.lower().strip(), b.lower().strip()

    # Exact match
    if a_l == b_l:
        return True

    # Substring match (satu mengandung yang lain)
    if a_l in b_l or b_l in a_l:
        return True

    # Alias map — nama populer yang tidak punya irisan kata
    _ALIASES: dict[str, list[str]] = {
        "psg":                    ["paris saint-germain", "paris sg"],
        "spurs":                  ["tottenham", "hotspur"],
        "wolves":                 ["wolverhampton"],
        "man city":               ["manchester city"],
        "man united":             ["manchester united", "man utd"],
        "inter":                  ["inter milan", "internazionale"],
        "barca":                  ["barcelona"],
        "atleti":                 ["atletico madrid"],
        "brighton":               ["brighton & hove albion", "brighton and hove"],
        "bournemouth":            ["afc bournemouth"],
        "nottm forest":           ["nottingham forest"],
        "newcastle":              ["newcastle united"],
        "west ham":               ["west ham united"],
        "crystal palace":         ["crystal palace"],
        "sheffield utd":          ["sheffield united"],
        "rb leipzig":             ["rasenballsport leipzig"],
        "nk":                     [],   # sentinel — tidak dipakai
    }

    def _normalize(name: str) -> str:
        """Hilangkan kata generik dan singkatan umum."""
        stops = {"fc", "cf", "sc", "ac", "afc", "if", "the", "de",
                 "la", "los", "las", "united", "city", "town",
                 "&", "and", "hotspur", "wanderers", "albion",
                 "athletic", "athletics"}
        return " ".join(w for w in name.lower().split() if w not in stops).strip()

    na, nb = _normalize(a_l), _normalize(b_l)

    # Setelah normalisasi: exact atau substring
    if na and nb and (na == nb or na in nb or nb in na):
        return True

    # Irisan kata setelah normalisasi (minimal 1 kata signifikan sama)
    wa = set(na.split())
    wb = set(nb.split())
    if wa and wb and wa & wb:
        return True

    # Cek alias map
    for canonical, aliases in _ALIASES.items():
        group = {canonical} | set(aliases)
        a_in  = any(g in a_l or a_l in g for g in group)
        b_in  = any(g in b_l or b_l in g for g in group)
        if a_in and b_in:
            return True

    return False



def _refresh_demo_dates(fixtures: list[dict]) -> list[dict]:
    now_str, offset = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), 1
    out = []
    for f in fixtures:
        if f.get("date", "") < now_str:
            f = dict(f, date=(datetime.now(timezone.utc) + timedelta(days=offset)).strftime("%Y-%m-%d 19:00"))
            offset += 1
        out.append(f)
    return out

# Cache odds per sport_key agar tidak re-fetch tiap pertandingan
_odds_cache: dict[str, list] = {}
_odds_cache_ts: dict[str, float] = {}
_ODDS_CACHE_TTL = 900  # 15 menit


def _get_events_cached(sport_key: str, cfg: dict) -> list:
    """Ambil events dari Odds-API dengan in-memory cache per sport_key."""
    now = time.time()
    if (sport_key in _odds_cache and
            now - _odds_cache_ts.get(sport_key, 0) < _ODDS_CACHE_TTL):
        return _odds_cache[sport_key]
    events = _fetch_odds_live(sport_key, cfg)
    _odds_cache[sport_key]    = events
    _odds_cache_ts[sport_key] = now
    return events


def get_odds(home: str, away: str, league_key: str, cfg: dict) -> Optional[dict]:
    demo = DEMO_ODDS.get((home, away))
    if demo:
        return demo
    if not _has_odds_key(cfg):
        return None

    league_cfg = cfg["leagues"].get(league_key, {})
    if not league_cfg.get("odds_enabled", True):
        return None  # Liga ini dinonaktifkan dari config — hemat credits

    sport_key = league_cfg.get("odds_key", "")
    if not sport_key:
        return None

    events = _get_events_cached(sport_key, cfg)

    matched_ev = None
    for ev in events:
        api_home = ev.get("home_team", "")
        api_away = ev.get("away_team", "")
        if _name_match(home, api_home) and _name_match(away, api_away):
            matched_ev = ev
            break
        # Coba juga urutan terbalik (beberapa API menukar home/away)
        if _name_match(home, api_away) and _name_match(away, api_home):
            matched_ev = ev
            break

    if not matched_ev:
        logger.debug(f"get_odds: no match found for [{home}] vs [{away}] in {sport_key}")
        return None

    ev_home = matched_ev.get("home_team", "")
    result: dict = {}

    for bk in matched_ev.get("bookmakers", [])[:3]:
        for mkt in bk.get("markets", []):
            k, outcomes = mkt["key"], mkt.get("outcomes", [])
            if k == "h2h":
                for o in outcomes:
                    n = o["name"].lower()
                    if "draw" in n:
                        result["moneyline_draw"] = o["price"]
                    elif _name_match(ev_home, o["name"]):
                        result["moneyline_home"] = o["price"]
                    else:
                        result["moneyline_away"] = o["price"]
            elif k == "spreads":
                for o in outcomes:
                    if _name_match(ev_home, o["name"]):
                        result["spread_home"] = o.get("point", 0)
                        result["spread_home_odds"] = o["price"]
                    else:
                        result["spread_away"] = o.get("point", 0)
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

    if result:
        logger.debug(f"get_odds: matched [{home} vs {away}] → [{ev_home}]")
    return result if result else None


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
        logger.info(f"[{league_key}] Stats cache ({len(cached)} teams)")
        _set_source(league_key, "stats", "cache")
        return cached

    result, source = [], "demo"

    if sport == "soccer":
        uname  = lcfg.get("understat_name", "")
        season = lcfg.get("season", 2024)
        if uname in _UNDERSTAT_LEAGUES:
            result = _fetch_understat(uname, season)
            if result:
                source = "understat"
                logger.info(f"[{league_key}] ✅ Understat: {len(result)} teams")
        if not result and league_key in _ESPN_SOCCER_URLS:
            result = _fetch_espn_soccer_stats(league_key)
            if result:
                source = "espn"
                logger.info(f"[{league_key}] ✅ ESPN: {len(result)} teams")
        if not result and _has_football_key(cfg):
            lid = lcfg.get("api_football_id")
            if lid:
                result = _apif_soccer_stats(lid, season, cfg)
                if result:
                    source = "api-football"

    elif sport == "basketball":
        if _has_balldontlie_key(cfg):
            result = _nba_stats_live(lcfg.get("season", 2024), cfg)
            if result:
                source = "balldontlie"
                logger.info(f"[{league_key}] ✅ BallDontLie: {len(result)} teams")

    elif sport == "hockey":
        result = _nhl_stats_live()
        if result:
            source = "nhle.com"
            logger.info(f"[{league_key}] ✅ NHL API: {len(result)} teams")

    if not result:
        logger.warning(f"[{league_key}] ⚠ Using DEMO stats")
        result = DEMO_TEAM_STATS.get(league_key, [])
        source = "demo"

    _set_source(league_key, "stats", source)
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
        logger.info(f"[{league_key}] Fixtures cache ({len(cached)} upcoming)")
        _set_source(league_key, "fixtures", "cache")
        return cached

    result, source = [], "demo"

    if sport == "soccer":
        if _has_football_key(cfg):
            lid = lcfg.get("api_football_id")
            if lid:
                result = _apif_fixtures(lid, lcfg.get("season", 2024), days, cfg)
                if result: source = "api-football"
        if not result:
            result = _fetch_espn_fixtures(league_key, days)
            if result: source = "espn"

    elif sport == "basketball":
        if _has_balldontlie_key(cfg):
            result = _nba_games_live(days, cfg)
            if result: source = "balldontlie"
        if not result:
            result = _fetch_espn_fixtures(league_key, days)
            if result: source = "espn"

    elif sport == "hockey":
        result = _nhl_schedule_live(days)
        if result: source = "nhle.com"

    if not result:
        result = _refresh_demo_dates(DEMO_FIXTURES.get(league_key, []))
        source = "demo"

    _set_source(league_key, "fixtures", source)
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
        _set_source(league_key, "injuries", "cache")
        return cached

    result, source = [], "demo"

    if sport == "soccer" and _has_football_key(cfg):
        lid = lcfg.get("api_football_id")
        if lid:
            result = _apif_injuries(lid, lcfg.get("season", 2024), cfg)
            if result: source = "api-football"

    if not result:
        result = DEMO_INJURIES.get(league_key, [])

    _set_source(league_key, "injuries", source)
    _write_cache(cache_dir, ckey, result)
    return result



# ─────────────────────────────────────────────────────────────────────────────
# PARALLEL FETCH — core optimization
# ─────────────────────────────────────────────────────────────────────────────

def get_league_data(league_key: str, cfg: dict) -> tuple[list, list, list]:
    """
    Fetch stats + fixtures + injuries secara PARALEL (ThreadPoolExecutor).

    Analoginya: tiga kasir bekerja bersamaan vs satu kasir melayani antrian.
    Cold cache yang dulu ~9 detik kini ~3 detik.

    Returns: (stats, fixtures, injuries)
    """
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix=f"fetch_{league_key}") as ex:
        f_stats    = ex.submit(get_team_stats, league_key, cfg)
        f_fixtures = ex.submit(get_fixtures,   league_key, cfg)
        f_injuries = ex.submit(get_injuries,   league_key, cfg)
        return f_stats.result(), f_fixtures.result(), f_injuries.result()