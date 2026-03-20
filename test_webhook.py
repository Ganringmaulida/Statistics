import requests
import json
from datetime import datetime, timezone
from kelly_calculator import calculate_kelly, format_telegram_message 

# ===== CONFIG =====
ZAPIER_WEBHOOK_URL = "https://hooks.zapier.com/hooks/catch/26882462/up8eycy/"

# ===== MARKET DATA (Dari Model Lo) =====
market_title = "Lakers vs Warriors - Lakers Win"
my_p = 0.67
market_p = 0.52
current_bankroll = 58.40
starting_bankroll = 60.00
daily_pnl = -1.60
daily_loss_pct = abs(daily_pnl) / starting_bankroll  # 0.0267
remaining_budget = starting_bankroll * 0.08 - abs(daily_pnl)  # $3.20

# ===== PRE-FILTER GATES =====
edge = my_p - market_p

# GATE 1: Edge minimum 12%
if edge < 0.12:
    print(f"❌ REJECTED: Edge {edge*100:.1f}% < 12% minimum")
    exit()

# GATE 2: Daily loss limit
if daily_loss_pct >= 0.08:
    print(f"🛑 KILL SWITCH: Daily loss {daily_loss_pct*100:.1f}% >= 8% limit")
    # Send alert to Telegram
    alert_payload = {
        "message": f"🛑 KILL SWITCH ACTIVATED\n\nDaily Loss: ${abs(daily_pnl)} ({daily_loss_pct*100:.1f}%)\nTrading halted until session reset."
    }
    requests.post(ZAPIER_WEBHOOK_URL, json=alert_payload)
    exit()

# ===== HITUNG KELLY =====
kelly_result = calculate_kelly(my_p, market_p, current_bankroll)

# ===== FORMAT MESSAGE =====
telegram_message = format_telegram_message(
    market_title, my_p, market_p, current_bankroll,
    kelly_result, remaining_budget, daily_loss_pct
)

# ===== KIRIM KE ZAPIER =====
payload = {
    "message": telegram_message,
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "market": market_title,
    "edge": kelly_result['edge_pct']
}

print("📤 Sending to Zapier...")
response = requests.post(
    ZAPIER_WEBHOOK_URL, 
    data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),  # ← GANTI INI
    headers={"Content-Type": "application/json; charset=utf-8"}     # ← TAMBAH INI
)
