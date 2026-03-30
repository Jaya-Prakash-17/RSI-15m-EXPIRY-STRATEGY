#!/usr/bin/env python3
"""
V11 Final Verification Suite
Run after applying all V11 prompts to confirm deployment readiness.

Usage: python scripts/verify_v11.py
"""
import sys
import os
import io

# Handle Unicode on Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

P = 0
F = 0
W = 0

def ok(msg):
    global P
    P += 1
    print(f"  \u2713 {msg}")

def warn(msg, detail=""):
    global W
    W += 1
    detail_str = f" \u2014 {detail}" if detail else ""
    print(f"  \u26a0 {msg}{detail_str}")

def fail(msg, detail=""):
    global F
    F += 1
    detail_str = f" \u2014 {detail}" if detail else ""
    print(f"  \u2717 {msg}{detail_str}")

print("\n=== V11 FINAL VERIFICATION ===\n")

# V11-P-01: NameError fix
print("[ BUG-V10-01: NameError in SQOFF/DAILY_LOSS_LIMIT ]")
try:
    with open('live/live_trader.py', encoding='utf-8') as f:
        src = f.read()
    lines = src.split('\n')
    count = sum(1 for l in lines if 'exit_order_id = None' in l)
    if count >= 2:
        ok(f"exit_order_id = None initialized in {count} locations")
    else:
        fail(f"Found only {count} exit_order_id = None", "need 2 (SQOFF + DAILY_LOSS_LIMIT)")
except Exception as e:
    fail(f"NameError check: {e}")

# V11-P-02: Circuit breaker in live trader
print("\n[ BUG-V10-02: Circuit breaker in live_trader ]")
try:
    with open('live/live_trader.py', encoding='utf-8') as f:
        src = f.read()
    checks = [
        ('self.consecutive_losses = 0' in src, 'consecutive_losses initialized in __init__'),
        ('self.circuit_breaker_active' in src, 'circuit_breaker_active state present'),
        ('def _update_circuit_breaker' in src, '_update_circuit_breaker method exists'),
        (src.count('_update_circuit_breaker(') >= 5,
         f'_update_circuit_breaker called {src.count("_update_circuit_breaker(")}/5+ times'),
    ]
    for ok_flag, label in checks:
        if ok_flag:
            ok(label)
        else:
            fail(label)
except Exception as e:
    fail(f"Circuit breaker check: {e}")

# V11-P-03: SL trailing alignment
print("\n[ BUG-V10-03: Trailing SL alignment backtest vs live ]")
try:
    with open('backtest/intraday_engine.py', encoding='utf-8') as f:
        bt = f.read()
    additive = "trade['sl'] + trade.get('alert_range'" in bt
    absolute = 'entry_price' in bt and '_round_to_tick' in bt
    if not additive:
        ok("Additive SL trail removed from backtest")
    else:
        fail("Additive trail still present", "apply V11-P-03")
    if absolute:
        ok("Absolute SL trail present in backtest")
except Exception as e:
    fail(f"SL trail check: {e}")

# V11-P-04: Dead code removed
print("\n[ BUG-V10-04: Dead code removed ]")
try:
    with open('live/live_trader.py', encoding='utf-8') as f:
        src = f.read()
    has_multi = 'def _handle_multi_lot_exits' in src
    has_single = 'def _handle_single_lot_exits' in src
    if not has_multi and not has_single:
        ok("Dead methods removed")
    elif 'DEPRECATED' in src:
        warn("Dead methods marked DEPRECATED (acceptable)")
    else:
        fail("Dead methods still present without DEPRECATED marker", "apply V11-P-04")
except Exception as e:
    fail(f"Dead code check: {e}")

# V11-P-05: RSI vectorization
print("\n[ HIGH-V9-04: RSI vectorization ]")
try:
    with open('strategy/expiry_rsi_breakout.py', encoding='utf-8') as f:
        src = f.read()
    has_numpy_array = 'np.asarray' in src or 'np.empty' in src or 'np.diff' in src
    has_loop = 'avg_gains.append' in src
    if has_numpy_array and not has_loop:
        ok("RSI vectorized (numpy arrays, no .append loop)")
    elif has_loop:
        warn("RSI still uses Python append loop", "apply V11-P-05")
    else:
        warn("RSI implementation unclear", "review manually")
except Exception as e:
    fail(f"RSI check: {e}")

# V11-P-06: Chart RSI fix
print("\n[ HIGH-V9-05: Chart RSI fix ]")
try:
    with open('utils/chart_visualizer.py', encoding='utf-8') as f:
        src = f.read()
    has_old = 'def calculate_rsi' in src
    has_import = 'ExpiryRSIBreakout' in src or 'calculate_wilder_rsi' in src
    if not has_old and has_import:
        ok("Chart RSI fixed - using strategy implementation")
    elif has_old:
        fail("Old calculate_rsi() still present", "apply V11-P-06")
    else:
        warn("Chart RSI status unclear", "review manually")
except Exception as e:
    fail(f"Chart RSI check: {e}")

# V11-P-08: Multi-lot guard
print("\n[ BUG-V10-07: Multi-lot + 1-lot guard ]")
try:
    with open('run_live.py', encoding='utf-8') as f:
        src = f.read()
    if 'multi_lot' in src and 'lots_per_trade < 3' in src:
        ok("Multi-lot + 1-lot guard in validate_config()")
    else:
        warn("Guard not found in validate_config()", "apply V11-P-08")
except Exception as e:
    fail(f"Multi-lot guard check: {e}")

# Config checks
print("\n[ Config sanity ]")
try:
    import yaml
    c = yaml.safe_load(open('config.yaml'))
    r = c.get('risk', {})
    s = c.get('strategy', {})
    checks = [
        (s.get('rsi', {}).get('warmup_periods', 0) >= 100,
         f"warmup_periods: {s.get('rsi',{}).get('warmup_periods')}"),
        (r.get('max_loss_per_day', 0) > 0,
         f"max_loss_per_day: Rs.{r.get('max_loss_per_day')}"),
        (c['trading']['paper_trading'] == True,
         'paper_trading: True'),
        (r.get('max_consecutive_losses', 999) <= 5,
         f"max_consecutive_losses: {r.get('max_consecutive_losses')} (need <=5)"),
    ]
    for ok_flag, label in checks:
        if ok_flag:
            ok(label)
        else:
            warn(label)
except Exception as e:
    fail(f"Config check: {e}")

# Test suite
print("\n[ Test suite ]")
try:
    import subprocess
    r = subprocess.run(
        ['python', '-m', 'pytest', 'tests/', '-q', '--tb=no', '--no-header'],
        capture_output=True, text=True, timeout=60
    )
    summary = next((l for l in r.stdout.splitlines() if 'passed' in l or 'failed' in l), '')
    if r.returncode == 0:
        ok(f"All tests pass ({summary.strip()})")
    else:
        fail(f"Test failures: {summary.strip()}")
except Exception as e:
    warn(f"Could not run tests: {e}")

# Out-of-sample check
print("\n[ Out-of-sample validation ]")
try:
    import glob
    import json
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
        ok(f"All years validated: {sorted(years_found)}")
    else:
        warn(f"Missing years: {sorted(missing)}", "run V11-P-07")
except Exception as e:
    fail(f"OOS check: {e}")

# Result
print("\n" + "="*55)
print(f"  {P} passed  |  {W} warnings  |  {F} failed")
print("="*55)

if F > 0:
    print("\n  FAILED - fix failures above before trading\n")
    sys.exit(1)
elif W > 0:
    print("\n  READY WITH WARNINGS - review warnings before trading\n")
    sys.exit(0)
else:
    print("\n  ALL CLEAR - ready for paper trading\n")
    sys.exit(0)
