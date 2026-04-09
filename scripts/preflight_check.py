#!/usr/bin/env python3
"""
Pre-flight check for RSI-15m Expiry Breakout Bot.
Usage: python scripts/preflight_check.py
Exit code 0 = ready, 1 = has failures.
"""
import sys, os, yaml
from datetime import datetime

# P-V8-P-03: Ensure stdout handles emojis on Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

passed = failed = warnings = 0

def ok(msg):   global passed;   passed += 1;   print(f"  ✅ {msg}")
def warn(msg): global warnings; warnings += 1; print(f"  ⚠️  {msg}")
def fail(msg): global failed;   failed += 1;   print(f"  ❌ {msg}")

print("\n" + "="*55)
print("  RSI BOT PRE-FLIGHT CHECK")
print("="*55)

# ── 1. CONFIGURATION ──────────────────────────────────────
print("\n[ Configuration ]")
config = None
try:
    with open('config.yaml') as f:
        config = yaml.safe_load(f)
        ok("config.yaml loaded")

        # DEBUG: print(f"DEBUG: config keys: {list(config.keys())}")

        rsi      = config.get('strategy', {}).get('rsi', {})
        warmup   = rsi.get('warmup_periods', 0)
        min_c    = rsi.get('min_candles_for_signal', 0)
        period   = rsi.get('period', 0)
        lots     = config.get('strategy', {}).get('lots_per_trade', 0)
        max_loss = config.get('risk', {}).get('max_loss_per_day', 0)
        paper    = config.get('trading', {}).get('paper_trading', True)

    if paper:
        ok("paper_trading: true (safe mode)")
    else:
        warn("paper_trading: false — REAL MONEY")

    if warmup >= 100:
        ok(f"warmup_periods: {warmup} ✓")
    else:
        fail(f"warmup_periods: {warmup} — signals will never fire! Set to 100+")

    if min_c <= warmup:
        ok(f"min_candles_for_signal: {min_c} ✓")
    else:
        fail(f"min_candles_for_signal ({min_c}) > warmup ({warmup}) — impossible!")

    if 1 <= lots <= 3:
        ok(f"lots_per_trade: {lots}")
    else:
        warn(f"lots_per_trade: {lots} — verify this is intentional")

    ok(f"max_loss_per_day: ₹{max_loss:,}")

except FileNotFoundError:
    fail("config.yaml not found")
except Exception as e:
    import traceback
    fail(f"Config section error: {e}")
    print(f"DEBUG: Traceback:\n{traceback.format_exc()}")

# ── 2. VALIDATE CONFIG ────────────────────────────────────
print("\n[ Config validation ]")
try:
    import logging
    logging.disable(logging.CRITICAL)
    from run_live import validate_config
    result = validate_config(config) if config else False
    logging.disable(logging.NOTSET)
    if result:
        ok("validate_config() passes")
    else:
        fail("validate_config() rejected config — check window times")
except Exception as e:
    fail(f"validate_config error: {e}")

# ── 3. IMPORTS ────────────────────────────────────────────
print("\n[ Imports ]")
try:
    from live.live_trader import LiveTrader
    ok("live_trader imports cleanly")
except ImportError as e:
    fail(f"Import error: {e}")
except Exception as e:
    warn(f"Import warning (may be ok): {e}")

# ── 4. GROWW API ──────────────────────────────────────────
print("\n[ Groww API ]")
client = None
try:
    from core.groww_client import GrowwClient
    client = GrowwClient()
    balance = client.get_balance()
    if balance is not None and balance >= 0:
        ok(f"Connected — margin: ₹{balance:,.0f}")
        # Rough minimum: 1 lot NIFTY @ ₹100 premium
        min_needed = (config or {}).get('strategy', {}).get('lots_per_trade', 1) * 65 * 100
        if balance < min_needed:
            warn(f"Balance ₹{balance:,.0f} may be tight for {lots} lot(s)")
    elif balance == 0:
        warn("Balance ₹0 — verify margin availability")
    else:
        fail("get_balance() returned None — check GROWW_API_KEY in .env")
except Exception as e:
    fail(f"Groww API error: {e}")

# ── 5. MARKET DATA ────────────────────────────────────────
print("\n[ Market data ]")
try:
    if client:
        ltp = client.get_ltp('NIFTY')
        if ltp and ltp > 0:
            ok(f"NIFTY LTP: ₹{ltp:,.2f}")
        else:
            warn("NIFTY LTP unavailable (ok if market is closed)")
    else:
        warn("Skipped — Groww not connected")
except Exception as e:
    warn(f"LTP check: {e} (ok if market closed)")

# ── 6. TELEGRAM ───────────────────────────────────────────
print("\n[ Telegram ]")
try:
    from utils.telegram_notifier import TelegramNotifier
    notifier = TelegramNotifier()
    if notifier.enabled:
        ok(f"Configured ({len(notifier.chat_ids)} chat(s))")
    else:
        warn("Not configured — add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env")
except Exception as e:
    warn(f"Telegram: {e}")

# ── 7. EXPIRY CALENDAR ────────────────────────────────────
print("\n[ Expiry calendar ]")
try:
    from utils.expiry_calendar import run_startup_assertions
    run_startup_assertions()
    ok("Startup assertions pass")
except AssertionError as e:
    fail(f"Calendar broken: {e}")
except Exception as e:
    warn(f"Calendar check: {e}")

# ── 8. TEST SUITE ─────────────────────────────────────────
print("\n[ Tests ]")
try:
    import subprocess
    r = subprocess.run(
        ['python', '-m', 'pytest', 'tests/', '-q', '--tb=no', '--no-header'],
        capture_output=True, text=True, timeout=30
    )
    summary = next((l for l in r.stdout.splitlines() if 'passed' in l or 'failed' in l), '')
    if r.returncode == 0:
        ok(f"All tests pass ({summary.strip()})")
    else:
        fail(f"Test failures: {summary.strip()} — run pytest -v for details")
except Exception as e:
    warn(f"Could not run tests: {e}")

# ── RESULT ────────────────────────────────────────────────
print("\n" + "="*55)
print(f"  {passed} passed  |  {warnings} warnings  |  {failed} failed")
print("="*55)

if failed > 0:
    print("\n  ❌ NOT READY — fix the failures above before trading\n")
    sys.exit(1)
elif warnings > 0:
    print("\n  ⚠️  READY WITH WARNINGS — review warnings before trading\n")
    sys.exit(0)
else:
    print("\n  ✅ ALL CLEAR — start the bot: python run_live.py\n")
    sys.exit(0)
