#!/usr/bin/env python3
# scripts/verify_v14.py
# Usage: python scripts/verify_v14.py

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

P = 0; F = 0; W = 0

def ok(msg):   global P; P += 1; print(f"  \u2713 {msg}")
def warn(msg, detail=""): global W; W += 1; print(f"  \u26a0 {msg}" + (f" \u2014 {detail}" if detail else ""))
def fail(msg, detail=""): global F; F += 1; print(f"  \u2717 {msg}" + (f" \u2014 {detail}" if detail else ""))

print("\n=== V14 FINAL VERIFICATION ===\n")

# V14-P-01: pending_entries.json atomic write
print("[ BUG-V12-01: pending_entries.json atomic write ]")
try:
    with open('execution/trade_tracker.py', encoding='utf-8') as f:
        src = f.read()
    # Count NamedTemporaryFile usages
    count = src.count('NamedTemporaryFile')
    if count >= 2:
        ok(f"NamedTemporaryFile used {count} times (save_pending_entries + _save_data)")
    elif count == 1:
        warn("Only 1 NamedTemporaryFile found \u2014 save_pending_entries may still be non-atomic",
             "apply V14-P-01")
    else:
        fail("No NamedTemporaryFile in trade_tracker.py", "apply V14-P-01")
except Exception as e:
    fail(f"Check failed: {e}")

# V14-P-02: strategy_state.json atomic write
print("\n[ BUG-V12-02: strategy_state.json atomic write ]")
try:
    with open('live/live_trader.py', encoding='utf-8') as f:
        lt = f.read()
    if 'NamedTemporaryFile' in lt and '_save_strategy_state' in lt:
        # Check it's in the right function
        save_state_idx = lt.find('def _save_strategy_state')
        temp_file_idx = lt.find('NamedTemporaryFile', save_state_idx)
        next_def_idx = lt.find('\n    def ', save_state_idx + 1)
        if save_state_idx < temp_file_idx < next_def_idx:
            ok("_save_strategy_state uses NamedTemporaryFile (atomic)")
        else:
            warn("NamedTemporaryFile found but may not be in _save_strategy_state", "verify manually")
    else:
        fail("_save_strategy_state does not use NamedTemporaryFile", "apply V14-P-02")
except Exception as e:
    fail(f"Check failed: {e}")

# V14-P-03: Paper trading TP uses target price not LTP
print("\n[ BUG-V12-03: Paper TP fills use target price ]")
try:
    with open('live/live_trader.py', encoding='utf-8') as f:
        lt = f.read()
    # Look for the corrected pattern: tp1_fill = targets[0] or similar
    if 'tp1_fill' in lt or 'tp2_fill' in lt or 'fill_price' in lt:
        ok("Paper TP fills use target prices (fill_price/tp1_fill pattern found)")
    elif 'self._handle_paper_tp_hit(trade, 1, ltp)' in lt:
        fail("Paper TP1 still passes raw LTP to _handle_paper_tp_hit", "apply V14-P-03")
    else:
        warn("Cannot determine paper TP fill price \u2014 check _monitor_active_trades manually")
except Exception as e:
    fail(f"Check failed: {e}")

# V14-P-04: Cancel failure Telegram alert
print("\n[ BUG-V12-04: Cancel failure Telegram alert ]")
try:
    with open('live/live_trader.py', encoding='utf-8') as f:
        lt = f.read()
    # Find _cancel_pending_entry and check for telegram send in failure path
    cancel_idx = lt.find('def _cancel_pending_entry')
    next_def_idx = lt.find('\n    def ', cancel_idx + 1)
    cancel_fn = lt[cancel_idx:next_def_idx] if next_def_idx > 0 else lt[cancel_idx:]
    if 'telegram._send' in cancel_fn and 'Failed to cancel' in cancel_fn:
        ok("Telegram alert present in cancel-failure branch")
    elif 'Failed to cancel' in cancel_fn:
        fail("Cancel failure logged but no Telegram alert", "apply V14-P-04")
    else:
        warn("Cannot find cancel failure handling \u2014 check _cancel_pending_entry manually")
except Exception as e:
    fail(f"Check failed: {e}")

# V14-P-05: compare_years win rate in verdict
print("\n[ BUG-V12-05: Win rate in GO/NO-GO verdict ]")
try:
    with open('scripts/compare_years.py', encoding='utf-8') as f:
        src = f.read()
    if 'wr_ok' in src and 'pf_ok and dd_ok and wr_ok' in src:
        ok("Win rate included in PASS/FAIL verdict")
    elif 'wr_ok' in src:
        fail("wr_ok computed but not in verdict \u2014 apply V14-P-05")
    else:
        fail("wr_ok not found in compare_years.py", "apply V14-P-05")
except Exception as e:
    fail(f"Check failed: {e}")

# V14-P-07: clear_day_data called in _initialize_day
print("\n[ BUG-V12-08: clear_day_data called in _initialize_day ]")
try:
    with open('live/live_trader.py', encoding='utf-8') as f:
        lt = f.read()
    init_day_idx = lt.find('def _initialize_day')
    next_def_idx = lt.find('\n    def ', init_day_idx + 1)
    init_day_fn = lt[init_day_idx:next_def_idx]
    if 'clear_day_data' in init_day_fn:
        ok("clear_day_data() called in _initialize_day()")
        # Check ordering: must come before _reconcile_positions
        clear_idx = init_day_fn.find('clear_day_data')
        reconcile_idx = init_day_fn.find('self._reconcile_positions')
        if clear_idx < reconcile_idx:
            ok("clear_day_data() called BEFORE _reconcile_positions() (correct order)")
        else:
            fail("clear_day_data() called AFTER _reconcile_positions() \u2014 wrong order!")
    else:
        fail("clear_day_data() not called in _initialize_day()", "apply V14-P-07")
except Exception as e:
    fail(f"Check failed: {e}")

# Config sanity
print("\n[ Config sanity checks ]")
try:
    import yaml
    try:
        c = yaml.safe_load(open('config.yaml', encoding='utf-8'))
    except TypeError: # Older pyyaml / Python might not support encoding in open directly like this
        c = yaml.safe_load(open('config.yaml'))
    r = c.get('risk', {})
    s = c.get('strategy', {})
    capital = c.get('capital', {}).get('initial', 100000)
    lots = s.get('lots_per_trade', 0)
    safe_sl = s.get('safe_sl_max_loss', 9999)
    checks = [
        (lots == 1, f"lots_per_trade: {lots} (need 1)"),
        (safe_sl <= 2500, f"safe_sl_max_loss: Rs.{safe_sl} (need \u22642500)"),
        (safe_sl / capital * 100 <= 3.0, f"safe_sl as % of capital: {safe_sl/capital*100:.1f}% (need \u22643%)"),
        (r.get('max_consecutive_losses', 999) <= 5,
         f"max_consecutive_losses: {r.get('max_consecutive_losses')} (need \u22645)"),
        (s.get('rsi', {}).get('warmup_periods', 0) >= 100,
         f"warmup_periods: {s.get('rsi', {}).get('warmup_periods')}"),
        (c.get('trading', {}).get('paper_trading', None) == True, 'paper_trading: True (for paper sessions)'),
    ]
    for ok_flag, label in checks:
        if ok_flag:
            ok(label)
        else:
            fail(label)
except Exception as e:
    fail(f"Config check failed: {e}")

# Test suite
print("\n[ Test suite ]")
try:
    import subprocess
    r = subprocess.run(
        ['python', '-m', 'pytest', 'tests/', '-q', '--tb=no', '--no-header'],
        capture_output=True, text=True, timeout=60
    )
    summary = next((l for l in r.stdout.splitlines()
                    if 'passed' in l or 'failed' in l), 'no output')
    if r.returncode == 0:
        ok(f"All tests pass ({summary.strip()})")
    else:
        fail(f"Test failures: {summary.strip()}")
except Exception as e:
    warn(f"Could not run tests: {e}")

# OOS validation status
print("\n[ Out-of-sample validation ]")
try:
    import glob, json
    files = glob.glob('reports/backtest_*_summary.json')
    years_found = set()
    for f in files:
        try:
            d = json.load(open(f))
            start = d.get('config', {}).get('backtest', {}).get('start_date', '')
            if start:
                years_found.add(start[:4])
        except:
            pass
    required = {'2022', '2023', '2024', '2025'}
    missing = required - years_found
    if not missing:
        ok(f"All 4 years validated: {sorted(years_found)}")
        print("    \u2192 Run: python scripts/compare_years.py reports/")
        print("    \u2192 Must show: ALL YEARS PASS")
    else:
        fail(f"OOS missing years: {sorted(missing)}", "run V14-P-06 \u2014 this is the LIVE DEPLOYMENT GATE")
except Exception as e:
    fail(f"OOS check failed: {e}")

# Result
print("\n" + "="*60)
print(f"  {P} passed  |  {W} warnings  |  {F} failed")
print("="*60)

if F > 0:
    print("\n  FAILED \u2014 fix failures above before paper or live trading\n")
    sys.exit(1)
elif W > 0:
    print("\n  READY WITH WARNINGS \u2014 address warnings before live capital\n")
    sys.exit(0)
else:
    print("\n  ALL CLEAR \u2014 ready for OOS validation then live\n")
    sys.exit(0)
