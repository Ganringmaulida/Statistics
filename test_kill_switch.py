import requests
from datetime import datetime, timezone

# 1. Simulasi pre-filter lokal (Gate 1 & Gate 2)
def should_send_webhook(my_p, market_p, daily_loss_pct):
    edge = my_p - market_p
    if edge < 0.12:
        print("BLOCKED: Edge di bawah 12%")
        return False
    if daily_loss_pct >= 0.08:
        print("🛑 KILL SWITCH AKTIF: Daily loss limit hit! Webhook dibatalkan.")
        return False
    return True

# Parameter test (ubah daily_loss_pct ke 0.09 untuk test Kill Switch)
my_p = 0.67
market_p = 0.52
daily_loss_pct = 0.09  # Simulasi kerugian 9% (Batas 8%)

if should_send_webhook(my_p, market_p, daily_loss_pct):
    print("Mengirim payload ke Zapier...")
    # [Masukkan kode requests.post Anda ke URL Zapier di sini]
else:
    print("Eksekusi dihentikan oleh sistem keamanan lokal.")