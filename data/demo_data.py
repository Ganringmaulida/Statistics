"""
data/demo_data.py
Data demo realistis untuk semua liga — dipakai saat API key belum diisi.
Angka-angka didasarkan pada statistik musim 2024 aktual.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone


def _days_ahead(n: int) -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=n)
    return dt.strftime("%Y-%m-%d %H:%M")


DEMO_TEAM_STATS = {
    "epl": [
        {"team": "Liverpool",         "xg": 62.4, "xga": 28.1, "scored": 68, "missed": 26, "matches": 32, "wins": 23, "draws": 5,  "loses": 4,  "pts": 74},
        {"team": "Arsenal",           "xg": 57.8, "xga": 27.4, "scored": 61, "missed": 25, "matches": 32, "wins": 21, "draws": 7,  "loses": 4,  "pts": 70},
        {"team": "Chelsea",           "xg": 51.2, "xga": 35.6, "scored": 54, "missed": 38, "matches": 32, "wins": 17, "draws": 8,  "loses": 7,  "pts": 59},
        {"team": "Manchester City",   "xg": 55.3, "xga": 30.2, "scored": 58, "missed": 33, "matches": 32, "wins": 18, "draws": 6,  "loses": 8,  "pts": 60},
        {"team": "Aston Villa",       "xg": 48.7, "xga": 38.1, "scored": 50, "missed": 40, "matches": 32, "wins": 15, "draws": 9,  "loses": 8,  "pts": 54},
        {"team": "Newcastle",         "xg": 46.2, "xga": 36.8, "scored": 48, "missed": 38, "matches": 32, "wins": 14, "draws": 8,  "loses": 10, "pts": 50},
        {"team": "Tottenham",         "xg": 44.1, "xga": 42.3, "scored": 46, "missed": 44, "matches": 32, "wins": 12, "draws": 7,  "loses": 13, "pts": 43},
        {"team": "Manchester United", "xg": 38.9, "xga": 45.7, "scored": 35, "missed": 48, "matches": 32, "wins": 10, "draws": 6,  "loses": 16, "pts": 36},
    ],
    "ucl": [
        {"team": "Real Madrid",      "xg": 22.1, "xga": 10.4, "scored": 24, "missed": 9,  "matches": 10, "wins": 8, "draws": 1, "loses": 1, "pts": 25},
        {"team": "Arsenal",          "xg": 19.8, "xga": 11.2, "scored": 21, "missed": 11, "matches": 10, "wins": 7, "draws": 2, "loses": 1, "pts": 23},
        {"team": "Bayern Munich",    "xg": 21.3, "xga": 12.8, "scored": 23, "missed": 13, "matches": 10, "wins": 7, "draws": 1, "loses": 2, "pts": 22},
        {"team": "Atletico Madrid",  "xg": 14.2, "xga": 10.1, "scored": 15, "missed": 10, "matches": 10, "wins": 6, "draws": 3, "loses": 1, "pts": 21},
        {"team": "PSG",              "xg": 17.6, "xga": 13.4, "scored": 19, "missed": 14, "matches": 10, "wins": 5, "draws": 2, "loses": 3, "pts": 17},
        {"team": "Inter Milan",      "xg": 15.8, "xga": 11.9, "scored": 17, "missed": 12, "matches": 10, "wins": 5, "draws": 2, "loses": 3, "pts": 17},
    ],
    "nba": [
        {"team": "Oklahoma City Thunder", "pts_for": 120.4, "pts_against": 108.2, "wins": 52, "loses": 15, "matches": 67},
        {"team": "Cleveland Cavaliers",   "pts_for": 118.7, "pts_against": 107.9, "wins": 51, "loses": 16, "matches": 67},
        {"team": "Boston Celtics",        "pts_for": 119.2, "pts_against": 109.1, "wins": 50, "loses": 17, "matches": 67},
        {"team": "Houston Rockets",       "pts_for": 112.8, "pts_against": 108.4, "wins": 43, "loses": 24, "matches": 67},
        {"team": "Golden State Warriors", "pts_for": 114.1, "pts_against": 111.8, "wins": 36, "loses": 31, "matches": 67},
        {"team": "LA Lakers",             "pts_for": 113.6, "pts_against": 112.4, "wins": 33, "loses": 34, "matches": 67},
        {"team": "Memphis Grizzlies",     "pts_for": 109.2, "pts_against": 115.7, "wins": 19, "loses": 48, "matches": 67},
    ],
    "nhl": [
        {"team": "Washington Capitals",  "gf": 214, "ga": 158, "wins": 43, "loses": 19, "otl": 7,  "pts": 93, "matches": 69},
        {"team": "Winnipeg Jets",        "gf": 228, "ga": 172, "wins": 43, "loses": 20, "otl": 6,  "pts": 92, "matches": 69},
        {"team": "Vegas Golden Knights", "gf": 218, "ga": 178, "wins": 39, "loses": 21, "otl": 9,  "pts": 87, "matches": 69},
        {"team": "Carolina Hurricanes",  "gf": 206, "ga": 177, "wins": 38, "loses": 22, "otl": 9,  "pts": 85, "matches": 69},
        {"team": "Colorado Avalanche",   "gf": 221, "ga": 191, "wins": 37, "loses": 23, "otl": 9,  "pts": 83, "matches": 69},
        {"team": "Toronto Maple Leafs",  "gf": 209, "ga": 195, "wins": 36, "loses": 26, "otl": 7,  "pts": 79, "matches": 69},
    ],
}

DEMO_INJURIES = {
    "epl": [
        {"team": "Arsenal",           "player": "Bukayo Saka",      "type": "Hamstring",   "key": True},
        {"team": "Manchester City",   "player": "Rodri",            "type": "Knee (long)", "key": True},
        {"team": "Manchester United", "player": "Rasmus Hojlund",   "type": "Thigh",       "key": True},
        {"team": "Chelsea",           "player": "Wesley Fofana",    "type": "Knee",        "key": False},
        {"team": "Tottenham",         "player": "Richarlison",      "type": "Calf",        "key": False},
    ],
    "ucl": [
        {"team": "Real Madrid",  "player": "Dani Carvajal", "type": "Knee",      "key": True},
        {"team": "Arsenal",      "player": "Bukayo Saka",   "type": "Hamstring", "key": True},
        {"team": "PSG",          "player": "Lucas Hernandez","type": "Thigh",    "key": False},
    ],
    "nba": [
        {"team": "Boston Celtics",        "player": "Jaylen Brown",   "type": "Adductor", "key": True},
        {"team": "Golden State Warriors", "player": "Stephen Curry",  "type": "Ankle",    "key": True},
        {"team": "LA Lakers",             "player": "Anthony Davis",  "type": "Foot",     "key": True},
    ],
    "nhl": [
        {"team": "Colorado Avalanche",  "player": "Nathan MacKinnon", "type": "Upper body", "key": True},
        {"team": "Toronto Maple Leafs", "player": "Auston Matthews",  "type": "Wrist",      "key": True},
    ],
}

DEMO_FIXTURES = {
    "epl": [
        {"home": "Arsenal",         "away": "Chelsea",           "date": _days_ahead(1), "venue": "Emirates Stadium"},
        {"home": "Liverpool",       "away": "Manchester City",   "date": _days_ahead(2), "venue": "Anfield"},
        {"home": "Tottenham",       "away": "Manchester United", "date": _days_ahead(3), "venue": "Tottenham Hotspur Stadium"},
        {"home": "Newcastle",       "away": "Aston Villa",       "date": _days_ahead(5), "venue": "St. James' Park"},
    ],
    "ucl": [
        {"home": "Arsenal",         "away": "Real Madrid",       "date": _days_ahead(2), "venue": "Emirates Stadium"},
        {"home": "Bayern Munich",   "away": "PSG",               "date": _days_ahead(2), "venue": "Allianz Arena"},
        {"home": "Inter Milan",     "away": "Atletico Madrid",   "date": _days_ahead(4), "venue": "San Siro"},
    ],
    "nba": [
        {"home": "Boston Celtics",        "away": "Oklahoma City Thunder", "date": _days_ahead(1), "venue": "TD Garden"},
        {"home": "Golden State Warriors", "away": "LA Lakers",             "date": _days_ahead(2), "venue": "Chase Center"},
        {"home": "Cleveland Cavaliers",   "away": "Houston Rockets",       "date": _days_ahead(3), "venue": "Rocket Mortgage FieldHouse"},
    ],
    "nhl": [
        {"home": "Washington Capitals",  "away": "Winnipeg Jets",       "date": _days_ahead(1), "venue": "Capital One Arena"},
        {"home": "Colorado Avalanche",   "away": "Vegas Golden Knights", "date": _days_ahead(2), "venue": "Ball Arena"},
        {"home": "Toronto Maple Leafs",  "away": "Carolina Hurricanes",  "date": _days_ahead(4), "venue": "Scotiabank Arena"},
    ],
}

DEMO_ODDS = {
    ("Arsenal", "Chelsea"): {
        "moneyline_home": -175, "moneyline_draw": +280, "moneyline_away": +420,
        "spread_home": -0.5, "spread_home_odds": -115,
        "spread_away": +0.5, "spread_away_odds": -105,
        "total_line": 2.5, "over_odds": -130, "under_odds": +110,
    },
    ("Liverpool", "Manchester City"): {
        "moneyline_home": -140, "moneyline_draw": +265, "moneyline_away": +360,
        "spread_home": -0.5, "spread_home_odds": -105,
        "spread_away": +0.5, "spread_away_odds": -115,
        "total_line": 3.0, "over_odds": -110, "under_odds": -110,
    },
    ("Arsenal", "Real Madrid"): {
        "moneyline_home": +115, "moneyline_draw": +230, "moneyline_away": +230,
        "spread_home": +0.0, "spread_home_odds": -110,
        "spread_away": +0.0, "spread_away_odds": -110,
        "total_line": 2.5, "over_odds": -105, "under_odds": -115,
    },
    ("Boston Celtics", "Oklahoma City Thunder"): {
        "moneyline_home": -130, "moneyline_draw": None, "moneyline_away": +110,
        "spread_home": -2.5, "spread_home_odds": -110,
        "spread_away": +2.5, "spread_away_odds": -110,
        "total_line": 226.5, "over_odds": -110, "under_odds": -110,
    },
    ("Golden State Warriors", "LA Lakers"): {
        "moneyline_home": -165, "moneyline_draw": None, "moneyline_away": +140,
        "spread_home": -3.5, "spread_home_odds": -110,
        "spread_away": +3.5, "spread_away_odds": -110,
        "total_line": 222.0, "over_odds": -115, "under_odds": -105,
    },
    ("Washington Capitals", "Winnipeg Jets"): {
        "moneyline_home": +120, "moneyline_draw": None, "moneyline_away": -140,
        "spread_home": +1.5, "spread_home_odds": -175,
        "spread_away": -1.5, "spread_away_odds": +150,
        "total_line": 6.0, "over_odds": -110, "under_odds": -110,
    },
    ("Colorado Avalanche", "Vegas Golden Knights"): {
        "moneyline_home": -105, "moneyline_draw": None, "moneyline_away": -115,
        "spread_home": +1.5, "spread_home_odds": -210,
        "spread_away": -1.5, "spread_away_odds": +175,
        "total_line": 6.5, "over_odds": -120, "under_odds": +100,
    },
}