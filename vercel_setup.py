"""
VERCEL DEPLOYMENT — Jika ingin kirim dari cloud (bukan lokal)
═══════════════════════════════════════════════════════════════════════════

KONTEKS:
  run_realtime.py (lokal) → generate predictions_log.json
  Masalah: jika lokal mati, tidak ada yang bisa kirim ke Zapier

SOLUSI VERCEL:
  Deploy API endpoint di Vercel yang:
  1. Baca predictions_log.json dari GitHub repo (auto-commit oleh lokal)
  2. Filter sinyal eligible
  3. POST ke Zapier
  4. Dipanggil via cron atau manual trigger

═══════════════════════════════════════════════════════════════════════════
PROMPT UNTUK CURSOR / CHATGPT (copy-paste):
═══════════════════════════════════════════════════════════════════════════

"Buatkan Vercel serverless deployment untuk sports prediction webhook.

Struktur yang dibutuhkan:
  vercel.json
  api/send_signal.py       ← serverless function
  requirements_vercel.txt

Spesifikasi api/send_signal.py:
1. HTTP GET /api/send_signal?secret=XXX
2. Baca predictions_log.json dari GitHub raw URL:
   https://raw.githubusercontent.com/{USER}/{REPO}/main/storage/predictions_log.json
3. Filter: bet_type != PASS, edge >= 0.12, actual_result == None
4. Ambil entri dengan edge tertinggi
5. Hitung kelly: position = edge / (decimal_odds - 1) * 0.25, cap 5%
6. Format pesan Telegram dan POST ke ZAPIER_WEBHOOK_URL (dari env variable)
7. Return JSON {status, market, edge, sent}

vercel.json:
{
  'functions': {'api/send_signal.py': {'runtime': 'python3.9'}},
  'env': {
    'ZAPIER_WEBHOOK_URL': '@zapier_webhook_url',
    'GITHUB_RAW_URL': '@github_raw_url',
    'API_SECRET': '@api_secret'
  },
  'crons': [{'path': '/api/send_signal', 'schedule': '0 */2 * * *'}]
}

Tambahkan error handling untuk: GitHub fetch gagal, no eligible predictions,
Zapier timeout. Semua response harus JSON."

═══════════════════════════════════════════════════════════════════════════
SETUP STEPS SETELAH DEPLOY:
═══════════════════════════════════════════════════════════════════════════

1. Push predictions_log.json ke GitHub (tambah ke git, jangan .gitignore)
2. Tambah script di run_realtime.py untuk auto-commit setelah run_once():
   git add storage/predictions_log.json && git commit -m "update predictions" && git push
3. Set Vercel env variables:
   ZAPIER_WEBHOOK_URL = https://hooks.zapier.com/hooks/catch/...
   GITHUB_RAW_URL     = https://raw.githubusercontent.com/USER/REPO/main/storage/predictions_log.json
   API_SECRET         = random string untuk keamanan
4. Vercel cron akan trigger /api/send_signal setiap 2 jam otomatis
"""

# ─────────────────────────────────────────────────────────────────────────────
# api/send_signal.py — Vercel serverless function (simpan di folder api/)
# ─────────────────────────────────────────────────────────────────────────────

VERCEL_FUNCTION = '''
import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests


def _american_to_prob(american: float) -> float:
    if american > 0:
        return 100.0 / (american + 100.0)
    return abs(american) / (abs(american) + 100.0)


def _kelly(my_p: float, market_p: float, bankroll: float = 100.0) -> dict:
    if market_p <= 0 or market_p >= 1:
        return {"position_size": 0, "capped_kelly_pct": 0, "edge_pct": 0}
    decimal_odds = 1 / market_p
    edge         = my_p - market_p
    full_kelly   = edge / (decimal_odds - 1) if decimal_odds > 1 else 0
    capped       = min(max(full_kelly * 0.25, 0), 0.05)
    return {
        "position_size":    round(capped * bankroll, 2),
        "capped_kelly_pct": round(capped * 100, 2),
        "edge_pct":         round(edge * 100, 2),
        "decimal_odds":     round(decimal_odds, 2),
    }


def fetch_predictions() -> list[dict]:
    url = os.environ.get("GITHUB_RAW_URL", "")
    if not url:
        raise ValueError("GITHUB_RAW_URL env variable tidak dikonfigurasi")
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()


def get_best_signal(entries: list[dict], min_edge: float = 0.12) -> dict | None:
    candidates = [
        e for e in entries
        if e.get("bet_type", "PASS") != "PASS"
        and (e.get("edge") or 0) >= min_edge
        and e.get("actual_result") is None
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: x.get("edge", 0), reverse=True)[0]


def build_message(entry: dict, kelly: dict) -> str:
    return (
        f"🎯 TRADE SIGNAL\\n\\n"
        f"📊 MARKET\\n"
        f"- {entry['home']} vs {entry['away']}\\n"
        f"- {entry.get('selection', '')}\\n"
        f"- League: {entry.get('league', '').upper()}\\n"
        f"- Match: {entry.get('match_date', '')[:10]}\\n\\n"
        f"💰 KELLY SIZING\\n"
        f"- Edge      : {kelly['edge_pct']:.2f}%\\n"
        f"- Kelly     : {kelly['capped_kelly_pct']:.2f}%\\n"
        f"- Position  : ${kelly['position_size']}\\n"
        f"- Odds      : {kelly['decimal_odds']}\\n\\n"
        f"📈 PROBABILITIES\\n"
        f"- P(Home)   : {entry.get('p_home_final', 0):.1%}\\n"
        f"- P(Away)   : {entry.get('p_away_final', 0):.1%}\\n"
        f"- Confidence: {entry.get('confidence', 'N/A')}\\n"
    )


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed   = urlparse(self.path)
        params   = parse_qs(parsed.query)
        secret   = params.get("secret", [None])[0]
        expected = os.environ.get("API_SECRET", "")

        # Auth check
        if expected and secret != expected:
            self._respond(401, {"error": "Unauthorized"})
            return

        try:
            entries = fetch_predictions()
            signal  = get_best_signal(entries)

            if not signal:
                self._respond(200, {"status": "no_signal", "message": "No eligible predictions"})
                return

            # Determine my_p
            sel = signal.get("selection", "").lower()
            if "(home)" in sel or signal.get("home", "").lower() in sel:
                my_p    = signal.get("p_home_final", 0.5)
                ml_odds = signal.get("ml_home_odds")
            else:
                my_p    = signal.get("p_away_final", 0.5)
                ml_odds = signal.get("ml_away_odds")

            if not ml_odds:
                self._respond(200, {"status": "no_signal", "message": "No market odds"})
                return

            market_p = _american_to_prob(float(ml_odds))
            kelly    = _kelly(my_p, market_p)
            message  = build_message(signal, kelly)

            # POST ke Zapier
            zapier_url = os.environ.get("ZAPIER_WEBHOOK_URL", "")
            if not zapier_url:
                self._respond(500, {"error": "ZAPIER_WEBHOOK_URL not set"})
                return

            payload = {
                "message":   message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "market":    f"{signal['home']} vs {signal['away']}",
                "edge":      kelly["edge_pct"],
            }

            zap_r = requests.post(
                zapier_url,
                json=payload,
                timeout=5,
            )

            self._respond(200, {
                "status":  "sent" if zap_r.status_code == 200 else "zapier_error",
                "market":  payload["market"],
                "edge":    kelly["edge_pct"],
                "zapier":  zap_r.status_code,
            })

        except Exception as exc:
            self._respond(500, {"error": str(exc)})

    def _respond(self, code: int, body: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())
        
    def log_message(self, *args):
        pass  # suppress default HTTP logs
'''

VERCEL_JSON = '''
{
  "functions": {
    "api/send_signal.py": {
      "runtime": "python3.9"
    }
  },
  "env": {
    "ZAPIER_WEBHOOK_URL": "@zapier_webhook_url",
    "GITHUB_RAW_URL":     "@github_raw_url",
    "API_SECRET":         "@api_secret"
  },
  "crons": [
    {
      "path":     "/api/send_signal",
      "schedule": "0 */2 * * *"
    }
  ]
}
'''

REQUIREMENTS_VERCEL = "requests>=2.31.0\n"

AUTO_COMMIT_SNIPPET = '''
# Tambahkan ke run_realtime.py — di dalam run_once(), setelah loop selesai
# Letakkan setelah baris: console.print(f"  [dim]Total pertandingan diproses: {total}[/]")

import subprocess

def _auto_push_predictions():
    """Auto-commit predictions_log.json ke GitHub setelah setiap run."""
    try:
        subprocess.run(
            ["git", "add", "storage/predictions_log.json"],
            check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", f"predictions update {datetime.now().strftime('%Y-%m-%d %H:%M')}"],
            capture_output=True  # tidak check=True — commit bisa skip jika tidak ada perubahan
        )
        subprocess.run(
            ["git", "push"],
            check=True, capture_output=True
        )
        logger.info("predictions_log.json pushed to GitHub")
    except subprocess.CalledProcessError as exc:
        logger.warning(f"Git push failed: {exc.stderr.decode()[:100]}")

# Panggil di akhir run_once():
_auto_push_predictions()
'''

if __name__ == "__main__":
    import os

    # Buat struktur folder Vercel
    os.makedirs("api", exist_ok=True)

    with open("api/send_signal.py", "w", encoding="utf-8") as f:
        f.write(VERCEL_FUNCTION.strip())
    print("✅ api/send_signal.py dibuat")

    with open("vercel.json", "w", encoding="utf-8") as f:
        f.write(VERCEL_JSON.strip())
    print("✅ vercel.json dibuat")

    with open("requirements_vercel.txt", "w", encoding="utf-8") as f:
        f.write(REQUIREMENTS_VERCEL)
    print("✅ requirements_vercel.txt dibuat")

    print("\n📋 Snippet auto-commit untuk run_realtime.py:")
    print(AUTO_COMMIT_SNIPPET)

    print("\n🚀 Deploy steps:")
    print("  1. npm i -g vercel")
    print("  2. vercel login")
    print("  3. vercel env add zapier_webhook_url")
    print("  4. vercel env add github_raw_url")
    print("  5. vercel env add api_secret")
    print("  6. vercel --prod")
    print("\n  URL trigger: https://your-project.vercel.app/api/send_signal?secret=XXX")