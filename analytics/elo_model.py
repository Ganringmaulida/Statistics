"""
analytics/elo_model.py  ←  FILE BARU GEN 3
═══════════════════════════════════════════════════════════════════════════
MENGAPA FILE INI ADA:
  Gen 2 menghitung probabilitas murni dari statistik musim ini (xG, win%).
  Masalahnya: statistik musim tidak sensitif terhadap momentum terbaru.

  ELO adalah sistem rating yang:
  1. Update setelah SETIAP pertandingan (bukan per musim)
  2. Menghargai kemenangan atas lawan kuat lebih dari lawan lemah
  3. Akumulasi lintas musim — tim yang baik selama bertahun-tahun
     punya rating lebih tinggi meski musim ini sedang turun

  Analoginya: seperti ranking ATP tenis. Federer tetap punya rating tinggi
  bahkan saat sedang cedera, karena akumulasi kemenangan masa lalu masih
  dihitung. Win% musim ini tidak punya "memori" seperti ini.

IMPLEMENTASI:
  - Rating awal semua tim: 1500 (konvensi standar)
  - K-factor: 32 untuk soccer, 20 untuk NBA/NHL (lebih stabil)
  - Home advantage: +100 rating points dalam kalkulasi expected score
  - Persistence: rating disimpan di storage/elo_ratings.json

CARA ELO MENINGKATKAN AKURASI:
  Model Poisson kita menggunakan xG/90 dan form.
  ELO menambahkan dimensi ketiga: "siapa yang lebih kuat secara kumulatif".
  Saat keduanya setuju → confidence naik. Saat berbeda → hati-hati.
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ELO_STORAGE = Path("storage/elo_ratings.json")
DEFAULT_RATING = 1500.0
HOME_ADVANTAGE = 100.0   # ELO points equivalent untuk home advantage


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EloRating:
    """Rating ELO satu tim."""
    team:           str
    league:         str
    rating:         float = DEFAULT_RATING
    matches_played: int   = 0
    last_updated:   str   = ""

    # History untuk trend analysis
    rating_history: list[float] = field(default_factory=list)


@dataclass
class EloMatchup:
    """Hasil kalkulasi ELO untuk satu pertandingan."""
    home_team:       str
    away_team:       str
    home_rating:     float
    away_rating:     float
    home_rating_adj: float    # Dengan home advantage
    p_home_elo:      float    # P(home win) dari ELO
    p_draw_elo:      float    # Estimasi dari rating gap
    p_away_elo:      float
    rating_gap:      float    # home - away (positif = home unggul)
    confidence:      str      # "HIGH" | "MEDIUM" | "LOW" berdasarkan matches played


# ─────────────────────────────────────────────────────────────────────────────
# ELO Ratings Store
# ─────────────────────────────────────────────────────────────────────────────

class EloStore:
    """
    Persistent storage untuk semua rating ELO.
    Membaca dan menulis ke storage/elo_ratings.json.
    """

    def __init__(self, path: Path = ELO_STORAGE):
        self.path    = path
        self.ratings: dict[str, EloRating] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            logger.info("ELO store: no file found, starting fresh")
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for key, data in raw.items():
                # rating_history mungkin tidak ada di data lama
                if "rating_history" not in data:
                    data["rating_history"] = []
                self.ratings[key] = EloRating(**data)
            logger.info(f"ELO store loaded: {len(self.ratings)} teams")
        except Exception as exc:
            logger.warning(f"ELO store load failed: {exc}")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {k: asdict(v) for k, v in self.ratings.items()},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )

    def get(self, team: str, league: str) -> EloRating:
        key = f"{league}:{team}"
        if key not in self.ratings:
            self.ratings[key] = EloRating(team=team, league=league)
        return self.ratings[key]

    def update(self, team: str, league: str, new_rating: float, date: str = "") -> None:
        r = self.get(team, league)
        r.rating_history.append(round(r.rating, 1))
        if len(r.rating_history) > 50:     # simpan 50 history terakhir
            r.rating_history = r.rating_history[-50:]
        r.rating         = round(new_rating, 2)
        r.matches_played += 1
        r.last_updated   = date

    def all_for_league(self, league: str) -> list[EloRating]:
        return [r for r in self.ratings.values() if r.league == league]


# Global store (singleton pattern)
_store: Optional[EloStore] = None

def get_store() -> EloStore:
    global _store
    if _store is None:
        _store = EloStore()
    return _store


# ─────────────────────────────────────────────────────────────────────────────
# ELO Calculation Engine
# ─────────────────────────────────────────────────────────────────────────────

def _k_factor(matches_played: int, sport: str) -> float:
    """
    K-factor menentukan seberapa cepat rating berubah per pertandingan.

    Tinggi di awal (tim baru, rating belum akurat) → turun saat banyak data.
    Seperti margin of error dalam statistik: semakin banyak sample, semakin kecil.
    """
    if sport == "soccer":
        if matches_played < 20: return 40.0
        if matches_played < 50: return 32.0
        return 24.0
    else:
        # NBA/NHL: lebih banyak pertandingan per musim → K lebih kecil
        if matches_played < 30: return 24.0
        return 16.0


def _expected_score(rating_a: float, rating_b: float) -> float:
    """
    Expected score untuk tim A berdasarkan rating gap.
    Formula standar ELO: E_A = 1 / (1 + 10^((R_B - R_A)/400))
    Output: 0.0–1.0 (bukan probabilitas menang, tapi expected "score")
    """
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def _elo_to_win_prob(
    home_rating: float,
    away_rating: float,
    sport: str,
) -> tuple[float, float, float]:
    """
    Konversi rating gap → probabilitas H/D/A.

    Untuk soccer (ada draw):
      Dari penelitian Hvattum & Arntzen (2010), draw probability
      tertinggi saat rating gap kecil.

    Untuk NBA/NHL (tidak ada draw):
      Langsung dari expected score.
    """
    # Rating dengan home advantage
    home_adj = home_rating + HOME_ADVANTAGE
    exp_home = _expected_score(home_adj, away_rating)

    if sport in ("basketball", "hockey"):
        # Tidak ada draw
        p_home = round(min(0.95, max(0.05, exp_home)), 4)
        return p_home, 0.0, round(1 - p_home, 4)

    # Soccer: model draw probability dari rating gap
    gap = abs(home_adj - away_rating)

    # Draw lebih mungkin saat tim setara (gap kecil)
    # Threshold empiris: gap > 200 → draw probability turun drastis
    p_draw = max(0.05, 0.30 - gap / 1000.0)
    p_draw = min(0.35, p_draw)

    # Sisa dibagi proporsional berdasarkan expected score
    remaining = 1.0 - p_draw
    p_home    = round(min(0.80, exp_home * remaining / (exp_home + (1 - exp_home))), 4)
    p_away    = round(max(0.05, remaining - p_home), 4)
    p_draw    = round(1.0 - p_home - p_away, 4)

    return p_home, p_draw, p_away


def calculate_elo_matchup(
    home_name: str,
    away_name: str,
    league:    str,
    sport:     str,
) -> EloMatchup:
    """
    Hitung probabilitas matchup berdasarkan ELO rating.
    Ini dipanggil SEBELUM pertandingan untuk prediksi.
    """
    store    = get_store()
    home_r   = store.get(home_name, league)
    away_r   = store.get(away_name, league)

    home_adj = home_r.rating + HOME_ADVANTAGE
    p_home, p_draw, p_away = _elo_to_win_prob(home_r.rating, away_r.rating, sport)

    gap = home_adj - away_r.rating

    # Confidence berdasarkan jumlah data
    min_matches = min(home_r.matches_played, away_r.matches_played)
    if min_matches >= 30:
        confidence = "HIGH"
    elif min_matches >= 10:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"   # Terlalu sedikit data, rating belum stabil

    return EloMatchup(
        home_team=home_name, away_team=away_name,
        home_rating=home_r.rating, away_rating=away_r.rating,
        home_rating_adj=home_adj,
        p_home_elo=p_home, p_draw_elo=p_draw, p_away_elo=p_away,
        rating_gap=round(gap, 1),
        confidence=confidence,
    )


def update_elo_after_match(
    home_name:  str,
    away_name:  str,
    league:     str,
    sport:      str,
    home_goals: int,
    away_goals: int,
    date:       str = "",
) -> tuple[float, float]:
    """
    Update ELO rating setelah pertandingan selesai.
    Dipanggil oleh prediction_log.py saat hasil dimasukkan.

    Returns: (new_home_rating, new_away_rating)
    """
    store  = get_store()
    home_r = store.get(home_name, league)
    away_r = store.get(away_name, league)

    home_adj = home_r.rating + HOME_ADVANTAGE

    # Actual score: 1 = menang, 0.5 = draw, 0 = kalah
    if home_goals > away_goals:
        s_home, s_away = 1.0, 0.0
    elif home_goals == away_goals:
        s_home, s_away = 0.5, 0.5
    else:
        s_home, s_away = 0.0, 1.0

    # Goal margin bonus (opsional, 0–0.1 berdasarkan margin)
    margin = abs(home_goals - away_goals)
    margin_bonus = min(0.1, margin * 0.03)
    if home_goals > away_goals:
        s_home = min(1.0, s_home + margin_bonus)
    elif away_goals > home_goals:
        s_away = min(1.0, s_away + margin_bonus)

    # Expected scores
    e_home = _expected_score(home_adj, away_r.rating)
    e_away = 1.0 - e_home

    # K factors
    k_home = _k_factor(home_r.matches_played, sport)
    k_away = _k_factor(away_r.matches_played, sport)

    # New ratings
    new_home = home_r.rating + k_home * (s_home - e_home)
    new_away = away_r.rating + k_away * (s_away - e_away)

    store.update(home_name, league, new_home, date)
    store.update(away_name, league, new_away, date)
    store.save()

    logger.info(
        f"ELO updated: {home_name} {home_r.rating:.0f}→{new_home:.0f} | "
        f"{away_name} {away_r.rating:.0f}→{new_away:.0f} "
        f"(result: {home_goals}-{away_goals})"
    )

    return round(new_home, 2), round(new_away, 2)


def blend_with_elo(
    p_model_home: float,
    p_model_draw: float,
    p_model_away: float,
    elo_matchup:  EloMatchup,
    elo_weight:   float = 0.20,
) -> tuple[float, float, float]:
    """
    Gabungkan probabilitas dari model utama (Poisson/Pythagorean) dengan ELO.

    Bobot default: 80% model utama + 20% ELO.
    Saat ELO confidence LOW (sedikit data) → turunkan bobot ELO ke 10%.

    Seperti menggabungkan dua ahli: satu berbasis statistik musim ini,
    satu berbasis rekam jejak historis. Keduanya punya informasi unik.
    """
    if elo_matchup.confidence == "LOW":
        elo_weight = max(0.05, elo_weight * 0.5)

    w_model = 1.0 - elo_weight
    w_elo   = elo_weight

    new_ph = p_model_home * w_model + elo_matchup.p_home_elo * w_elo
    new_pd = p_model_draw * w_model + elo_matchup.p_draw_elo * w_elo
    new_pa = p_model_away * w_model + elo_matchup.p_away_elo * w_elo

    total  = new_ph + new_pd + new_pa
    return round(new_ph/total, 4), round(new_pd/total, 4), round(new_pa/total, 4)


# ─────────────────────────────────────────────────────────────────────────────
# Seed ELO dari statistik yang ada (bootstrap)
# ─────────────────────────────────────────────────────────────────────────────

def seed_elo_from_stats(
    league:     str,
    team_stats: list[dict],
    sport:      str,
) -> None:
    """
    Inisialisasi ELO rating dari statistik musim (bukan dari nol).
    Dipanggil SEKALI saat pertama kali setup Gen 3.

    Win% → rating awal yang lebih akurat dari default 1500.
    Formula: rating = 1500 + (win_pct - 0.5) × 400
    """
    store = get_store()
    for t in team_stats:
        name = t.get("team", "")
        if not name:
            continue

        key = f"{league}:{name}"
        if key in store.ratings and store.ratings[key].matches_played > 0:
            continue  # Sudah ada data nyata, jangan override

        # Hitung win% dari data
        wins   = t.get("wins",   0)
        draws  = t.get("draws",  0)
        loses  = t.get("loses",  0)
        total  = wins + draws + loses or 1
        wp     = (wins + draws * 0.5) / total

        # Seed rating
        seed_rating = 1500 + (wp - 0.5) * 400
        seed_rating = max(1200, min(1800, seed_rating))

        r = store.get(name, league)
        r.rating = round(seed_rating, 1)
        logger.debug(f"ELO seeded: {name} ({league}) → {seed_rating:.0f}")

    store.save()
    logger.info(f"ELO seeded for {league}: {len(team_stats)} teams")