# run_live.py — jalankan sekali, sistem jalan terus
import time, subprocess, sys
from datetime import datetime

INTERVAL_MINUTES = 30  # refresh setiap 30 menit

def run():
    while True:
        now = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{now}] Menjalankan analisis...")
        subprocess.run([sys.executable, "app.py", "--league", "epl"])
        subprocess.run([sys.executable, "app.py", "--league", "nba"])
        print(f"Selesai. Refresh berikutnya dalam {INTERVAL_MINUTES} menit.")
        time.sleep(INTERVAL_MINUTES * 60)

if __name__ == "__main__":
    run()