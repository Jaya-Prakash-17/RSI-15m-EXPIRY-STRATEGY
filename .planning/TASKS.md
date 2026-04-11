# Active Task Tracker — RSI-15m Bot V16
> Place at: `docs/TASKS.md`
> Update after every session.

## 🔴 BLOCKED (do these first)

### V16-P-01: Negative alert_range guard
**File:** `strategy/expiry_rsi_breakout.py`
**Function:** `check_signal()`
**Fix:** Add before alert state is set:
```python
alert_range = alert_candle['high'] - alert_candle['low']
if alert_range < self.min_alert_range:
    self.logger.warning(f"[{symbol}] Skipping alert: corrupt/flat candle (range={alert_range:.2f})")
    return None
```
**Config key:** `strategy.min_alert_range_points: 0.5` (already in config.yaml ✅)
**Evidence:** 8 trades in 2020-2025 had inverted targets (T1 < entry_price)
**Test:** `pytest tests/test_business_logic.py::test_corrupt_candle_flat_range_rejected`

---

### V16-P-02: OOS Year-by-Year Validation
**Command:** `python scripts/run_oos_validation.py 2022 2023 2024 2025`
**Then:** `python scripts/compare_years.py reports/`
**Pass criteria (ALL must pass):**
- PF ≥ 1.1
- Max DD > −35%
- Win Rate 25%–70%
- No single year > 40% of total PnL
**This is the final deployment gate.**

---

## 🟡 QUEUED (do after P-01 and P-02)

### V16-P-03: Test config RSI period fix
**File:** `tests/test_business_logic.py`
**Issue:** `make_config()` fallback uses `period=11` but verify it actually matches
**Test:** `pytest tests/test_business_logic.py::test_make_config_uses_period_11`

### V16-P-04: Position-scaled slippage
**Already in config.yaml:** `slippage_model: position_scaled` ✅
**Verify it's actually used in `reporting/performance.py`** → check the `slip_model == 'position_scaled'` branch executes

### V16-P-05: Option data quality guard
**Already implemented:** `_is_option_data_tradeable()` in `backtest/intraday_engine.py` ✅
**Verify:** config key `strategy.min_volume_candles_pct: 0.5` is read correctly

### V16-P-06: Remove dead `same_candle_guard` code
**Status:** Architectural property — management starts T+2 by design
**Action:** Search codebase for `same_candle_guard`, confirm it's dead code, delete

### V16-P-07: avg_capital_deployed in stats
**File:** `reporting/performance.py`
**Check:** `stats['avg_capital_deployed']` uses `trades_df['cost'].mean()` → confirm `cost` column populated

### V16-P-08: TP-before-SL for trailed SL above entry
**File:** `backtest/intraday_engine.py`, `_manage_active_trade()`
**Already implemented:** `trailed_sl_above_entry` check exists ✅
**Verify:** test with candle where high ≥ target AND low ≤ trailed_sl > entry

### V16-P-09: verify_v16.py
**Create:** `tests/verify_v16.py` covering all V16 patches
**Template:** mirror structure of `tests/verify_residual_fixes.py`

---

## ✅ COMPLETED (V15 and earlier)

| ID | Fix |
|----|-----|
| V15-P-01 | TP3 paper mode block |
| V15-P-02 | Drawdown calculation with initial capital |
| V15-P-03 | LTP 1s TTL cache |
| V14 | Atomic writes, paper TP fills at limit price |
| V13 | verify_residual_fixes.py |
| V12 | Capital concentration guard, NameError fix |
| V11 | Per-index trade lock, circuit breaker, RSI vectorization |
| V10 | Safe SL recalc, gap-below-SL, historical lot sizes in engine |
| V9 | Historical lot sizes, same-candle SL architectural fix |
| V8 | Crash recovery |

---

## LIVE DEBUT CHECKLIST
```
[ ] V16-P-01 patched and tested
[ ] compare_years.py: ALL 2022/2023/2024/2025 PASS
[ ] 20 full paper trading sessions completed
[ ] Zero unhandled exceptions across all paper sessions
[ ] preflight_check.py: all green
[ ] Telegram verified each session
[ ] Kill switch tested (touch /tmp/rsi_bot_kill)

Then set config:
  lots_per_trade: 1
  exit_mode: single_lot
  single_lot_exit_target: 2
  safe_sl_max_loss: 2000
  max_loss_per_day: 3000
  paper_trading: false
```
