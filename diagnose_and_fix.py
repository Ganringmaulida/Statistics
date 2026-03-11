"""
diagnose_and_fix.py — Jalankan ini dari folder predictor:
    py diagnose_and_fix.py

Script ini akan:
  1. Diagnose semua penyebab demo data masih dipakai
  2. Test setiap API endpoint secara langsung
  3. Fix config.yaml otomatis
  4. Hapus cache lama
  5. Beri instruksi jelas apa yang harus dilakukan
"""
from __future__ import annotations
import sys, os, json, re, time, traceback, shutil
from pathlib import Path
from datetime import datetime, timezone

# Pastikan jalankan dari folder predictor
HERE = Path(__file__).resolve().parent
os.chdir(HERE)
sys.path.insert(0, str(HERE))

try:
    import requests
    import yaml
    from rich.console import Console
    from rich.panel   import Panel
    from rich.table   import Table
    console = Console()
except ImportError as e:
    print(f"Import error: {e}")
    print("Jalankan: pip install requests pyyaml rich")
    sys.exit(1)

PASS  = "[bold green]✅ PASS[/]"
FAIL  = "[bold red]❌ FAIL[/]"
WARN  = "[bold yellow]⚠  WARN[/]"
INFO  = "[dim cyan]ℹ [/]"
FIX   = "[bold magenta]🔧 FIX[/]"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"

# ─────────────────────────────────────────────────────────────────────────────
print_results: list[tuple] = []   # (category, status, message)

def R(cat, status, msg):
    print_results.append((cat, status, msg))
    console.print(f"  {status}  [white]{cat}[/]  {msg}")

# ─────────────────────────────────────────────────────────────────────────────
console.print(Panel(
    "[bold white]DIAGNOSE & FIX — Sports Prediction Engine[/]\n"
    "[dim]Mengidentifikasi kenapa data masih DEMO[/]",
    style="blue"
))

# ═════════════════════════════════════════════════════════════════════════════
# STEP 1 — Cek versi fetcher.py
# ═════════════════════════════════════════════════════════════════════════════
console.print("\n[bold cyan]STEP 1 — Cek fetcher.py (root cause #1)[/]")

fetcher_path = Path("data/fetcher.py")
if not fetcher_path.exists():
    R("fetcher.py", FAIL, "FILE TIDAK ADA di data/fetcher.py")
else:
    code = fetcher_path.read_text(encoding="utf-8", errors="ignore")
    has_nhl    = "_nhl_stats_live" in code or "nhle.com" in code
    has_bdl    = "balldontlie"     in code
    has_stale  = "_fixtures_are_stale" in code or "fixtures_are_stale" in code
    has_under  = "teamsData"       in code

    version = "Gen 3 (BARU)" if (has_nhl and has_bdl) else "Gen 2 (LAMA — perlu di-replace)"

    R("fetcher.py versi", PASS if has_nhl else FAIL, version)
    R("NHL Official API",   PASS if has_nhl   else FAIL,
      "ada" if has_nhl   else "TIDAK ADA — update fetcher.py dari outputs/data/fetcher.py")
    R("BallDontLie NBA",    PASS if has_bdl   else FAIL,
      "ada" if has_bdl   else "TIDAK ADA — update fetcher.py dari outputs/data/fetcher.py")
    R("Stale cache fix",    PASS if has_stale else FAIL,
      "ada" if has_stale else "TIDAK ADA — update fetcher.py")
    R("Understat parser",   PASS if has_under else WARN,
      "ada" if has_under else "TIDAK ADA")

    if not has_nhl:
        console.print(
            "\n  [bold red]⛔ MASALAH UTAMA DITEMUKAN:[/]\n"
            "  fetcher.py masih versi GEN 2 yang tidak punya NHL API + BallDontLie.\n"
            "  Ganti dengan file dari: outputs/data/fetcher.py\n"
        )

# ═════════════════════════════════════════════════════════════════════════════
# STEP 2 — Cek config.yaml
# ═════════════════════════════════════════════════════════════════════════════
console.print("\n[bold cyan]STEP 2 — Cek config.yaml[/]")

cfg_path = Path("config.yaml")
cfg: dict = {}

if not cfg_path.exists():
    R("config.yaml", FAIL, "FILE TIDAK ADA")
else:
    try:
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        R("config.yaml", PASS, "terbaca")
    except Exception as e:
        R("config.yaml", FAIL, f"YAML parse error: {e}")

def key_status(cfg, *path):
    obj = cfg
    for p in path:
        obj = obj.get(p, {}) if isinstance(obj, dict) else {}
    if not isinstance(obj, str):
        return "", "missing"
    if not obj or "YOUR" in obj:
        return obj, "placeholder"
    if len(obj) < 10:
        return obj, "too_short"
    return obj, "ok"

sections = {
    "the_odds_api.api_key":   ("the_odds_api", "api_key"),
    "api_football.api_key":   ("api_football", "api_key"),
    "balldontlie.api_key":    ("balldontlie",  "api_key"),
}

config_fixes_needed = []
for label, path in sections.items():
    val, status = key_status(cfg, *path)
    if status == "ok":
        R(label, PASS, "✓ key ada")
    elif status == "placeholder":
        R(label, WARN, f"placeholder — belum diisi (demo akan dipakai untuk {path[0]})")
        config_fixes_needed.append(path[0])
    else:
        R(label, FAIL, f"MISSING di config.yaml — section '{path[0]}' tidak ada")
        config_fixes_needed.append(path[0])

# Cek leagues section
leagues = cfg.get("leagues", {})
for lk in ["epl", "ucl", "nba", "nhl"]:
    lcfg = leagues.get(lk, {})
    if not lcfg:
        R(f"leagues.{lk}", FAIL, "SECTION TIDAK ADA di config.yaml")
    else:
        sport = lcfg.get("sport", "")
        R(f"leagues.{lk}", PASS if sport else FAIL,
          f"sport={sport}" if sport else "field 'sport' tidak ada")

# ═════════════════════════════════════════════════════════════════════════════
# STEP 3 — Test koneksi API langsung
# ═════════════════════════════════════════════════════════════════════════════
console.print("\n[bold cyan]STEP 3 — Test koneksi API langsung[/]")

def test_url(label, url, params=None, headers=None, timeout=10, check_fn=None):
    try:
        r = requests.get(
            url, params=params, headers=headers or {"User-Agent": UA},
            timeout=timeout
        )
        if r.status_code == 200:
            if check_fn:
                ok, detail = check_fn(r)
                if ok:
                    R(label, PASS, detail)
                else:
                    R(label, WARN, f"HTTP 200 tapi data tidak valid: {detail}")
            else:
                R(label, PASS, f"HTTP 200")
        elif r.status_code == 401:
            R(label, WARN, "HTTP 401 — API key salah/tidak ada")
        elif r.status_code == 404:
            R(label, FAIL, f"HTTP 404 — endpoint tidak ditemukan")
        else:
            R(label, FAIL, f"HTTP {r.status_code}")
    except requests.exceptions.ConnectionError as e:
        R(label, FAIL, f"CONNECTION ERROR — cek koneksi internet\n         {str(e)[:80]}")
    except requests.exceptions.Timeout:
        R(label, FAIL, "TIMEOUT — server tidak merespons dalam 10 detik")
    except Exception as e:
        R(label, FAIL, f"{type(e).__name__}: {str(e)[:80]}")

# 3a. NHL Official API (no key)
def check_nhl(r):
    d = r.json()
    teams = d.get("standings", [])
    if teams:
        name = (teams[0].get("teamName") or {}).get("default", "?")
        return True, f"{len(teams)} teams — sample: {name}"
    return False, "standings kosong"

test_url(
    "NHL Official API (nhle.com)",
    "https://api-web.nhle.com/v1/standings/now",
    check_fn=check_nhl
)

# 3b. NHL Schedule
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
def check_nhl_sched(r):
    d = r.json()
    weeks = d.get("gameWeek", [])
    total = sum(len(day.get("games",[])) for day in weeks)
    return True, f"{total} games ditemukan minggu ini"

test_url(
    "NHL Schedule API",
    f"https://api-web.nhle.com/v1/schedule/{today}",
    check_fn=check_nhl_sched
)

# 3c. Understat EPL
def check_understat(r):
    m = re.search(r"var\s+teamsData\s*=\s*JSON\.parse\('(.+?)'\)", r.text)
    if m:
        return True, "teamsData pattern ditemukan"
    return False, "teamsData pattern TIDAK ditemukan (mungkin struktur berubah)"

test_url(
    "Understat EPL (no key)",
    "https://understat.com/league/EPL/2024",
    check_fn=check_understat
)

# 3d. API-Football
apif_key, apif_status = key_status(cfg, "api_football", "api_key")
if apif_status == "ok":
    def check_apif(r):
        d = r.json()
        errors = d.get("errors", {})
        if errors:
            return False, f"API errors: {errors}"
        resp = d.get("response", [])
        return True, f"{len(resp)} items"
    test_url(
        "API-Football standings (EPL)",
        "https://v3.football.api-sports.io/standings",
        params={"league": 39, "season": 2024},
        headers={"x-rapidapi-key": apif_key, "x-rapidapi-host": "v3.football.api-sports.io"},
        check_fn=check_apif
    )
else:
    R("API-Football", WARN, f"skip test — key {apif_status}")

# 3e. BallDontLie NBA
bdl_key, bdl_status = key_status(cfg, "balldontlie", "api_key")
if bdl_status == "ok":
    def check_bdl(r):
        d = r.json()
        teams = d.get("data", [])
        if teams:
            name = teams[0].get("team", {}).get("full_name", "?")
            return True, f"{len(teams)} teams — sample: {name}"
        return False, "data kosong"
    test_url(
        "BallDontLie NBA standings",
        "https://api.balldontlie.io/v1/standings",
        params={"season": 2024},
        headers={"Authorization": bdl_key},
        check_fn=check_bdl
    )
else:
    R("BallDontLie NBA", WARN, f"skip test — key {bdl_status}")

# 3f. The-Odds-API
odds_key, odds_status = key_status(cfg, "the_odds_api", "api_key")
if odds_status == "ok":
    def check_odds(r):
        d = r.json()
        if isinstance(d, list):
            return True, f"{len(d)} events"
        return False, str(d)[:60]
    test_url(
        "The-Odds-API (EPL odds)",
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds",
        params={"apiKey": odds_key, "regions": "uk", "markets": "h2h"},
        check_fn=check_odds
    )
else:
    R("The-Odds-API", WARN, f"skip test — key {odds_status}")

# ═════════════════════════════════════════════════════════════════════════════
# STEP 4 — Cek cache
# ═════════════════════════════════════════════════════════════════════════════
console.print("\n[bold cyan]STEP 4 — Cek cache folder[/]")

cache_dir = Path(cfg.get("cache", {}).get("dir", "cache"))
if cache_dir.exists():
    files = list(cache_dir.glob("*.json"))
    stale = []
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            age_h = (time.time() - d["ts"]) / 3600
            v = d.get("v", [])
            is_old = age_h > 24
            if is_old:
                stale.append(f.name)
            console.print(
                f"  {'[dim]' if is_old else ''}{f.stem}: "
                f"age={age_h:.1f}h, {len(v)} items"
                f"{'  ← STALE (>24h)' if is_old else ''}"
                f"{'[/]' if is_old else ''}"
            )
        except:
            stale.append(f.name)
    if stale:
        R("cache stale files", WARN, f"{len(stale)} file cache lama ditemukan — akan dihapus")
    else:
        R("cache", PASS, f"{len(files)} files, semua fresh")
else:
    R("cache", INFO, "folder tidak ada — akan dibuat saat pertama run")

# ═════════════════════════════════════════════════════════════════════════════
# STEP 5 — AUTO-FIX
# ═════════════════════════════════════════════════════════════════════════════
console.print("\n[bold cyan]STEP 5 — Auto-Fix[/]")

# Fix 5a: Hapus cache lama
if cache_dir.exists():
    shutil.rmtree(cache_dir)
    R("Cache dihapus", FIX, "folder cache/ dihapus — akan refetch dari API")

# Fix 5b: Patch config.yaml — tambah section yang missing
config_patched = False
if cfg_path.exists():
    # Tambah balldontlie section jika tidak ada
    if "balldontlie" not in cfg:
        cfg["balldontlie"] = {
            "api_key": "YOUR_BALLDONTLIE_KEY_HERE",
            "base_url": "https://api.balldontlie.io/v1"
        }
        config_patched = True

    # Tambah api_football section jika tidak ada
    if "api_football" not in cfg:
        cfg["api_football"] = {
            "api_key": "YOUR_API_FOOTBALL_KEY_HERE",
            "base_url": "https://v3.football.api-sports.io"
        }
        config_patched = True

    # Pastikan the_odds_api punya base_url
    if "the_odds_api" in cfg and "base_url" not in cfg["the_odds_api"]:
        cfg["the_odds_api"]["base_url"] = "https://api.the-odds-api.com/v4"
        config_patched = True

    # Pastikan leagues.nhl ada (NHL tidak butuh key)
    if "leagues" in cfg:
        if "nhl" not in cfg["leagues"]:
            cfg["leagues"]["nhl"] = {
                "name": "NHL", "flag": "🏒", "sport": "hockey",
                "odds_key": "icehockey_nhl"
            }
            config_patched = True
        if "nba" not in cfg["leagues"]:
            cfg["leagues"]["nba"] = {
                "name": "NBA", "flag": "🏀", "sport": "basketball",
                "odds_key": "basketball_nba", "season": 2024
            }
            config_patched = True
        # Fix UCL understat_name jika masih 'UCL' (tidak support)
        if "ucl" in cfg["leagues"]:
            ucl = cfg["leagues"]["ucl"]
            if ucl.get("understat_name", "") == "UCL":
                cfg["leagues"]["ucl"]["understat_name"] = ""  # kosongkan → pakai API-Football
                config_patched = True
                R("UCL understat_name", FIX, "dikosongkan — UCL tidak support Understat")

    if config_patched:
        # Backup config lama
        backup = cfg_path.with_suffix(".yaml.bak")
        shutil.copy(cfg_path, backup)

        # Tulis config baru
        cfg_path.write_text(
            yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8"
        )
        R("config.yaml", FIX, f"dipatch otomatis (backup: config.yaml.bak)")
    else:
        R("config.yaml", PASS, "tidak perlu patch")

# ═════════════════════════════════════════════════════════════════════════════
# RINGKASAN AKHIR
# ═════════════════════════════════════════════════════════════════════════════
console.print()
console.print(Panel("[bold white]RINGKASAN & LANGKAH SELANJUTNYA[/]", style="cyan"))

# Deteksi apakah fetcher.py perlu diganti
fetcher_code = fetcher_path.read_text(encoding="utf-8", errors="ignore") if fetcher_path.exists() else ""
needs_fetcher = "_nhl_stats_live" not in fetcher_code

# Deteksi API mana yang masih butuh key
needs_keys = []
if key_status(cfg, "api_football", "api_key")[1] != "ok":
    needs_keys.append(("API-Football (EPL fixtures + UCL stats)", "https://dashboard.api-football.com/register", "GRATIS 100 req/day"))
if key_status(cfg, "balldontlie", "api_key")[1] != "ok":
    needs_keys.append(("BallDontLie (NBA stats + schedule)",      "https://www.balldontlie.io",                 "GRATIS unlimited"))
if key_status(cfg, "the_odds_api", "api_key")[1] != "ok":
    needs_keys.append(("The-Odds-API (odds semua liga)",          "https://the-odds-api.com/#get-access",       "GRATIS 500 req/month"))

step = 1

if needs_fetcher:
    console.print(f"\n  [bold red]LANGKAH {step} — WAJIB — Replace fetcher.py[/]")
    console.print(
        "  Copy file ini ke folder predictor:\n"
        "  [bold yellow]outputs\\data\\fetcher.py[/] → [bold yellow]data\\fetcher.py[/]\n"
        "\n"
        "  Perintah PowerShell:\n"
        "  [dim]Copy-Item '.\\outputs\\data\\fetcher.py' '.\\data\\fetcher.py' -Force[/]"
    )
    step += 1

console.print(f"\n  [bold green]LANGKAH {step} — NHL & EPL sudah bisa realtime SEKARANG[/]")
console.print(
    "  Setelah replace fetcher.py, jalankan:\n"
    "  [dim]py .\\run_realtime.py --once --league nhl[/]\n"
    "  Lihat apakah muncul: [bold]✅ NHL API: 32 teams (realtime)[/]"
)
step += 1

if needs_keys:
    console.print(f"\n  [bold yellow]LANGKAH {step} — Opsional tapi direkomendasikan — Daftar API keys gratis[/]")
    for name, url, quota in needs_keys:
        console.print(f"  • [bold]{name}[/]\n    Daftar: {url}  ({quota})")
    console.print(
        "\n  Setelah dapat key, isi di config.yaml:\n"
        "  [dim]api_football:\n    api_key: 'isi-key-di-sini'\n"
        "  balldontlie:\n    api_key: 'isi-key-di-sini'[/]"
    )
    step += 1

console.print(f"\n  [bold green]LANGKAH {step} — Jalankan ulang[/]")
console.print(
    "  Cache sudah dihapus otomatis oleh script ini.\n"
    "  Jalankan:\n"
    "  [dim]py .\\run_realtime.py --once[/]"
)

console.print(
    "\n  [bold green]Yang LANGSUNG realtime tanpa key apapun:[/]\n"
    "  ✅ NHL  — NHL Official API  (api-web.nhle.com)\n"
    "  ✅ EPL stats — Understat    (understat.com)\n"
    "\n"
    "  [bold yellow]Yang masih DEMO sampai key diisi:[/]\n"
    "  ⚠  EPL fixtures  — butuh API-Football key\n"
    "  ⚠  UCL semua     — butuh API-Football key\n"
    "  ⚠  NBA semua     — butuh BallDontLie key\n"
    "  ⚠  Odds          — butuh The-Odds-API key\n"
)