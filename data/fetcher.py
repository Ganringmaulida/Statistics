"""
data/fetcher.py
Unified data fetcher — real API jika key ada, demo data jika tidak.
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
        json.dumps({"ts": time.time(), "v": value}), encoding="utf-8"
    )


# ─────────────────────────────────────────────────────────────────────────────
# API key checks
# ─────────────────────────────────────────────────────────────────────────────

def _has_odds_key(cfg: dict) -> bool:
    k = cfg.get("the_odds_api", {}).get("api_key", "")
    return bool(k) and k != "YOUR_ODDS_API_KEY_HERE"

def _has_football_key(cfg: dict) -> bool:
    k = cfg.get("api_football", {}).get("api_key", "")
    return bool(k) and k != "YOUR_API_FOOTBALL_KEY_HERE"


# ─────────────────────────────────────────────────────────────────────────────
# Understat — xG data (no key needed)
# ─────────────────────────────────────────────────────────────────────────────

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36")

def _understat_teams(league_name: str, season: int) -> list[dict]:
    url = f"https://understat.com/league/{league_name}/{season}"
    try:
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=15)
        r.raise_for_status()
        m = re.search(r"var\s+teamsData\s*=\s*JSON\.parse\('(.+?)'\)", r.text)
        if not m:
            return []
        raw = m.group(1).encode("utf-8").decode("unicode_escape")
        teams_raw = json.loads(raw)
        out = []
        for _, td in teams_raw.items():
            hist = td.get("history", [])
            if not hist:
                continue
            n      = len(hist)
            xg     = sum(float(h.get("xG",  0)) for h in hist)
            xga    = sum(float(h.get("xGA", 0)) for h in hist)
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
        logger.warning(f"Understat fetch failed: {exc}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# API-Football — fixtures & injuries
# ─────────────────────────────────────────────────────────────────────────────

def _apif_get(cfg: dict, endpoint: str, params: dict) -> Optional[dict]:
    key = cfg.get("api_football", {}).get("api_key", "")
    url = f"{cfg['api_football']['base_url']}/{endpoint}"
    try:
        r = requests.get(url, params=params, timeout=15,
                         headers={"x-rapidapi-key": key,
                                  "x-rapidapi-host": "v3.football.api-sports.io"})
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning(f"API-Football /{endpoint}: {exc}")
        return None

def _fetch_fixtures_live(league_id: int, season: int, days: int, cfg: dict) -> list[dict]:
    now  = datetime.now(timezone.utc)
    data = _apif_get(cfg, "fixtures", {
        "league": league_id, "season": season,
        "from":   now.strftime("%Y-%m-%d"),
        "to":     (now + timedelta(days=days)).strftime("%Y-%m-%d"),
    })
    if not data:
        return []
    out = []
    for f in data.get("response", []):
        fix   = f.get("fixture", {})
        teams = f.get("teams", {})
        venue = fix.get("venue", {}) or {}
        dt    = fix.get("date", "")[:16].replace("T", " ")
        out.append({
            "home":  teams.get("home", {}).get("name", ""),
            "away":  teams.get("away", {}).get("name", ""),
            "date":  dt,
            "venue": venue.get("name", "-"),
        })
    return sorted(out, key=lambda x: x["date"])

def _fetch_injuries_live(league_id: int, season: int, cfg: dict) -> list[dict]:
    data = _apif_get(cfg, "injuries", {"league": league_id, "season": season})
    if not data:
        return []
    return [
        {
            "team":   item.get("team",   {}).get("name", ""),
            "player": item.get("player", {}).get("name", ""),
            "type":   item.get("player", {}).get("type",   ""),
            "key":    False,
        }
        for item in data.get("response", [])
    ]


# ─────────────────────────────────────────────────────────────────────────────
# The-Odds-API — market odds
# ─────────────────────────────────────────────────────────────────────────────

def _american_to_prob(american: float) -> float:
    if american > 0:
        return 100 / (american + 100)
    return abs(american) / (abs(american) + 100)

def _fetch_odds_live(sport_key: str, cfg: dict) -> list[dict]:
    key = cfg.get("the_odds_api", {}).get("api_key", "")
    url = f"{cfg['the_odds_api']['base_url']}/sports/{sport_key}/odds"
    try:
        r = requests.get(url, params={
            "apiKey": key, "regions": "us,uk",
            "markets": "h2h,spreads,totals", "oddsFormat": "american",
        }, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning(f"The-Odds-API: {exc}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Public API — unified getters
# ─────────────────────────────────────────────────────────────────────────────

def get_team_stats(league_key: str, cfg: dict) -> list[dict]:
    """Ambil statistik tim (xG/xGA untuk soccer, pts for/against untuk NBA/NHL)."""
    lcfg      = cfg["leagues"][league_key]
    sport     = lcfg["sport"]
    cache_dir = cfg["cache"]["dir"]
    ttl       = cfg["cache"]["ttl_hours"]["stats"]
    ckey      = f"stats_{league_key}"

    cached = _read_cache(cache_dir, ckey, ttl)
    if cached:
        logger.info(f"[{league_key}] Stats from cache")
        return cached

    result: list[dict] = []

    if sport == "soccer":
        uname = lcfg.get("understat_name", "")
        season = lcfg.get("season", 2024)
        if uname:
            logger.info(f"[{league_key}] Fetching Understat xG data…")
            result = _understat_teams(uname, season)

    if not result:
        logger.info(f"[{league_key}] Using demo stats data")
        result = DEMO_TEAM_STATS.get(league_key, [])

    _write_cache(cache_dir, ckey, result)
    return result


def get_fixtures(league_key: str, cfg: dict) -> list[dict]:
    """Ambil jadwal pertandingan mendatang."""
    lcfg      = cfg["leagues"][league_key]
    cache_dir = cfg["cache"]["dir"]
    ttl       = cfg["cache"]["ttl_hours"]["fixtures"]
    days      = cfg["display"]["fixtures_days_ahead"]
    ckey      = f"fixtures_{league_key}"

    cached = _read_cache(cache_dir, ckey, ttl)
    if cached:
        return cached

    result: list[dict] = []
    if _has_football_key(cfg):
        result = _fetch_fixtures_live(
            lcfg["api_football_id"], lcfg["season"], days, cfg
        )

    if not result:
        logger.info(f"[{league_key}] Using demo fixture data")
        result = DEMO_FIXTURES.get(league_key, [])

    _write_cache(cache_dir, ckey, result)
    return result


def get_injuries(league_key: str, cfg: dict) -> list[dict]:
    """Ambil data cedera pemain."""
    lcfg      = cfg["leagues"][league_key]
    cache_dir = cfg["cache"]["dir"]
    ttl       = cfg["cache"]["ttl_hours"]["injuries"]
    ckey      = f"injuries_{league_key}"

    cached = _read_cache(cache_dir, ckey, ttl)
    if cached:
        return cached

    result: list[dict] = []
    if _has_football_key(cfg):
        result = _fetch_injuries_live(lcfg["api_football_id"], lcfg["season"], cfg)

    if not result:
        result = DEMO_INJURIES.get(league_key, [])

    _write_cache(cache_dir, ckey, result)
    return result


def get_odds(home: str, away: str, league_key: str, cfg: dict) -> Optional[dict]:
    """
    Ambil odds pasar untuk satu pertandingan.
    Lookup dari The-Odds-API atau demo data.
    """
    # Cek demo data dulu (exact match)
    demo = DEMO_ODDS.get((home, away))
    if demo:
        return demo

    if not _has_odds_key(cfg):
        return None

    sport_key = cfg["leagues"][league_key].get("odds_key", "")
    events    = _fetch_odds_live(sport_key, cfg)

    for ev in events:
        h = ev.get("home_team", "")
        a = ev.get("away_team", "")
        if h.lower() in home.lower() or home.lower() in h.lower():
            if a.lower() in away.lower() or away.lower() in a.lower():
                # Parse bookmaker odds
                result: dict = {}
                for bk in ev.get("bookmakers", [])[:3]:
                    for mkt in bk.get("markets", []):
                        k = mkt["key"]
                        outcomes = mkt.get("outcomes", [])
                        if k == "h2h":
                            for o in outcomes:
                                n = o["name"].lower()
                                if "draw" in n:
                                    result["moneyline_draw"] = o["price"]
                                elif h.split()[0].lower() in n:
                                    result["moneyline_home"] = o["price"]
                                else:
                                    result["moneyline_away"] = o["price"]
                        elif k == "spreads":
                            for o in outcomes:
                                n = o["name"].lower()
                                if h.split()[0].lower() in n:
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
                                elif o["name"] == "Under":
                                    result["under_odds"] = o["price"]
                    if result:
                        break
                return result if result else None
    return None