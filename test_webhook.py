"""
test_webhook.py  [Gen 3 — Auto from Local Data]
═══════════════════════════════════════════════════════════════════════════
Baca prediksi terbaru dari predictions_log.json (hasil run_realtime.py)
dan kirim langsung ke Zapier — tanpa hardcode, tanpa refresh manual.

Usage:
  py test_webhook.py              → kirim sinyal edge tertinggi
  py test_webhook.py --all        → kirim semua prediksi eligible hari ini
  py test_webhook.py --match-id X → kirim match_id spesifik
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

from kelly_calculator import calculate_kelly, format_telegram_message


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

def load_cfg() -> dict:
    p = Path("config.yaml")
    if not p.exists():
        print("ERROR: config.yaml tidak ditemukan")
        sys.exit(1)
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ─────────────────────────────────────────────────────────────────────────────
# Baca predictions_log.json
# ─────────────────────────────────────────────────────────────────────────────

def load_predictions(log_path: str = "storage/predictions_log.json") -> list[dict]:
    p = Path(log_path)
    if not p.exists():
        print(f"ERROR: {log_path} tidak ditemukan. Jalankan run_realtime.py dulu.")
        sys.exit(1)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def get_sendable(entries: list[dict], min_edge: float, match_id: str = None) -> list[dict]:
    """
    Filter entri yang layak dikirim:
      - bet_type != PASS
      - edge >= min_edge
      - actual_result == None (masih upcoming)
      - Opsional: filter by match_id
    """
    results = []
    for e in entries:
        if match_id and e.get("match_id") != match_id:
            continue
        if e.get("bet_type", "PASS") == "PASS":
            continue
        edge = e.get("edge")
        if edge is None or edge < min_edge:
            continue
        if e.get("actual_result") is not None:
            continue
        results.append(e)

    return sorted(results, key=lambda x: x.get("edge", 0), reverse=True)


# ─────────────────────────────────────────────────────────────────────────────
# Build payload dari satu entri log
# ─────────────────────────────────────────────────────────────────────────────

def _american_to_prob(american: float) -> float:
    if american > 0:
        return 100.0 / (american + 100.0)
    return abs(american) / (abs(american) + 100.0)


def build_payload(entry: dict, bankroll_state: dict) -> dict | None:
    selection = entry.get("selection", "")
    edge      = entry.get("edge", 0)
    sel       = selection.lower()

    # Tentukan my_p + ml_odds berdasarkan sisi selection
    if "(home)" in sel or entry.get("home", "").lower() in sel:
        my_p    = entry.get("p_home_final", 0)
        ml_odds = entry.get("ml_home_odds")
    elif "(away)" in sel or entry.get("away", "").lower() in sel:
        my_p    = entry.get("p_away_final", 0)
        ml_odds = entry.get("ml_away_odds")
    elif "over" in sel or "under" in sel:
        my_p    = 0.5 + edge  # approximate untuk totals
        ml_odds = entry.get("ml_home_odds")
    else:
        my_p    = entry.get("p_home_final", 0)
        ml_odds = entry.get("ml_home_odds")

    if not ml_odds:
        return None

    market_p          = _american_to_prob(float(ml_odds))
    current_bankroll  = float(bankroll_state.get("current_bankroll",  100.0))
    starting_bankroll = float(bankroll_state.get("starting_bankroll", current_bankroll))
    daily_pnl         = float(bankroll_state.get("daily_pnl",         0.0))
    max_loss_pct      = float(bankroll_state.get("max_daily_loss_pct", 0.08))
    daily_loss_pct    = abs(daily_pnl) / starting_bankroll if daily_pnl < 0 else 0.0

    # Kill Switch
    if daily_loss_pct >= max_loss_pct:
        return {
            "message": (
                f"🛑 KILL SWITCH ACTIVATED\n\n"
                f"Daily Loss : ${abs(daily_pnl):.2f} ({daily_loss_pct:.1%})\n"
                f"Status     : Trading halted."
            ),
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "market":      f"{entry['home']} vs {entry['away']}",
            "edge":        edge,
            "kill_switch": True,
        }

    kelly_result     = calculate_kelly(my_p, market_p, current_bankroll)
    remaining_budget = max(starting_bankroll * max_loss_pct - abs(daily_pnl), 0.0)
    market_title     = f"{entry['home']} vs {entry['away']} — {selection}"

    telegram_message = format_telegram_message(
        market_title     = market_title,
        my_p             = my_p,
        market_p         = market_p,
        current_bankroll = current_bankroll,
        kelly_result     = kelly_result,
        remaining_budget = remaining_budget,
        daily_loss_pct   = daily_loss_pct,
    )

    return {
        "message":     telegram_message,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "market":      market_title,
        "edge":        round(edge * 100, 2),
        "league":      entry.get("league", ""),
        "match_date":  entry.get("match_date", ""),
        "kill_switch": False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Send ke Zapier
# ─────────────────────────────────────────────────────────────────────────────

def send(payload: dict, webhook_url: str) -> bool:
    try:
        r = requests.post(
            webhook_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=5,
        )
        if r.status_code == 200:
            print(f"  ✅ Sent: {payload['market']} | edge={payload['edge']}%")
            return True
        print(f"  ❌ HTTP {r.status_code}: {r.text[:80]}")
        return False
    except requests.exceptions.Timeout:
        print("  ❌ Timeout >5s")
        return False
    except Exception as exc:
        print(f"  ❌ Error: {exc}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all",      action="store_true")
    parser.add_argument("--match-id", type=str, default=None)
    args = parser.parse_args()

    cfg            = load_cfg()
    webhook_url    = cfg.get("zapier", {}).get("webhook_url", "")
    min_edge       = float(cfg.get("webhook", {}).get("min_edge_for_webhook", 0.12))
    bankroll_state = cfg.get("bankroll", {})

    if not webhook_url or "YOUR" in webhook_url:
        print("ERROR: webhook_url belum dikonfigurasi di config.yaml")
        sys.exit(1)

    entries  = load_predictions()
    sendable = get_sendable(entries, min_edge, match_id=args.match_id)

    if not sendable:
        print(f"Tidak ada prediksi eligible")
        print(f"  Syarat: edge >= {min_edge:.0%}, bet != PASS, belum ada hasil")
        print(f"  Total entri di log: {len(entries)}")
        sys.exit(0)

    targets = sendable if args.all else [sendable[0]]

    print(f"\nMengirim {len(targets)} sinyal ke Zapier...\n")
    for entry in targets:
        payload = build_payload(entry, bankroll_state)
        if payload:
            send(payload, webhook_url)
        else:
            print(f"  ⚠ Skip {entry.get('match_id')} — market_p tidak tersedia")

    print(f"\nSelesai. Total eligible: {len(sendable)} prediksi.")


if __name__ == "__main__":
    main()