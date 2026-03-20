# kelly_calculator.py

def calculate_kelly(my_p, market_p, current_bankroll, max_cap=0.35):
    """
    Hitung Kelly Criterion dengan cap 35%
    """
    edge = my_p - market_p
    decimal_odds = 1 / market_p
    full_kelly = edge / (decimal_odds - 1)
    capped_kelly = min(full_kelly, max_cap)
    position_size = capped_kelly * current_bankroll
    max_loss = position_size
    
    return {
        "edge": round(edge, 4),
        "edge_pct": round(edge * 100, 2),
        "full_kelly": round(full_kelly, 4),
        "full_kelly_pct": round(full_kelly * 100, 2),
        "capped_kelly": round(capped_kelly, 4),
        "capped_kelly_pct": round(capped_kelly * 100, 2),
        "position_size": round(position_size, 2),
        "max_loss": round(max_loss, 2),
        "decimal_odds": round(decimal_odds, 2)
    }

def format_telegram_message(market_title, my_p, market_p, current_bankroll, 
                           kelly_result, remaining_budget, daily_loss_pct):
    """
    Format pesan Telegram yang clean
    """
    msg = f"""🎯 TRADE SIGNAL

📊 MARKET
- {market_title}
- My P: {my_p*100:.1f}% | Market P: {market_p*100:.1f}%
- Edge: {kelly_result['edge_pct']:.2f}%

💰 POSITION SIZING
- Full Kelly: {kelly_result['full_kelly_pct']:.2f}%
- Capped (35%): {kelly_result['capped_kelly_pct']:.2f}%
- Position: ${kelly_result['position_size']} / ${current_bankroll}
- Decimal Odds: {kelly_result['decimal_odds']}

⚠️ RISK CHECK
- Max Loss: ${kelly_result['max_loss']}
- Remaining Budget: ${remaining_budget:.2f}
- Daily Loss: {daily_loss_pct*100:.2f}%

📝 CALCULATION
Edge / (Odds - 1) = {kelly_result['edge']:.4f} / ({kelly_result['decimal_odds']:.2f} - 1)
= {kelly_result['full_kelly_pct']:.2f}% → Capped to {kelly_result['capped_kelly_pct']:.2f}%
"""
    return msg