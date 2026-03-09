"""
analytics/strength_profiler.py
─────────────────────────────────────────────────────────────────────────────
Layer 2: Konversi data mentah → profil kekuatan dan kelemahan tim.

Setiap tim mendapat 4 rating (0.0–1.0):
  attack_rating   : seberapa tajam serangan
  defense_rating  : seberapa solid pertahanan
  form_score      : momentum 5 laga terakhir
  fatigue_index   : pengurangan karena cedera pemain kunci

Output akhir adalah TeamProfile yang dipakai oleh probability engine.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TeamProfile:
    """Profil lengkap satu tim untuk satu pertandingan."""
    name:           str
    sport:          str           # "soccer" | "basketball" | "hockey"

    # Rating 0.0–1.0
    attack_rating:  float = 0.5
    defense_rating: float = 0.5
    form_score:     float = 0.5
    fatigue_index:  float = 1.0   # 1.0 = full strength, <1.0 = terganggu cedera

    # Raw stats (untuk display)
    xg_per90:       float = 0.0
    xga_per90:      float = 0.0
    pts_for_avg:    float = 0.0   # NBA/NHL: poin per laga
    pts_against_avg:float = 0.0
    win_pct:        float = 0.0
    gf_per_game:    float = 0.0   # NHL
    ga_per_game:    float = 0.0

    # Strength / weakness labels
    strengths:      list[str] = field(default_factory=list)
    weaknesses:     list[str] = field(default_factory=list)
    key_injuries:   list[str] = field(default_factory=list)

    # Overall power score (weighted composite)
    power_score:    float = 0.0


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _sigmoid_normalize(values: list[float]) -> list[float]:
    """
    Normalisasi relatif antar tim dalam satu liga.
    Seperti kurva nilai ujian — yang terbaik mendapat 1.0,
    yang paling buruk mendapat ~0.0, rata-rata mendapat 0.5.
    """
    if not values:
        return []
    mn, mx = min(values), max(values)
    if mx == mn:
        return [0.5] * len(values)
    return [(v - mn) / (mx - mn) for v in values]


# ─────────────────────────────────────────────────────────────────────────────
# Soccer profiler
# ─────────────────────────────────────────────────────────────────────────────

def profile_soccer_teams(
    team_stats: list[dict],
    injuries:   list[dict],
    cfg:        dict,
) -> dict[str, TeamProfile]:
    """
    Buat TeamProfile untuk semua tim di liga sepakbola.
    Input: data dari Understat (xG, xGA, wins, draws, loses, matches).
    """
    if not team_stats:
        return {}

    mp = cfg.get("model", {})
    injury_penalty = float(mp.get("injury_penalty_per_key", 0.08))

    # Kumpulkan metrik mentah
    xg_per90_list  = []
    xga_per90_list = []

    for t in team_stats:
        n = max(t.get("matches", 1), 1)
        xg_per90_list.append(t.get("xg", 0) / n)
        xga_per90_list.append(t.get("xga", 0) / n)

    # Normalisasi relatif antar tim
    xg_norm  = _sigmoid_normalize(xg_per90_list)
    # Untuk xGA: tim dengan xGA lebih RENDAH lebih bagus defensnya
    xga_norm = _sigmoid_normalize([-v for v in xga_per90_list])

    # Indeks cedera per tim
    key_injuries_by_team: dict[str, list[str]] = {}
    for inj in injuries:
        team = inj.get("team", "")
        if inj.get("key", False):
            key_injuries_by_team.setdefault(team, []).append(inj.get("player", ""))

    profiles: dict[str, TeamProfile] = {}

    for i, t in enumerate(team_stats):
        name    = t.get("team", "")
        n       = max(t.get("matches", 1), 1)
        wins    = t.get("wins",   0)
        draws   = t.get("draws",  0)
        loses   = t.get("loses",  0)
        total   = wins + draws + loses or 1

        xg_p90  = xg_per90_list[i]
        xga_p90 = xga_per90_list[i]

        attack  = _clamp(xg_norm[i])
        defense = _clamp(xga_norm[i])

        # Form score: rasio poin dari 5 laga terakhir yang mungkin
        form_pts = wins * 3 + draws
        form_max = total * 3
        form     = _clamp(form_pts / form_max)

        # Fatigue
        key_inj = key_injuries_by_team.get(name, [])
        fatigue = _clamp(1.0 - len(key_inj) * injury_penalty, 0.5, 1.0)

        # Power score (weighted)
        power = _clamp(
            attack * 0.35 + defense * 0.35 + form * 0.20 + fatigue * 0.10
        )

        # Label kekuatan / kelemahan
        strengths, weaknesses = _label_soccer(attack, defense, form, xg_p90, xga_p90)

        profiles[name] = TeamProfile(
            name=name, sport="soccer",
            attack_rating=round(attack, 3),
            defense_rating=round(defense, 3),
            form_score=round(form, 3),
            fatigue_index=round(fatigue, 3),
            xg_per90=round(xg_p90, 2),
            xga_per90=round(xga_p90, 2),
            win_pct=round(wins / total, 3),
            power_score=round(power, 3),
            strengths=strengths,
            weaknesses=weaknesses,
            key_injuries=key_inj,
        )

    return profiles


def _label_soccer(
    attack: float,
    defense: float,
    form: float,
    xg_p90: float,
    xga_p90: float,
) -> tuple[list[str], list[str]]:
    s, w = [], []

    if attack > 0.70:
        s.append(f"Serangan sangat tajam (xG/90: {xg_p90:.2f})")
    elif attack > 0.50:
        s.append(f"Serangan solid (xG/90: {xg_p90:.2f})")
    else:
        w.append(f"Serangan tumpul (xG/90: {xg_p90:.2f})")

    if defense > 0.70:
        s.append(f"Pertahanan sangat solid (xGA/90: {xga_p90:.2f})")
    elif defense > 0.50:
        s.append(f"Pertahanan cukup baik (xGA/90: {xga_p90:.2f})")
    else:
        w.append(f"Pertahanan rapuh (xGA/90: {xga_p90:.2f})")

    if form > 0.65:
        s.append("Form laga terakhir sangat baik")
    elif form < 0.40:
        w.append("Sedang dalam form buruk")

    return s, w


# ─────────────────────────────────────────────────────────────────────────────
# NBA profiler
# ─────────────────────────────────────────────────────────────────────────────

def profile_nba_teams(
    team_stats: list[dict],
    injuries:   list[dict],
    cfg:        dict,
) -> dict[str, TeamProfile]:
    if not team_stats:
        return {}

    mp = cfg.get("model", {})
    injury_penalty = float(mp.get("injury_penalty_per_key", 0.08))

    off_list = [t.get("pts_for",     0) / max(t.get("matches", 1), 1) for t in team_stats]
    def_list = [t.get("pts_against", 0) / max(t.get("matches", 1), 1) for t in team_stats]

    off_norm = _sigmoid_normalize(off_list)
    def_norm = _sigmoid_normalize([-v for v in def_list])

    key_inj_map: dict[str, list[str]] = {}
    for inj in injuries:
        if inj.get("key", False):
            key_inj_map.setdefault(inj["team"], []).append(inj["player"])

    profiles: dict[str, TeamProfile] = {}
    for i, t in enumerate(team_stats):
        name  = t["team"]
        n     = max(t.get("matches", 1), 1)
        wins  = t.get("wins",  0)
        loses = t.get("loses", 0)
        total = wins + loses or 1

        off   = off_list[i]
        defn  = def_list[i]

        attack  = _clamp(off_norm[i])
        defense = _clamp(def_norm[i])
        form    = _clamp(wins / total)

        key_inj = key_inj_map.get(name, [])
        fatigue = _clamp(1.0 - len(key_inj) * injury_penalty, 0.5, 1.0)
        power   = _clamp(attack * 0.35 + defense * 0.35 + form * 0.20 + fatigue * 0.10)

        s, w = _label_nba_nhl(attack, defense, form, off, defn, "pts")

        profiles[name] = TeamProfile(
            name=name, sport="basketball",
            attack_rating=round(attack, 3),
            defense_rating=round(defense, 3),
            form_score=round(form, 3),
            fatigue_index=round(fatigue, 3),
            pts_for_avg=round(off, 1),
            pts_against_avg=round(defn, 1),
            win_pct=round(wins / total, 3),
            power_score=round(power, 3),
            strengths=s, weaknesses=w,
            key_injuries=key_inj,
        )

    return profiles


# ─────────────────────────────────────────────────────────────────────────────
# NHL profiler
# ─────────────────────────────────────────────────────────────────────────────

def profile_nhl_teams(
    team_stats: list[dict],
    injuries:   list[dict],
    cfg:        dict,
) -> dict[str, TeamProfile]:
    if not team_stats:
        return {}

    mp = cfg.get("model", {})
    injury_penalty = float(mp.get("injury_penalty_per_key", 0.08))

    gf_list = [t.get("gf", 0) / max(t.get("matches", 1), 1) for t in team_stats]
    ga_list = [t.get("ga", 0) / max(t.get("matches", 1), 1) for t in team_stats]

    gf_norm = _sigmoid_normalize(gf_list)
    ga_norm = _sigmoid_normalize([-v for v in ga_list])

    key_inj_map: dict[str, list[str]] = {}
    for inj in injuries:
        if inj.get("key", False):
            key_inj_map.setdefault(inj["team"], []).append(inj["player"])

    profiles: dict[str, TeamProfile] = {}
    for i, t in enumerate(team_stats):
        name  = t["team"]
        n     = max(t.get("matches", 1), 1)
        wins  = t.get("wins", 0)
        loses = t.get("loses", 0)
        otl   = t.get("otl",  0)
        total = wins + loses + otl or 1

        gf_pg = gf_list[i]
        ga_pg = ga_list[i]

        attack  = _clamp(gf_norm[i])
        defense = _clamp(ga_norm[i])
        form    = _clamp((wins * 2 + otl) / (total * 2))

        key_inj = key_inj_map.get(name, [])
        fatigue = _clamp(1.0 - len(key_inj) * injury_penalty, 0.5, 1.0)
        power   = _clamp(attack * 0.35 + defense * 0.35 + form * 0.20 + fatigue * 0.10)

        s, w = _label_nba_nhl(attack, defense, form, gf_pg, ga_pg, "goals")

        profiles[name] = TeamProfile(
            name=name, sport="hockey",
            attack_rating=round(attack, 3),
            defense_rating=round(defense, 3),
            form_score=round(form, 3),
            fatigue_index=round(fatigue, 3),
            gf_per_game=round(gf_pg, 2),
            ga_per_game=round(ga_pg, 2),
            win_pct=round(wins / total, 3),
            power_score=round(power, 3),
            strengths=s, weaknesses=w,
            key_injuries=key_inj,
        )

    return profiles


def _label_nba_nhl(
    attack: float, defense: float, form: float,
    off_val: float, def_val: float, unit: str,
) -> tuple[list[str], list[str]]:
    s, w = [], []
    if attack > 0.70:
        s.append(f"Offense elit ({off_val:.1f} {unit}/game)")
    elif attack < 0.35:
        w.append(f"Offense lemah ({off_val:.1f} {unit}/game)")
    if defense > 0.70:
        s.append(f"Defense sangat solid ({def_val:.1f} {unit} allowed/game)")
    elif defense < 0.35:
        w.append(f"Defense bocor ({def_val:.1f} {unit} allowed/game)")
    if form > 0.65:
        s.append("Win rate tinggi musim ini")
    elif form < 0.40:
        w.append("Win rate rendah — underperforming")
    return s, w


# ─────────────────────────────────────────────────────────────────────────────
# Dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def build_profiles(
    league_key: str,
    team_stats: list[dict],
    injuries:   list[dict],
    cfg:        dict,
) -> dict[str, TeamProfile]:
    sport = cfg["leagues"][league_key]["sport"]
    if sport == "soccer":
        return profile_soccer_teams(team_stats, injuries, cfg)
    elif sport == "basketball":
        return profile_nba_teams(team_stats, injuries, cfg)
    elif sport == "hockey":
        return profile_nhl_teams(team_stats, injuries, cfg)
    return {}