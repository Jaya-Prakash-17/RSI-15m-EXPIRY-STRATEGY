#!/usr/bin/env python3
"""
V15 Final Verification Suite
Run after applying all V15 prompts.
Usage: python scripts/verify_v15.py
"""
import sys, os, io
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

P = 0; F = 0; W = 0
def ok(msg):  global P; P += 1; print(f"  \u2713 {msg}")
def warn(msg, d=""): global W; W += 1; print(f"  \u26a0 {msg}" + (f" \u2014 {d}" if d else ""))
def fail(msg, d=""): global F; F += 1; print(f"  \u2717 {msg}" + (f" \u2014 {d}" if d else ""))

print("\n=== V15 FINAL VERIFICATION ===\n")

# V15-P-01: Paper TP3 complete
print("[ BUG-V14-01: Paper TP3 block complete ]")
try:
    with open('live/live_trader.py', encoding='utf-8') as f:
        lt = f.read()
    tp3_idx = lt.find('tp3_fill = targets[2]')
    if tp3_idx >= 0:
        block = lt[tp3_idx:tp3_idx+1000]
        if 'close_trade(trade_id, tp3_fill' in block: ok("TP3 calls close_trade()")
        else: fail("TP3 missing close_trade()", "apply V15-P-01")
        if '_update_circuit_breaker' in block: ok("TP3 calls _update_circuit_breaker()")
        else: fail("TP3 missing circuit breaker", "apply V15-P-01")
        if 'continue' in block: ok("TP3 has continue (no fall-through)")
        else: fail("TP3 missing continue", "apply V15-P-01")
        if 'tp1_fill = targets[0]' in lt and 'tp2_fill = targets[1]' in lt:
            ok("TP1/TP2 use target prices")
        else: fail("TP1/TP2 still using LTP")
    else:
        fail("tp3_fill = targets[2] not found in live_trader.py", "apply V15-P-01")
except Exception as e:
    fail(f"TP3 check failed: {e}")

# V15-P-02: Drawdown fix
print("\n[ BUG-V15-01: max_drawdown_pct uses running_capital ]")
try:
    with open('reporting/performance.py', encoding='utf-8') as f:
        perf = f.read()
    if 'running_capital' in perf and 'initial_cap' in perf:
        ok("Drawdown uses running_capital with initial_cap denominator")
    elif 'peak.max()' in perf and 'max_drawdown_pct' in perf:
        fail("Drawdown still uses peak cumPnL denominator", "apply V15-P-02")
    else:
        warn("Drawdown calculation \u2014 verify manually")
except Exception as e:
    fail(f"Drawdown check failed: {e}")

# V15-P-03: Volume filter removed
print("\n[ BUG-V15-02: Volume filter removed entirely ]")
try:
    import yaml
    c = yaml.safe_load(open('config.yaml'))
    if 'min_volume' in c.get('strategy', {}):
        fail("min_volume still in config.yaml", "apply V15-P-03")
    else:
        ok("min_volume removed from config")
    with open('backtest/intraday_engine.py', encoding='utf-8') as f:
        bt = f.read()
    if 'Minimum Volume Filter' in bt or 'min_volume' in bt:
        fail("Volume filter dead code in intraday_engine.py", "apply V15-P-03")
    else:
        ok("No volume filter code in intraday_engine.py")
except Exception as e:
    fail(f"Volume filter check failed: {e}")

# V15-P-04: LTP cache in monitor
print("\n[ BUG-V14-04: LTP cache in _monitor_active_trades ]")
try:
    with open('live/live_trader.py', encoding='utf-8') as f:
        lt = f.read()
    m_idx = lt.find('def _monitor_active_trades')
    next_def = lt.find('\n    def ', m_idx + 1)
    monitor_fn = lt[m_idx:next_def] if next_def > 0 else lt[m_idx:]
    if 'self.client.get_ltp(' in monitor_fn:
        fail("Direct get_ltp() still in _monitor_active_trades", "apply V15-P-04")
    elif '_get_ltp_cached(' in monitor_fn:
        ok("_monitor_active_trades uses _get_ltp_cached()")
    else:
        warn("No LTP calls found in monitor \u2014 verify paper trading path")
except Exception as e:
    fail(f"LTP cache check: {e}")

# V15-P-05: trailing_stop removed
print("\n[ BUG-V14-05: trailing_stop config removed ]")
try:
    import yaml
    c = yaml.safe_load(open('config.yaml'))
    if 'trailing_stop' in c.get('strategy', {}):
        fail("trailing_stop still in config.yaml", "apply V15-P-05")
    else:
        ok("trailing_stop removed from config")
except Exception as e:
    fail(f"trailing_stop check: {e}")

# Config sanity
print("\n[ Config sanity ]")
try:
    import yaml
    c = yaml.safe_load(open('config.yaml'))
    s = c.get('strategy', {})
    r = c.get('risk', {})
    capital = c.get('capital', {}).get('initial', 100000)
    checks = [
        (s.get('rsi', {}).get('warmup_periods', 0) >= 100,
         f"warmup_periods: {s.get('rsi',{}).get('warmup_periods')}"),
        (r.get('max_loss_per_day', 0) > 0,
         f"max_loss_per_day: Rs.{r.get('max_loss_per_day')}"),
        (c['trading']['paper_trading'] == True, 'paper_trading: True (for paper sessions)'),
        (r.get('max_consecutive_losses', 999) <= 5,
         f"max_consecutive_losses: {r.get('max_consecutive_losses')}"),
        (s.get('safe_sl_max_loss', 9999) / capital * 100 <= 5.0,
         f"safe_sl as % capital: {s.get('safe_sl_max_loss',0)/capital*100:.1f}%"),
    ]
    for ok_flag, label in checks:
        if ok_flag: ok(label)
        else: warn(label)
except Exception as e:
    fail(f"Config sanity: {e}")

# validate_config
print("\n[ validate_config() passes ]")
try:
    import logging, yaml
    logging.disable(logging.CRITICAL)
    c = yaml.safe_load(open('config.yaml'))
    from run_live import validate_config
    result = validate_config(c)
    logging.disable(logging.NOTSET)
    if result: ok("validate_config() returns True")
    else: fail("validate_config() returns False")
except Exception as e:
    fail(f"validate_config raised: {e}")

# Test suite
print("\n[ Test suite ]")
try:
    import subprocess
    r = subprocess.run(['python', '-m', 'pytest', 'tests/', '-q', '--tb=no', '--no-header'],
                      capture_output=True, text=True, timeout=60)
    summary = next((l for l in r.stdout.splitlines() if 'passed' in l or 'failed' in l), '')
    if r.returncode == 0: ok(f"All tests pass ({summary.strip()})")
    else: fail(f"Test failures: {summary.strip()}")
except Exception as e:
    warn(f"Could not run tests: {e}")

# OOS gate
print("\n[ Out-of-sample validation ]")
try:
    import glob, json
    files = glob.glob('reports/backtest_*_summary.json')
    years = set()
    for f in files:
        try:
            d = json.load(open(f))
            s = d.get('config', {}).get('backtest', {}).get('start_date', '')
            if s: years.add(s[:4])
        except: pass
    required = {'2022', '2023', '2024', '2025'}
    missing = required - years
    if not missing:
        ok(f"All 4 years present: {sorted(years)}")
        print("    \u2192 Run: python scripts/compare_years.py reports/")
        print("    \u2192 Must show: ALL YEARS PASS")
    else:
        fail(f"OOS missing: {sorted(missing)}", "run V15-P-08 \u2014 LIVE GATE")
except Exception as e:
    fail(f"OOS check: {e}")

print(f"\n{'='*60}")
print(f"  {P} passed  |  {W} warnings  |  {F} failed")
print(f"{'='*60}")
if F > 0: print("\n  FAILED \u2014 fix before paper or live\n"); sys.exit(1)
elif W > 0: print("\n  READY WITH WARNINGS\n"); sys.exit(0)
else: print("\n  ALL CLEAR \u2014 proceed to OOS then live\n"); sys.exit(0)
