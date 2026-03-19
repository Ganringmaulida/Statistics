"""
analytics/elo_model.py  [Gen 3]
═══════════════════════════════════════════════════════════════════════════
ELO Rating System — model historis lintas musim untuk semua sport.

Analoginya: seperti sistem ranking catur FIDE. Setiap pemain (tim)
punya skor rating. Menang lawan tim lebih kuat → rating naik banyak.
Menang lawan tim lebih lemah → rating naik sedikit. Kalah dari tim
kuat → rating turun sedikit. Ini mencerminkan "siapa yang susah
dikalahkan" bukan hanya "siapa yang paling banyak menang hari ini."

K-factor per sport (seberapa cepat rating berubah):
  Soccer  : K=32  (banyak faktor eksternal, rating perlu responsif)
  NBA     : K=20  (82 games/season, sample besar → perlu stabil)
  NHL     : K=24  (playoff upset lebih sering → perlu sedikit responsif)

Home advantage ELO:
  Soccer : +65 pts
  NBA    : +100 pts
  NHL    : +50 pts

Storage: storage/elo_ratings.json
  { "EPL": { "Arsenal": 1650, ... }, "NBA": { ... }, ... }

Fungsi utama:
  load_ratings(cfg)                  → dict semua rating
  get_matchup(home, away, league, sport, cfg) → EloMatchup
  update_ratings(...)                → update setelah pertandingan selesai
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_RATINGS_PATH = Path("storage/elo_ratings.json")
_DEFAULT_RATING = 1500.0

# K-factor dan home advantage per sport
_ELO_CONFIG: dict[str, dict] = {
    "soccer":     {"K": 32, "home_adv": 65,  "draw_threshold": 0.06},
    "basketball": {"K": 20, "home_adv": 100, "draw_threshold": 0.0},
    "hockey":     {"K": 24, "home_adv": 50,  "draw_threshold": 0.04},
}


@dataclass
class EloMatchup:
    """Hasil kalkulasi ELO untuk satu head-to-head."""
    home:          str
    away:          str
    rating_home:   float
    rating_away:   float
    diff:          float          # home - away (setelah home_adv)

    p_home_elo:    float          # probabilitas menang home menurut ELO
    p_draw_elo:    float          # 0.0 untuk NBA
    p_away_elo:    float

    confidence:    str            # "HIGH" | "MEDIUM" | "LOW"
    home_favored:  bool


# ─────────────────────────────────────────────────────────────────────────────
# Storage
# ─────────────────────────────────────────────────────────────────────────────

def load_ratings(cfg: Optional[dict] = None) -> dict[str, dict[str, float]]:
    """Muat semua ELO ratings. Return {} jika file tidak ada."""
    path = Path(cfg.get("storage", {}).get("elo_path", str(_RATINGS_PATH))) if cfg else _RATINGS_PATH
    if not path.exists():
        return _default_ratings()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"elo_model load error: {exc}")
        return _default_ratings()


def save_ratings(ratings: dict[str, dict[str, float]], cfg: Optional[dict] = None) -> None:
    path = Path(cfg.get("storage", {}).get("elo_path", str(_RATINGS_PATH))) if cfg else _RATINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ratings, indent=2, ensure_ascii=False), encoding="utf-8")


def _default_ratings() -> dict[str, dict[str, float]]:
    """Seed rating awal untuk semua liga yang didukung."""
    return {
        "EPL": {
            "Manchester City": 1780, "Arsenal": 1720, "Liverpool": 1700,
            "Chelsea": 1640, "Manchester United": 1620, "Tottenham": 1610,
            "Newcastle United": 1590, "Aston Villa": 1575, "Brighton": 1560,
            "West Ham United": 1545, "Fulham": 1525, "Brentford": 1520,
            "Crystal Palace": 1505, "Wolverhampton": 1500, "Everton": 1490,
            "Nottingham Forest": 1485, "AFC Bournemouth": 1480, "Burnley": 1460,
            "Sheffield United": 1450, "Luton Town": 1440,
        },
        "UCL": {
            "Real Madrid": 1900, "Manchester City": 1860, "Bayern Munich": 1840,
            "Arsenal": 1800, "Liverpool": 1790, "PSG": 1780,
            "Inter Milan": 1760, "Atletico Madrid": 1745, "Barcelona": 1740,
            "Borussia Dortmund": 1720, "Napoli": 1700, "AC Milan": 1695,
            "Juventus": 1680, "RB Leipzig": 1665, "Porto": 1650,
            "Benfica": 1640,
        },
        "NBA": {
            "Boston Celtics": 1780, "Oklahoma City Thunder": 1760,
            "Denver Nuggets": 1755, "Minnesota Timberwolves": 1740,
            "Cleveland Cavaliers": 1730, "New York Knicks": 1715,
            "LA Clippers": 1700, "Orlando Magic": 1695,
            "Milwaukee Bucks": 1690, "Golden State Warriors": 1680,
            "Phoenix Suns": 1670, "Sacramento Kings": 1660,
            "Indiana Pacers": 1655, "Dallas Mavericks": 1650,
            "Miami Heat": 1645, "Los Angeles Lakers": 1640,
            "Philadelphia 76ers": 1630, "New Orleans Pelicans": 1625,
            "Houston Rockets": 1620, "Chicago Bulls": 1580,
            "Brooklyn Nets": 1540, "Atlanta Hawks": 1535,
            "Utah Jazz": 1510, "Portland Trail Blazers": 1505,
            "San Antonio Spurs": 1480, "Memphis Grizzlies": 1470,
            "Charlotte Hornets": 1460, "Washington Wizards": 1445,
            "Toronto Raptors": 1440, "Detroit Pistons": 1420,
        },
        "NHL": {
            "Florida Panthers": 1740, "Colorado Avalanche": 1730,
            "Vegas Golden Knights": 1720, "Boston Bruins": 1715,
            "Carolina Hurricanes": 1705, "Toronto Maple Leafs": 1695,
            "New York Rangers": 1685, "Dallas Stars": 1680,
            "Edmonton Oilers": 1675, "Tampa Bay Lightning": 1665,
            "New Jersey Devils": 1655, "Pittsburgh Penguins": 1640,
            "Seattle Kraken": 1625, "Minnesota Wild": 1620,
            "Calgary Flames": 1610, "Nashville Predators": 1605,
            "Winnipeg Jets": 1600, "New York Islanders": 1590,
            "Ottawa Senators": 1580, "St. Louis Blues": 1570,
            "Vancouver Canucks": 1565, "Los Angeles Kings": 1555,
            "Philadelphia Flyers": 1540, "Washington Capitals": 1530,
            "Anaheim Ducks": 1500, "Detroit Red Wings": 1495,
            "Buffalo Sabres": 1490, "Montreal Canadiens": 1480,
            "Chicago Blackhawks": 1450, "Utah Hockey Club": 1460,
            "San Jose Sharks": 1420, "Columbus Blue Jackets": 1415,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Core ELO math
# ─────────────────────────────────────────────────────────────────────────────

def _expected_score(r_a: float, r_b: float) -> float:
    """E(A beats B) berdasarkan rating ELO standar."""
    return 1.0 / (1.0 + 10.0 ** ((r_b - r_a) / 400.0))


def _elo_to_probs(
    r_home: float, r_away: float, home_adv: float, draw_threshold: float
) -> tuple[float, float, float]:
    """
    Konversi selisih ELO + home advantage → (p_home, p_draw, p_away).

    Untuk sport tanpa draw (NBA): p_draw = 0.0, probabilitas renormalisasi.
    Untuk soccer/hockey: zona di sekitar 50/50 sebagian dialokasikan ke draw.
    """
    e_home = _expected_score(r_home + home_adv, r_away)

    if draw_threshold == 0.0:
        return round(e_home, 4), 0.0, round(1.0 - e_home, 4)

    # Alokasi draw berdasarkan seberapa dekat ke keseimbangan
    centrality = 1.0 - abs(e_home - 0.5) * 2
    p_draw = max(0.05, min(0.35, draw_threshold * 5 * centrality))
    rem    = 1.0 - p_draw
    p_home = e_home * rem
    p_away = (1.0 - e_home) * rem
    total  = p_home + p_draw + p_away
    return round(p_home / total, 4), round(p_draw / total, 4), round(p_away / total, 4)


def _confidence(diff: float) -> str:
    """Konversi selisih rating → confidence label."""
    if abs(diff) >= 150:
        return "HIGH"
    elif abs(diff) >= 75:
        return "MEDIUM"
    return "LOW"


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def get_matchup(
    home: str,
    away: str,
    league_key: str,
    sport: str,
    cfg: Optional[dict] = None,
) -> Optional[EloMatchup]:
    """
    Hitung ELO matchup untuk satu pertandingan.
    Return None jika salah satu tim tidak dikenal.
    Tim baru akan di-seed dengan DEFAULT_RATING otomatis.
    """
    elo_cfg = _ELO_CONFIG.get(sport, _ELO_CONFIG["soccer"])
    ratings = load_ratings(cfg)
    league_ratings = ratings.get(league_key.upper(), ratings.get(league_key, {}))

    r_home = _fuzzy_get(league_ratings, home)
    r_away = _fuzzy_get(league_ratings, away)

    if r_home is None:
        logger.debug(f"elo_model: seeding new team {home} @ {_DEFAULT_RATING}")
        r_home = _DEFAULT_RATING
    if r_away is None:
        logger.debug(f"elo_model: seeding new team {away} @ {_DEFAULT_RATING}")
        r_away = _DEFAULT_RATING

    home_adv = elo_cfg["home_adv"]
    diff     = (r_home + home_adv) - r_away

    ph, pd, pa = _elo_to_probs(r_home, r_away, home_adv, elo_cfg["draw_threshold"])

    return EloMatchup(
        home         = home,
        away         = away,
        rating_home  = r_home,
        rating_away  = r_away,
        diff         = round(diff, 1),
        p_home_elo   = ph,
        p_draw_elo   = pd,
        p_away_elo   = pa,
        confidence   = _confidence(diff),
        home_favored = diff > 0,
    )


def update_ratings(
    home: str,
    away: str,
    league_key: str,
    sport: str,
    home_score: int,
    away_score: int,
    cfg: Optional[dict] = None,
) -> tuple[float, float]:
    """
    Update ELO ratings setelah pertandingan selesai.
    Returns: (delta_home, delta_away) — perubahan rating masing-masing.
    """
    elo_cfg = _ELO_CONFIG.get(sport, _ELO_CONFIG["soccer"])
    K       = elo_cfg["K"]

    ratings = load_ratings(cfg)
    lk      = league_key.upper()
    if lk not in ratings:
        ratings[lk] = {}

    r_home = ratings[lk].get(home, _DEFAULT_RATING)
    r_away = ratings[lk].get(away, _DEFAULT_RATING)

    home_adv   = elo_cfg["home_adv"]
    e_home     = _expected_score(r_home + home_adv, r_away)

    # Actual score: 1.0 = home win, 0.5 = draw, 0.0 = away win
    if home_score > away_score:
        s_home = 1.0
    elif home_score == away_score:
        s_home = 0.5
    else:
        s_home = 0.0

    delta = K * (s_home - e_home)
    ratings[lk][home] = round(r_home + delta, 1)
    ratings[lk][away] = round(r_away - delta, 1)

    save_ratings(ratings, cfg)
    logger.debug(f"ELO update: {home} {r_home:.0f}→{ratings[lk][home]:.0f}  "
                 f"{away} {r_away:.0f}→{ratings[lk][away]:.0f}")
    return round(delta, 2), round(-delta, 2)


def _fuzzy_get(ratings: dict[str, float], name: str) -> Optional[float]:
    """Cari rating dengan toleransi perbedaan nama tim."""
    if name in ratings:
        return ratings[name]
    name_l = name.lower()
    for k, v in ratings.items():
        if k.lower() == name_l or name_l in k.lower() or k.lower() in name_l:
            return v
    # Cek kata pertama (nama kota)
    name_word = name_l.split()[0] if name_l.split() else ""
    for k, v in ratings.items():
        if name_word and k.lower().split()[0] == name_word:
            return v
    return None