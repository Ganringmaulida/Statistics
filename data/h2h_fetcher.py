"""
data/h2h_fetcher.py  ←  FILE BARU GEN 3
═══════════════════════════════════════════════════════════════════════════
MENGAPA FILE INI ADA:
  Gen 2 hanya melihat statistik musim ini (xG, win%, dst.).
  Masalahnya: ada tim yang secara historis "jinx" untuk lawan tertentu
  — contoh: Chelsea kalah dari Arsenal 7 dari 10 pertemuan terakhir
  meskipun statistik musim ini Chelsea lebih baik.

  H2H adalah faktor psikologis + taktikal yang tidak tertangkap statistik.
  Analoginya: seperti mengecek riwayat utang seseorang sebelum meminjamkan
  uang — meskipun penghasilannya sekarang bagus, pola masa lalu tetap relevan.

SUMBER DATA:
  API-Football endpoint /fixtures?h2h={teamA}-{teamB}
  → Gratis 100 req/hari, cache 7 hari (H2H tidak berubah cepat)

OUTPUT:
  H2HRecord dengan:
    - win_pct_home: proporsi home menang dari 10 pertemuan terakhir
    - avg_goals: rata-rata total gol dari 5 pertemuan terakhir
    - last_result: hasil pertemuan terakhir
    - dominance_factor: -1.0 sampai +1.0 (negatif = home sering kalah)
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_CACHE_TTL_HOURS = 168   # 7 hari — H2H tidak berubah cepat


# ─────────────────────────────────────────────────────────────────────────────
# Data structure
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class H2HRecord:
    """Rekap head-to-head dua tim."""
    home_team:          str
    away_team:          str
    matches_analyzed:   int

    # Persentase (0.0–1.0)
    home_win_pct:       float    # Berapa kali home menang
    draw_pct:           float
    away_win_pct:       float

    # Statistik gol
    avg_total_goals:    float    # Rata-rata total gol per pertemuan
    avg_home_goals:     float
    avg_away_goals:     float

    # Faktor dominansi: +1 = home selalu menang, -1 = away selalu menang
    dominance_factor:   float

    # Konteks
    last_5_results:     list[str]   # ["H","A","D","H","H"]
    last_match_date:    str
    last_match_score:   str         # "2-1"

    # Adjustment untuk probability engine
    # Seberapa besar H2H harus menggeser probabilitas dari model murni
    h2h_weight:         float = 0.15   # 15% bobot H2H vs 85% model


# ─────────────────────────────────────────────────────────────────────────────
# Demo H2H data (saat API tidak tersedia)
# ─────────────────────────────────────────────────────────────────────────────

_DEMO_H2H = {
    ("Arsenal", "Chelsea"): H2HRecord(
        home_team="Arsenal", away_team="Chelsea", matches_analyzed=10,
        home_win_pct=0.50, draw_pct=0.20, away_win_pct=0.30,
        avg_total_goals=2.8, avg_home_goals=1.6, avg_away_goals=1.2,
        dominance_factor=0.20, last_5_results=["H","H","D","A","H"],
        last_match_date="2024-09-22", last_match_score="1-1",
    ),
    ("Liverpool", "Manchester City"): H2HRecord(
        home_team="Liverpool", away_team="Manchester City", matches_analyzed=10,
        home_win_pct=0.40, draw_pct=0.30, away_win_pct=0.30,
        avg_total_goals=3.2, avg_home_goals=1.8, avg_away_goals=1.4,
        dominance_factor=0.10, last_5_results=["D","H","A","H","D"],
        last_match_date="2024-11-25", last_match_score="2-0",
    ),
    ("Arsenal", "Real Madrid"): H2HRecord(
        home_team="Arsenal", away_team="Real Madrid", matches_analyzed=8,
        home_win_pct=0.25, draw_pct=0.25, away_win_pct=0.50,
        avg_total_goals=2.5, avg_home_goals=1.0, avg_away_goals=1.5,
        dominance_factor=-0.25, last_5_results=["A","D","A","H","A"],
        last_match_date="2024-04-10", last_match_score="0-1",
    ),
    ("Boston Celtics", "Oklahoma City Thunder"): H2HRecord(
        home_team="Boston Celtics", away_team="Oklahoma City Thunder",
        matches_analyzed=6, home_win_pct=0.67, draw_pct=0.0, away_win_pct=0.33,
        avg_total_goals=224.5, avg_home_goals=114.0, avg_away_goals=110.5,
        dominance_factor=0.33, last_5_results=["H","H","A","H","H"],
        last_match_date="2025-01-18", last_match_score="112-108",
    ),
    ("Washington Capitals", "Winnipeg Jets"): H2HRecord(
        home_team="Washington Capitals", away_team="Winnipeg Jets",
        matches_analyzed=8, home_win_pct=0.38, draw_pct=0.0, away_win_pct=0.62,
        avg_total_goals=6.4, avg_home_goals=3.0, avg_away_goals=3.4,
        dominance_factor=-0.24, last_5_results=["A","A","H","A","A"],
        last_match_date="2025-02-01", last_match_score="3-4",
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Cache
# ─────────────────────────────────────────────────────────────────────────────

def _h2h_cache_key(home: str, away: str) -> str:
    return f"h2h_{home.replace(' ','_')}_{away.replace(' ','_')}".lower()

def _read_h2h_cache(cache_dir: str, key: str) -> Optional[dict]:
    p = Path(cache_dir) / f"{key}.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if (time.time() - d["ts"]) / 3600 < _CACHE_TTL_HOURS:
            return d["v"]
    except Exception:
        pass
    return None

def _write_h2h_cache(cache_dir: str, key: str, value: dict) -> None:
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    (Path(cache_dir) / f"{key}.json").write_text(
        json.dumps({"ts": time.time(), "v": value}), encoding="utf-8"
    )


# ─────────────────────────────────────────────────────────────────────────────
# API-Football H2H fetch
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_team_id(team_name: str, api_key: str) -> Optional[int]:
    """Cari team ID dari nama tim."""
    try:
        r = requests.get(
            "https://v3.football.api-sports.io/teams",
            params={"search": team_name},
            headers={"x-rapidapi-key": api_key,
                     "x-rapidapi-host": "v3.football.api-sports.io"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json().get("response", [])
        if data:
            return data[0]["team"]["id"]
    except Exception as exc:
        logger.warning(f"Team ID lookup failed [{team_name}]: {exc}")
    return None


def _fetch_h2h_live(
    home: str, away: str, api_key: str, last_n: int = 10
) -> Optional[H2HRecord]:
    """
    Fetch H2H dari API-Football.
    Membutuhkan 2 API calls (team ID lookup x2) + 1 H2H call = 3 calls total.
    Di-cache 7 hari untuk efisiensi.
    """
    home_id = _fetch_team_id(home, api_key)
    away_id = _fetch_team_id(away, api_key)
    if not home_id or not away_id:
        return None

    try:
        r = requests.get(
            "https://v3.football.api-sports.io/fixtures",
            params={"h2h": f"{home_id}-{away_id}", "last": last_n},
            headers={"x-rapidapi-key": api_key,
                     "x-rapidapi-host": "v3.football.api-sports.io"},
            timeout=15,
        )
        r.raise_for_status()
        fixtures = r.json().get("response", [])
    except Exception as exc:
        logger.warning(f"H2H fetch failed [{home} vs {away}]: {exc}")
        return None

    if not fixtures:
        return None

    return _parse_h2h_fixtures(fixtures, home, away)


def _parse_h2h_fixtures(
    fixtures: list[dict],
    home_team: str,
    away_team: str,
) -> H2HRecord:
    """Parse raw fixture list → H2HRecord."""
    h_wins = d_draws = a_wins = 0
    total_goals_list, h_goals_list, a_goals_list = [], [], []
    results = []
    last_date = ""
    last_score = ""

    for f in fixtures:
        teams  = f.get("teams", {})
        goals  = f.get("goals", {})
        fix    = f.get("fixture", {})

        f_home = teams.get("home", {}).get("name", "")
        f_away = teams.get("away", {}).get("name", "")
        g_home = goals.get("home") or 0
        g_away = goals.get("away") or 0

        # Tentukan apakah home_team bermain sebagai home atau away
        if home_team.lower() in f_home.lower():
            actual_h = g_home
            actual_a = g_away
            if g_home > g_away:   h_wins += 1; results.append("H")
            elif g_home == g_away: d_draws += 1; results.append("D")
            else:                  a_wins += 1; results.append("A")
        else:
            actual_h = g_away
            actual_a = g_home
            if g_away > g_home:   h_wins += 1; results.append("H")
            elif g_away == g_home: d_draws += 1; results.append("D")
            else:                  a_wins += 1; results.append("A")

        total_goals_list.append(actual_h + actual_a)
        h_goals_list.append(actual_h)
        a_goals_list.append(actual_a)

        date = fix.get("date", "")[:10]
        if date > last_date:
            last_date  = date
            last_score = f"{actual_h}-{actual_a}"

    n = len(fixtures) or 1
    dom = (h_wins - a_wins) / n

    return H2HRecord(
        home_team=home_team, away_team=away_team, matches_analyzed=n,
        home_win_pct=round(h_wins / n, 3),
        draw_pct=round(d_draws / n, 3),
        away_win_pct=round(a_wins / n, 3),
        avg_total_goals=round(sum(total_goals_list) / n, 2),
        avg_home_goals=round(sum(h_goals_list) / n, 2),
        avg_away_goals=round(sum(a_goals_list) / n, 2),
        dominance_factor=round(dom, 3),
        last_5_results=results[-5:],
        last_match_date=last_date,
        last_match_score=last_score,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def get_h2h(
    home: str,
    away: str,
    cfg: dict,
) -> Optional[H2HRecord]:
    """
    Ambil H2H record untuk dua tim.
    Prioritas: demo data → cache → live API.
    """
    # 1. Demo data
    demo = _DEMO_H2H.get((home, away)) or _DEMO_H2H.get((away, home))
    if demo:
        return demo

    # 2. Cache
    cache_dir = cfg.get("cache", {}).get("dir", "cache")
    ckey      = _h2h_cache_key(home, away)
    cached    = _read_h2h_cache(cache_dir, ckey)
    if cached:
        return H2HRecord(**cached)

    # 3. Live API
    api_key = cfg.get("api_football", {}).get("api_key", "")
    if api_key and api_key != "YOUR_API_FOOTBALL_KEY_HERE":
        record = _fetch_h2h_live(home, away, api_key)
        if record:
            _write_h2h_cache(cache_dir, ckey, record.__dict__)
            return record

    logger.info(f"No H2H data available for {home} vs {away}")
    return None


def apply_h2h_adjustment(
    p_home: float,
    p_draw: float,
    p_away: float,
    h2h: Optional[H2HRecord],
) -> tuple[float, float, float]:
    """
    Sesuaikan probabilitas model dengan faktor H2H.

    Formula:
      p_adjusted = p_model × (1 - w) + p_h2h × w
      di mana w = h2h.h2h_weight (default 15%)

    Jika tidak ada H2H data, kembalikan probabilitas tanpa perubahan.
    """
    if not h2h or h2h.matches_analyzed < 4:
        return p_home, p_draw, p_away

    w = h2h.h2h_weight

    H2H probabilities
    h2h_total = h2h.home_win_pct + h2h.draw_pct + h2h.away_win_pct
    if h2h_total <= 0:
        return p_home, p_draw, p_away

    h2h_ph = h2h.home_win_pct / h2h_total
    h2h_pd = h2h.draw_pct     / h2h_total
    h2h_pa = h2h.away_win_pct / h2h_total

    # Weighted blend
    new_ph = p_home * (1 - w) + h2h_ph * w
    new_pd = p_draw * (1 - w) + h2h_pd * w
    new_pa = p_away * (1 - w) + h2h_pa * w

    # Re-normalize (floating point)
    total  = new_ph + new_pd + new_pa
    return round(new_ph/total, 4), round(new_pd/total, 4), round(new_pa/total, 4)