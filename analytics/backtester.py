"""
analytics/backtester.py  [G+1]
─────────────────────────────────────────────────────────────────────────────
Backtester — Validasi model terhadap hasil historis.

Analogi: Seperti seorang navigator yang membandingkan peta dengan
terrain aktual setelah perjalanan. Tanpa backtester, kita tidak
tahu apakah model kita "benar" atau sekadar terlihat masuk akal.

Metric yang dihitung:
  - Brier Score        : MSE probabilitas (lower = better, 0 = perfect)
  - Log Loss           : Cross-entropy (lower = better)
  - Calibration Bins   : P(model 60-70%) → berapa % yang benar-benar menang?
  - ROI Simulasi       : Jika kita bet $1 setiap rekomendasi, untung/rugi?
  - Hit Rate           : % prediksi arah yang benar

Cara pakai:
  from analytics.backtester import Backtester
  bt = Backtester()
  bt.record(prob, rec, actual_result)   # simpan setelah pertandingan selesai
  report = bt.generate_report()
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from analytics.probability_engine import MatchProbability
from analytics.bet_selector import BetRecommendation


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PredictionRecord:
    """Satu record prediksi + hasil aktual."""
    # Identitas
    match_id:    str      # "{home}_{away}_{date}"
    home_team:   str
    away_team:   str
    sport:       str
    date_utc:    str

    # Probabilitas model
    p_home_win:  float
    p_draw:      float
    p_away_win:  float

    # Expected score
    expected_home: float
    expected_away: float

    # Odds pasar (jika tersedia)
    ml_home:     Optional[float] = None
    ml_away:     Optional[float] = None
    total_line:  Optional[float] = None

    # Rekomendasi
    bet_type:    str = "PASS"
    selection:   str = "PASS"
    confidence:  str = "LOW"
    edge:        Optional[float] = None

    # Hasil aktual (diisi setelah pertandingan)
    actual_home_score: Optional[int] = None
    actual_away_score: Optional[int] = None
    actual_result:     Optional[str] = None   # "HOME" | "DRAW" | "AWAY"
    actual_total:      Optional[float] = None

    # Outcome bet (diisi otomatis dari evaluate())
    bet_won:     Optional[bool] = None
    pnl:         Optional[float] = None   # profit/loss per $100

    # Metadata
    model_version: str = "G1"
    dixon_coles:   bool = False


@dataclass
class BacktestReport:
    """Laporan performa model dari semua prediksi yang direkam."""
    total_predictions: int = 0
    completed:         int = 0    # yang sudah ada hasil aktual

    # Accuracy
    hit_rate_direction: float = 0.0   # % prediksi arah benar
    hit_rate_draw:      float = 0.0   # % draw predictions correct

    # Probabilistic scoring
    brier_score:   float = 0.0
    log_loss:      float = 0.0

    # Calibration (sebagai dict {bin_label: {predicted, actual, n}})
    calibration: dict = field(default_factory=dict)

    # ROI simulasi flat bet $100
    bets_placed:    int   = 0
    bets_won:       int   = 0
    total_wagered:  float = 0.0
    total_returned: float = 0.0
    roi_pct:        float = 0.0

    # Per sport
    per_sport: dict = field(default_factory=dict)

    # Per bet type
    per_bet_type: dict = field(default_factory=dict)

    generated_at: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _brier(p_predicted: float, outcome: int) -> float:
    """Brier score untuk satu prediksi."""
    return (p_predicted - outcome) ** 2

def _log_loss_single(p: float, y: int, eps: float = 1e-7) -> float:
    p = max(eps, min(1 - eps, p))
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))

def _american_to_decimal(american: float) -> float:
    if american > 0:
        return american / 100 + 1
    return 100 / abs(american) + 1

def _american_to_pnl(american: float, won: bool, stake: float = 100.0) -> float:
    if won:
        if american > 0:
            return american * stake / 100
        return stake * 100 / abs(american)
    return -stake


# ─────────────────────────────────────────────────────────────────────────────
# Backtester
# ─────────────────────────────────────────────────────────────────────────────

class Backtester:
    """
    Menyimpan prediksi, menerima hasil aktual, dan menghitung
    semua metrik performa model.
    """

    def __init__(self, storage_path: str = "storage/predictions.json"):
        self.storage_path = Path(storage_path)
        self.records: list[PredictionRecord] = []
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self.storage_path.exists():
            try:
                raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
                self.records = [PredictionRecord(**r) for r in raw]
            except Exception:
                self.records = []

    def _save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(
            json.dumps([asdict(r) for r in self.records], indent=2),
            encoding="utf-8",
        )

    # ── Record ───────────────────────────────────────────────────────────────

    def record(
        self,
        prob:   MatchProbability,
        rec:    BetRecommendation,
        odds:   Optional[dict] = None,
        date:   Optional[str]  = None,
    ) -> PredictionRecord:
        """
        Simpan satu prediksi sebelum pertandingan dimulai.
        Hasil aktual diisi kemudian via update_result().
        """
        now = date or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        mid = f"{prob.home_team}_{prob.away_team}_{now[:10]}"

        # Skip jika sudah ada
        for r in self.records:
            if r.match_id == mid:
                return r

        record = PredictionRecord(
            match_id      = mid,
            home_team     = prob.home_team,
            away_team     = prob.away_team,
            sport         = prob.sport,
            date_utc      = now,
            p_home_win    = prob.p_home_win,
            p_draw        = prob.p_draw,
            p_away_win    = prob.p_away_win,
            expected_home = prob.expected_home,
            expected_away = prob.expected_away,
            ml_home       = odds.get("moneyline_home") if odds else None,
            ml_away       = odds.get("moneyline_away") if odds else None,
            total_line    = odds.get("total_line")     if odds else None,
            bet_type      = rec.bet_type,
            selection     = rec.selection,
            confidence    = rec.confidence,
            edge          = rec.edge,
            dixon_coles   = getattr(prob, "dixon_coles_applied", False),
        )
        self.records.append(record)
        self._save()
        return record

    def update_result(
        self,
        match_id:   str,
        home_score: int,
        away_score: int,
    ) -> Optional[PredictionRecord]:
        """
        Update hasil aktual untuk prediksi yang sudah tersimpan.
        Otomatis mengevaluasi apakah bet menang dan menghitung P&L.
        """
        for r in self.records:
            if r.match_id == match_id:
                r.actual_home_score = home_score
                r.actual_away_score = away_score
                r.actual_total      = home_score + away_score

                if home_score > away_score:
                    r.actual_result = "HOME"
                elif home_score < away_score:
                    r.actual_result = "AWAY"
                else:
                    r.actual_result = "DRAW"

                self._evaluate_bet(r)
                self._save()
                return r
        return None

    def _evaluate_bet(self, r: PredictionRecord) -> None:
        """Hitung apakah bet menang dan berapa P&L-nya."""
        if r.actual_result is None:
            return

        won  = False
        odds = None

        if r.bet_type == "MONEYLINE":
            side = "HOME" if r.home_team in r.selection else "AWAY"
            won  = (r.actual_result == side)
            odds = r.ml_home if side == "HOME" else r.ml_away

        elif r.bet_type == "SPREAD":
            # Evaluasi spread: butuh actual score dan spread line
            won  = False   # simplified — perlu actual score + spread
            odds = None

        elif r.bet_type in ("OVER", "UNDER"):
            if r.total_line and r.actual_total is not None:
                if r.bet_type == "OVER":
                    won = r.actual_total > r.total_line
                else:
                    won = r.actual_total < r.total_line
            # Jika tie dengan line → push (tidak dihitung)
            odds = None

        elif r.bet_type == "PASS":
            r.bet_won = None
            r.pnl     = 0.0
            return

        r.bet_won = won
        if odds is not None:
            r.pnl = _american_to_pnl(odds, won)
        else:
            r.pnl = 100.0 if won else -100.0   # fallback -110 implied

    # ── Generate Report ───────────────────────────────────────────────────────

    def generate_report(self) -> BacktestReport:
        """
        Hitung semua metrik dari records yang sudah ada hasil aktual.
        """
        completed = [r for r in self.records if r.actual_result is not None]
        report    = BacktestReport(
            total_predictions = len(self.records),
            completed         = len(completed),
            generated_at      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        )

        if not completed:
            return report

        # ── Direction accuracy ────────────────────────────────────────────────
        n_correct = 0
        for r in completed:
            pred = max(
                ("HOME", r.p_home_win),
                ("DRAW", r.p_draw),
                ("AWAY", r.p_away_win),
                key=lambda x: x[1],
            )[0]
            if pred == r.actual_result:
                n_correct += 1
        report.hit_rate_direction = round(n_correct / len(completed), 4)

        # ── Brier Score ───────────────────────────────────────────────────────
        brier_scores = []
        log_losses   = []
        for r in completed:
            y_home = 1 if r.actual_result == "HOME" else 0
            y_draw = 1 if r.actual_result == "DRAW" else 0
            y_away = 1 if r.actual_result == "AWAY" else 0
            bs = (_brier(r.p_home_win, y_home)
                + _brier(r.p_draw,     y_draw)
                + _brier(r.p_away_win, y_away)) / 3
            brier_scores.append(bs)

            # Log loss pada outcome yang terjadi
            if r.actual_result == "HOME":
                log_losses.append(_log_loss_single(r.p_home_win, 1))
            elif r.actual_result == "DRAW":
                log_losses.append(_log_loss_single(r.p_draw, 1))
            else:
                log_losses.append(_log_loss_single(r.p_away_win, 1))

        report.brier_score = round(statistics.mean(brier_scores), 5)
        report.log_loss    = round(statistics.mean(log_losses),   5)

        # ── Calibration bins (deciles) ────────────────────────────────────────
        bins: dict[str, dict] = {}
        for r in completed:
            p_max = max(r.p_home_win, r.p_draw, r.p_away_win)
            bin_label = f"{int(p_max * 10) * 10}-{int(p_max * 10) * 10 + 10}%"
            if bin_label not in bins:
                bins[bin_label] = {"predicted_sum": 0.0, "actual_wins": 0, "n": 0}
            bins[bin_label]["predicted_sum"] += p_max
            bins[bin_label]["n"]             += 1
            # "win" = model's top pick was correct
            pred = max(
                ("HOME", r.p_home_win),
                ("DRAW", r.p_draw),
                ("AWAY", r.p_away_win),
                key=lambda x: x[1],
            )[0]
            if pred == r.actual_result:
                bins[bin_label]["actual_wins"] += 1

        for label, b in bins.items():
            bins[label]["predicted_avg"] = round(b["predicted_sum"] / b["n"], 3)
            bins[label]["actual_rate"]   = round(b["actual_wins"]   / b["n"], 3)
        report.calibration = bins

        # ── ROI simulasi ──────────────────────────────────────────────────────
        bet_records = [r for r in completed if r.bet_type != "PASS" and r.pnl is not None]
        if bet_records:
            report.bets_placed    = len(bet_records)
            report.bets_won       = sum(1 for r in bet_records if r.bet_won)
            report.total_wagered  = round(len(bet_records) * 100.0, 2)
            report.total_returned = round(sum(r.pnl for r in bet_records) + report.total_wagered, 2)
            net = report.total_returned - report.total_wagered
            report.roi_pct = round(net / report.total_wagered * 100, 2) if report.total_wagered else 0.0

        # ── Per sport ─────────────────────────────────────────────────────────
        sports = set(r.sport for r in completed)
        for sport in sports:
            recs = [r for r in completed if r.sport == sport]
            n_c  = sum(1 for r in recs if max(
                ("HOME", r.p_home_win), ("DRAW", r.p_draw), ("AWAY", r.p_away_win),
                key=lambda x: x[1],
            )[0] == r.actual_result)
            report.per_sport[sport] = {
                "n":        len(recs),
                "hit_rate": round(n_c / len(recs), 3) if recs else 0.0,
            }

        # ── Per bet type ──────────────────────────────────────────────────────
        bet_types = set(r.bet_type for r in bet_records)
        for bt in bet_types:
            recs = [r for r in bet_records if r.bet_type == bt]
            won  = sum(1 for r in recs if r.bet_won)
            pnl  = sum(r.pnl for r in recs)
            report.per_bet_type[bt] = {
                "n":       len(recs),
                "won":     won,
                "win_rate": round(won / len(recs), 3) if recs else 0.0,
                "net_pnl": round(pnl, 2),
            }

        return report

    # ── Convenience ──────────────────────────────────────────────────────────

    def pending_results(self) -> list[PredictionRecord]:
        """Returns prediksi yang belum ada hasil aktualnya."""
        return [r for r in self.records if r.actual_result is None]

    def print_summary(self) -> None:
        """Quick summary ke console."""
        report = self.generate_report()
        print(f"\n{'='*50}")
        print(f"BACKTEST REPORT — {report.generated_at}")
        print(f"{'='*50}")
        print(f"Total predictions : {report.total_predictions}")
        print(f"Completed         : {report.completed}")
        print(f"Direction accuracy: {report.hit_rate_direction:.1%}")
        print(f"Brier Score       : {report.brier_score:.5f}  (lower=better, 0=perfect)")
        print(f"Log Loss          : {report.log_loss:.5f}")
        if report.bets_placed:
            print(f"\nBets placed  : {report.bets_placed}")
            print(f"Bets won     : {report.bets_won}")
            print(f"ROI          : {report.roi_pct:+.2f}%")
        if report.calibration:
            print(f"\nCalibration:")
            for label, b in sorted(report.calibration.items()):
                print(f"  {label:10s} predicted={b['predicted_avg']:.0%}  "
                      f"actual={b['actual_rate']:.0%}  n={b['n']}")
        print(f"{'='*50}\n")