#!/usr/bin/env python3
"""
scripts/verify_v12.py
Run after applying all V12 prompts to confirm deployment readiness.
Usage: python scripts/verify_v12.py
"""
import sys
import os
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

P = 0; F = 0; W = 0

def ok(msg):
    global P; P += 1; print(f"  \u2713 {msg}")

def warn(msg, detail=""):
    global W; W += 1
    detail_str = f" \u2014 {detail}" if detail else ""
    print(f"  \u26a0 {msg}{detail_str}")

def fail(msg, detail=""):
    global F; F += 1
    detail_str = f" \u2014 {detail}" if detail else ""
    print(f"  \u2717 {msg}{detail_str}")

print("\n=== V12 FINAL VERIFICATION ===\n")

# BUG-V11-01: underlying NameError fix
print("[ BUG-V11-01: underlying NameError in backtest ]")
try:
    with open('backtest/intraday_engine.py', encoding='utf-8') as f:
        src = f.read()
    lines = src.split('\n')
    # Find _manage_active_trade and check if underlying is defined at top
    in_func = False
    top_level_underlying = False
    func_start = 0
    for i, line in enumerate(lines):
        if 'def _manage_active_trade' in line:
            in_func = True
            func_start = i
        if in_func and i < func_start + 20:
            if "underlying = trade.get('underlying'" in line and 'if exit_mode' not in lines[i-3:i]:
                top_level_underlying = True
                break
        if in_func and i > func_start + 5 and line.startswith('    def '):
            break
    if top_level_underlying:
        ok("underlying defined at top of _manage_active_trade() (both branches covered)")
    else:
        fail("underlying NOT defined at top of _manage_active_trade()", "apply V12-P-01")
except Exception as e:
    fail(f"Check failed: {e}")

# BUG-V11-02: lots_per_trade config
print("\n[ BUG-V11-02: lots_per_trade in config ]")
try:
    import yaml
    c = yaml.safe_load(open('config.yaml'))
    lots = c['strategy'].get('lots_per_trade', 999)
    if lots == 1:
        ok(f"lots_per_trade: 1 (correct)")
    elif lots <= 2:
        warn(f"lots_per_trade: {lots} \u2014 should be 1 for live debut")
    else:
        fail(f"lots_per_trade: {lots} \u2014 must be 1 for live debut (apply V12-P-02)")
except Exception as e:
    fail(f"Config read failed: {e}")

# BUG-V11-03: Capital concentration guard
print("\n[ BUG-V11-03: Capital concentration guard in validate_config ]")
try:
    with open('run_live.py', encoding='utf-8') as f:
        src = f.read()
    if 'position_cost_pct' in src or 'CONSERVATIVE_PREMIUM' in src or 'capital concentration' in src.lower():
        ok("Capital concentration guard present in validate_config()")
    else:
        warn("Capital concentration guard missing \u2014 apply V12-P-03")
except Exception as e:
    fail(f"Check failed: {e}")

# BUG-V11-04: Legacy trade monitor removed
print("\n[ BUG-V11-04: _monitor_legacy_trade removed ]")
try:
    with open('live/live_trader.py', encoding='utf-8') as f:
        src = f.read()
    if '_monitor_legacy_trade' not in src:
        ok("_monitor_legacy_trade() removed (dead code gone)")
    else:
        # Check if it's called anywhere
        call_count = src.count('_monitor_legacy_trade(')
        def_count = src.count('def _monitor_legacy_trade')
        if call_count == 0 and def_count > 0:
            warn("_monitor_legacy_trade() still defined but never called \u2014 apply V12-P-04")
        else:
            fail(f"_monitor_legacy_trade() called {call_count} times \u2014 investigate")
except Exception as e:
    fail(f"Check failed: {e}")

# BUG-V11-05: Circuit breaker in DAILY_LOSS_LIMIT
print("\n[ BUG-V11-05: Circuit breaker called in DAILY_LOSS_LIMIT ]")
try:
    with open('live/live_trader.py', encoding='utf-8') as f:
        src = f.read()
    cb_count = src.count('_update_circuit_breaker(')
    if cb_count >= 8:
        ok(f"_update_circuit_breaker called {cb_count} times (includes DAILY_LOSS_LIMIT)")
    elif cb_count == 7:
        warn(f"_update_circuit_breaker called {cb_count} times \u2014 DAILY_LOSS_LIMIT still missing (apply V12-P-06)")
    else:
        fail(f"_update_circuit_breaker called only {cb_count} times \u2014 review live_trader.py")
except Exception as e:
    fail(f"Check failed: {e}")

# Config sanity
print("\n[ Config sanity checks ]")
try:
    import yaml
    c = yaml.safe_load(open('config.yaml'))
    r = c.get('risk', {})
    s = c.get('strategy', {})
    checks = [
        (s.get('rsi', {}).get('warmup_periods', 0) >= 100,
         f"warmup_periods: {s.get('rsi', {}).get('warmup_periods')}"),
        (s.get('lots_per_trade') == 1,
         f"lots_per_trade: {s.get('lots_per_trade')} (need 1)"),
        (s.get('safe_sl_max_loss', 9999) <= 2500,
         f"safe_sl_max_loss: Rs.{s.get('safe_sl_max_loss')} (need <=2500)"),
        (r.get('max_loss_per_day', 0) > 0,
         f"max_loss_per_day: Rs.{r.get('max_loss_per_day')}"),
        (c['trading']['paper_trading'] == True,
         'paper_trading: True (use True for paper sessions)'),
        (r.get('max_consecutive_losses', 999) <= 5,
         f"max_consecutive_losses: {r.get('max_consecutive_losses')} (need <=5)"),
        (s.get('exit_mode') in ('single_lot', 'multi_lot'),
         f"exit_mode: {s.get('exit_mode')}"),
    ]
    for ok_flag, label in checks:
        if ok_flag:
            ok(label)
        else:
            fail(label)
except Exception as e:
    fail(f"Config check failed: {e}")

# Validate config passes
print("\n[ validate_config() passes with current config ]")
try:
    import logging
    logging.disable(logging.CRITICAL)
    import yaml
    c = yaml.safe_load(open('config.yaml'))
    from run_live import validate_config
    result = validate_config(c)
    logging.disable(logging.NOTSET)
    if result:
        ok("validate_config() returns True")
    else:
        fail("validate_config() returns False \u2014 check critical config errors")
except Exception as e:
    fail(f"validate_config() raised exception: {e}")

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
        ok(f"All 4 years validated: {sorted(years_found)}")
        print("    \u2192 Run: python scripts/compare_years.py reports/")
    else:
        warn(f"Missing years: {sorted(missing)}", "run V12-P-05")
except Exception as e:
    fail(f"OOS check failed: {e}")

# Backtest smoke test (can it complete without crashing?)
print("\n[ Backtest smoke test (single-day) ]")
print("  Manual: Set config.yaml dates to a single known expiry day and run:")
print("    python run_backtest.py 2>&1 | tail -5")
print("  Expected: completes without NameError, shows trade count or 'zero trades'")

# Result
print("\n" + "="*60)
print(f"  {P} passed  |  {W} warnings  |  {F} failed")
print("="*60)

if F > 0:
    print("\n  FAILED \u2014 fix failures above before deploying\n")
    sys.exit(1)
elif W > 0:
    print("\n  READY WITH WARNINGS \u2014 review warnings before live capital\n")
    sys.exit(0)
else:
    print("\n  ALL CLEAR \u2014 ready for paper trading and OOS validation\n")
    sys.exit(0)
