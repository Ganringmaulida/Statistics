"""
webhook/zapier_sender.py  [Gen 3]
═══════════════════════════════════════════════════════════════════════════
Modul integrasi Zapier — pipeline dari sinyal bet ke Telegram notification.

Flow:
  prepare_zapier_payload()   → validasi + ekstrak variabel dari objek engine
  process_kelly_for_webhook() → Kelly sizing + Kill Switch check → final JSON
  send_to_zapier()           → HTTP POST non-blocking (timeout=5s)

Dipanggil dari run_realtime.py setelah `bet = select_bet(prob, odds, cfg)`.
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _american_to_prob(american: float) -> float:
    """American odds → implied probability (raw, dengan vig)."""
    if american > 0:
        return 100.0 / (american + 100.0)
    return abs(american) / (abs(american) + 100.0)


def _resolve_side(bet_selection: str, home_team: str, away_team: str) -> str:
    """
    Tentukan sisi bet (HOME / AWAY / DRAW / OVER / UNDER) dari teks selection.

    Contoh input:
      "Arsenal ML (Home)"        → HOME
      "Tottenham Hotspur ML (Away)" → AWAY
      "Over 3.5"                 → OVER
      "Under 226.5"              → UNDER
      "Crystal Palace -0.5"      → HOME  (spread home team)
    """
    sel = bet_selection.lower()
    if "(home)" in sel or "home" in sel:
        return "HOME"
    if "(away)" in sel or "away" in sel:
        return "AWAY"
    if "draw" in sel:
        return "DRAW"
    if sel.startswith("over"):
        return "OVER"
    if sel.startswith("under"):
        return "UNDER"

    # Fallback: cek apakah nama tim home ada di selection
    if home_team.lower() in sel:
        return "HOME"
    if away_team.lower() in sel:
        return "AWAY"

    return "HOME"  # safe default jika tidak bisa diparse


# ─────────────────────────────────────────────────────────────────────────────
# Fungsi 1 — Prepare Payload (Gate 1: Edge filter)
# ─────────────────────────────────────────────────────────────────────────────

def prepare_zapier_payload(
    fixture:      dict,
    prob,         # analytics.probability_engine.MatchProbability
    bet,          # analytics.bet_selector.BetRecommendation
    odds:         Optional[dict],
    bankroll_cfg: dict,
) -> Optional[dict]:
    """
    Ekstrak variabel dinamis dari objek engine dan jalankan Gate 1 (edge filter).

    Returns:
        dict  → data bersih untuk diteruskan ke process_kelly_for_webhook()
        None  → gate gagal, skip pengiriman

    bankroll_cfg keys yang dibaca:
        min_edge_for_webhook  (float, default 0.12)
    """
    # Skip jika tidak ada rekomendasi bet
    if bet.bet_type == "PASS" or bet.edge is None:
        return None

    edge = bet.edge

    # ── Gate 1: Minimum edge threshold ──────────────────────────────────────
    min_edge = float(bankroll_cfg.get("min_edge_for_webhook", 0.12))
    if edge < min_edge:
        logger.debug(
            f"[Zapier] Gate 1 BLOCK: edge {edge:.1%} < minimum {min_edge:.1%} "
            f"({fixture['home']} vs {fixture['away']})"
        )
        return None

    home_team = fixture.get("home", prob.home_team)
    away_team = fixture.get("away", prob.away_team)
    side      = _resolve_side(bet.selection, home_team, away_team)

    # ── Tentukan my_p berdasarkan sisi ──────────────────────────────────────
    if side == "HOME":
        my_p     = prob.p_home_win
        market_p = prob.market_p_home
    elif side == "AWAY":
        my_p     = prob.p_away_win
        market_p = prob.market_p_away
    elif side == "DRAW":
        my_p     = prob.p_draw
        market_p = None  # jarang tersedia, fallback ke odds mentah
    elif side in ("OVER", "UNDER"):
        # Untuk totals: my_p dan market_p dari bet_selector
        my_p     = bet.model_prob   # sudah dihitung di _eval_totals
        market_p = bet.market_prob
    else:
        my_p     = prob.p_home_win
        market_p = prob.market_p_home

    # ── Fallback: hitung market_p dari raw odds jika belum ada ─────────────
    if market_p is None and odds:
        if side == "HOME" and odds.get("moneyline_home"):
            market_p = _american_to_prob(float(odds["moneyline_home"]))
        elif side == "AWAY" and odds.get("moneyline_away"):
            market_p = _american_to_prob(float(odds["moneyline_away"]))
        elif side == "DRAW" and odds.get("moneyline_draw"):
            market_p = _american_to_prob(float(odds["moneyline_draw"]))

    # Tidak bisa kirim tanpa market_p — Kelly tidak bisa dihitung
    if market_p is None:
        logger.debug(
            f"[Zapier] Gate 1 BLOCK: market_p unavailable "
            f"({home_team} vs {away_team} — {bet.selection})"
        )
        return None

    market_title = f"{home_team} vs {away_team} — {bet.selection}"

    return {
        "market_title": market_title,
        "my_p":         round(float(my_p),     4),
        "market_p":     round(float(market_p), 4),
        "edge":         round(float(edge),      4),
        "bet_type":     bet.bet_type,
        "confidence":   bet.confidence,
        "side":         side,
        "home_team":    home_team,
        "away_team":    away_team,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fungsi 2 — Kelly Calculation + Kill Switch (Gate 2)
# ─────────────────────────────────────────────────────────────────────────────

def process_kelly_for_webhook(
    payload_data:   dict,
    bankroll_state: dict,
) -> Optional[dict]:
    """
    Hitung Kelly sizing dan terapkan Gate 2 (daily loss Kill Switch).

    Returns:
        dict  → final JSON payload siap di-POST ke Zapier
        None  → tidak ada action (seharusnya tidak terjadi — kill switch return dict)

    bankroll_state keys yang dibaca:
        current_bankroll      (float) — modal aktif saat ini
        starting_bankroll     (float) — modal awal hari ini (untuk % loss)
        daily_pnl             (float) — P&L hari ini (negatif = rugi)
        max_daily_loss_pct    (float, default 0.08)
    """
    from kelly_calculator import calculate_kelly, format_telegram_message

    my_p             = payload_data["my_p"]
    market_p         = payload_data["market_p"]
    current_bankroll = float(bankroll_state.get("current_bankroll",  100.0))
    starting_bankroll= float(bankroll_state.get("starting_bankroll", current_bankroll))
    daily_pnl        = float(bankroll_state.get("daily_pnl",         0.0))
    max_loss_pct     = float(bankroll_state.get("max_daily_loss_pct", 0.08))

    daily_loss_pct = abs(daily_pnl) / starting_bankroll if daily_pnl < 0 else 0.0

    # ── Gate 2: Kill Switch — daily loss limit ───────────────────────────────
    if daily_loss_pct >= max_loss_pct:
        logger.warning(
            f"[Zapier] KILL SWITCH ACTIVATED: "
            f"daily_loss={daily_loss_pct:.1%} >= limit={max_loss_pct:.1%}"
        )
        return {
            "message":     (
                f"🛑 KILL SWITCH ACTIVATED\n\n"
                f"Daily Loss : ${abs(daily_pnl):.2f} ({daily_loss_pct:.1%})\n"
                f"Limit      : {max_loss_pct:.1%}\n"
                f"Status     : Trading halted. Reset sesi sebelum lanjut."
            ),
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "market":      payload_data["market_title"],
            "edge":        payload_data["edge"],
            "kill_switch": True,
        }

    # ── Kelly calculation ────────────────────────────────────────────────────
    kelly_result    = calculate_kelly(my_p, market_p, current_bankroll)
    remaining_budget = starting_bankroll * max_loss_pct - abs(daily_pnl)

    telegram_message = format_telegram_message(
        market_title    = payload_data["market_title"],
        my_p            = my_p,
        market_p        = market_p,
        current_bankroll= current_bankroll,
        kelly_result    = kelly_result,
        remaining_budget= max(remaining_budget, 0.0),
        daily_loss_pct  = daily_loss_pct,
    )

    logger.info(
        f"[Zapier] Payload ready: {payload_data['market_title']} | "
        f"edge={payload_data['edge']:.1%} | "
        f"kelly={kelly_result['capped_kelly_pct']:.2f}% | "
        f"pos=${kelly_result['position_size']}"
    )

    return {
        "message":     telegram_message,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "market":      payload_data["market_title"],
        "edge":        kelly_result["edge_pct"],
        "kill_switch": False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fungsi 3 — HTTP POST Non-Blocking (timeout=5s)
# ─────────────────────────────────────────────────────────────────────────────

def send_to_zapier(
    payload_json: dict,
    webhook_url:  str,
) -> bool:
    """
    POST payload ke Zapier webhook dengan timeout=5s.

    Tidak pernah raise exception — semua error dicatat ke logger.
    Returns True jika HTTP 200, False untuk semua error/non-200.
    """
    if not webhook_url or "YOUR" in webhook_url:
        logger.debug("[Zapier] Webhook URL tidak dikonfigurasi — skip")
        return False

    try:
        response = requests.post(
            webhook_url,
            data=json.dumps(payload_json, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=5,
        )
        if response.status_code == 200:
            logger.info(
                f"[Zapier] ✅ Sent: {payload_json.get('market', '')} "
                f"→ HTTP {response.status_code}"
            )
            return True
        else:
            logger.error(
                f"[Zapier] ❌ HTTP {response.status_code}: "
                f"{response.text[:120]}"
            )
            return False

    except requests.exceptions.Timeout:
        logger.error("[Zapier] Timeout >5s — webhook skipped, pipeline tidak terblokir")
        return False
    except requests.exceptions.ConnectionError as exc:
        logger.error(f"[Zapier] ConnectionError: {exc}")
        return False
    except Exception as exc:
        logger.error(f"[Zapier] Unexpected error: {exc}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Convenience wrapper — panggil ketiga fungsi sekaligus
# ─────────────────────────────────────────────────────────────────────────────

def try_send_bet_signal(
    fixture:        dict,
    prob,
    bet,
    odds:           Optional[dict],
    cfg:            dict,
) -> None:
    """
    One-liner wrapper untuk dipanggil dari process_league().

    Membaca konfigurasi dari cfg:
        cfg["bankroll"]      → bankroll_state dict
        cfg["webhook"]       → { min_edge_for_webhook, ... }
        cfg["zapier"]["webhook_url"]

    Jika config tidak ada, fungsi silent return (tidak crash main loop).
    """
    webhook_url = cfg.get("zapier", {}).get("webhook_url", "")
    if not webhook_url:
        return

    bankroll_cfg   = cfg.get("webhook",  {})
    bankroll_state = cfg.get("bankroll", {})

    # Gate 1
    payload_data = prepare_zapier_payload(fixture, prob, bet, odds, bankroll_cfg)
    if payload_data is None:
        return

    # Gate 2 + Kelly
    final_payload = process_kelly_for_webhook(payload_data, bankroll_state)
    if final_payload is None:
        return

    # HTTP POST
    send_to_zapier(final_payload, webhook_url)