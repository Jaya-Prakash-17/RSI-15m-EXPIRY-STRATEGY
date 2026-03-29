# tests/verify_residual_fixes.py
"""Quick verification for POST-001 through POST-009 fixes."""
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

passed = failed = 0

def check(name, condition, note=""):
    global passed, failed
    if condition:
        print(f"  ✓ {name}")
        passed += 1
    else:
        print(f"  ✗ {name}{(' — ' + note) if note else ''}")
        failed += 1

print("\n=== POST-FIX VERIFICATION ===\n")

# POST-001: Closed candle cutoff in live trader
with open('live/live_trader.py', encoding='utf-8') as f:
    lt = f.read()
check("POST-001a: closed_candle_cutoff defined",
      "closed_candle_cutoff" in lt)
check("POST-001b: option candle lag guard removed",
      "option candle ({current_candle_time}) behind spot" not in lt and
      "option candle behind spot" not in lt)
check("POST-001c: timedelta subtraction from last_candle_time",
      "last_candle_time - timedelta" in lt)

# POST-001 backtest
with open('backtest/intraday_engine.py', encoding='utf-8') as f:
    bt = f.read()
check("POST-001d: backtest uses t - timedelta",
      "t - timedelta" in bt or "timedelta(seconds=1)" in bt)

# POST-002: Double partial exit prevention
check("POST-002: target_order_ids nulled on qty_filled=0",
      "target_ids[idx] = None" in lt or "target_ids[tp_level - 1] = None" in lt)

# POST-003: No get_order_list in live trader
check("POST-003: get_order_list removed",
      "get_order_list" not in lt)

# POST-004: Defensive lot_size lookup
check("POST-004: defensive .get() for lot_size",
      "self.config['indices'].get(underlying" in bt or
      "config['indices'].get(underlying" in bt)

# POST-005: daily_reconcile no bad import
with open('daily_reconcile.py', encoding='utf-8') as f:
    dr = f.read()
check("POST-005: config_loader import removed",
      "from core.config_loader" not in dr)

# POST-006: gitignore has state files
with open('.gitignore', encoding='utf-8') as f:
    gi = f.read()
check("POST-006a: strategy_state.json in gitignore",
      "strategy_state.json" in gi)
check("POST-006b: pending_entries.json in gitignore",
      "pending_entries.json" in gi)

# POST-007: KILL_SWITCH_FILE at module level
lines = lt.split('\n')
module_level_kill = any(
    'KILL_SWITCH_FILE' in l and not l.startswith(' ') and not l.startswith('\t')
    for l in lines[:50]
)
check("POST-007: KILL_SWITCH_FILE at module level", module_level_kill)

# POST-008: No datetime.min
check("POST-008: datetime.min removed",
      "datetime.min" not in lt)

# POST-009: Closed candle debug log
check("POST-009: RSI check closed candle log",
      "RSI check on CLOSED candle" in lt or "closed candle" in lt.lower())

# HISTORICAL-001: Historical lot sizes file exists
try:
    from utils.historical_lot_sizes import get_historical_lot_size
    from datetime import date as _d
    lot_check = (
        get_historical_lot_size('NIFTY', _d(2023, 1, 1)) == 75 and
        get_historical_lot_size('BANKNIFTY', _d(2024, 11, 19)) == 25 and
        get_historical_lot_size('BANKNIFTY', _d(2024, 11, 20)) == 35
    )
    check("HISTORICAL-001: Historical lot sizes correct", lot_check)
except Exception as e:
    check("HISTORICAL-001: Historical lot sizes", False, str(e))

# HISTORICAL-002: Backtest engine uses historical lot sizes
check("HISTORICAL-002: intraday_engine imports historical_lot_sizes",
      "from utils.historical_lot_sizes import get_historical_lot_size" in bt)
check("HISTORICAL-002: intraday_engine calls get_historical_lot_size",
      "get_historical_lot_size" in bt)

# HISTORICAL-003: NSE holidays cover 2020
with open('utils/nse_calendar.py', encoding='utf-8') as f:
    nc = f.read()
check("HISTORICAL-003: NSE holidays include 2020",
      "2020" in nc and ("2020-02-21" in nc or "2020-03-10" in nc))
check("HISTORICAL-003: NSE holidays include 2024",
      "2024" in nc and "2024-01-26" in nc)

# HISTORICAL-004: SENSEX guard in backtest engine
check("HISTORICAL-004: SENSEX pre-launch guard in backtest",
      "sensex_not_launched_yet" in bt or "SENSEX_WEEKLY_LAUNCH_DATE" in bt or
      "2023, 5, 1" in bt)

print(f"\n{'='*35}")
print(f"  {passed} passed  |  {failed} failed")
print(f"{'='*35}\n")
sys.exit(0 if failed == 0 else 1)
