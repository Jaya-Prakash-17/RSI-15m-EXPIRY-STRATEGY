# Latest Fix Prompt Guide

> **Generated**: 2026-04-18 | **Status**: Pre-patch | **Priority**: P0

---

## 1. BUG LIST — Current Codebase Vulnerabilities

### 🔴 P0 — Must Fix Before Live

- **BUG-001: Backtest RSI Look-Ahead Bias (Off-By-One)**
  - **File**: `backtest/intraday_engine.py:321,418-422`
  - **Root Cause**: `calculate_wilder_rsi(numpy_array)` returns `rsi_values` (length N-1) without the pandas alignment offset (`iloc[n:] = rsi_values[n-1:]`). Engine indexes `symbol_rsis[curr_idx]` which maps to `rsi_values[curr_idx]`, but the correct mapping is `rsi_values[curr_idx - 1]`.
  - **Impact**: Every backtest RSI reading uses the NEXT candle's close price. Live/backtest parity is broken. All historical PnL is unreliable.
  - **Severity**: CRITICAL — invalidates all backtest results.

- **BUG-002: Volume Filter Too Loose (`0.9`)**
  - **File**: `config.yaml:63`
  - **Root Cause**: `min_volume_candles_pct: 0.9` accepts options where up to 90% of candles have zero volume.
  - **Impact**: Backtest fills at theoretical OHLC prices that don't exist in real order books. Live trading on these options would result in partial/no fills and massive slippage.
  - **Severity**: HIGH — overstates backtest profitability.

### 🟡 P1 — Fix Before OOS Re-Validation

- **BUG-003: SENSEX Enabled Without Historical Data Verification**
  - **File**: `config.yaml:34-37` (uncommitted change)
  - **Root Cause**: SENSEX uncommented in config but no verification that SENSEX option data exists in `data/derivatives/SENSEX/` for 2023–2025 backtest range.
  - **Impact**: Silent no-data skips inflate "days processed" count without contributing trades, or worse, stale data generates phantom trades.

- **BUG-004: `batch_calculate_rsi` Uses `calculate_wilder_rsi` Without Specifying Return Type**
  - **File**: `strategy/expiry_rsi_breakout.py:232`
  - **Root Cause**: `batch_calculate_rsi` passes dict values (could be Series or array) to `calculate_wilder_rsi`. If a pandas Series is passed, the return is a pandas Series with correct alignment. If a numpy array, the return has the off-by-one issue. Code works correctly in live (Series path) but would fail if batch mode ever received numpy arrays.
  - **Impact**: Latent parity bug. Live uses `calculate_latest_rsi` (safe), batch mode is only used defensively.

### 🟢 P2 — Hardening

- **BUG-005: `min_candles_for_signal` Check Bypassed in Backtest**
  - **File**: `backtest/intraday_engine.py:426`
  - **Root Cause**: Engine calls `strategy.check_signal(symbol, row, rsi_values=...)` without `price_history`, so the `min_candles_for_signal` guard in the strategy (line 494) is always skipped (`price_history is None`).
  - **Impact**: Backtest may generate signals from candles with insufficient history that live would reject. Minor — RSI cache already requires `curr_idx >= 1`.

- **BUG-006: Warmup `min 100` Override Ignores Config Intent**
  - **File**: `backtest/intraday_engine.py:242`
  - **Root Cause**: `warmup_candles = max(warmup_candles, 100)` forces 100-candle minimum even when config sets `warmup_periods: 33`. Safe but potentially confusing — config intent is overridden silently.
  - **Impact**: None (protective). But config documentation should note this floor.

---

## 2. PROMPT GUIDE — Exact `/gsd:execute` Prompts

Execute these in order. Each prompt is self-contained.

---

### PATCH 1: Fix RSI Look-Ahead in Backtest Engine

```
/gsd:execute Fix the RSI off-by-one look-ahead bias in backtest/intraday_engine.py.

PROBLEM: calculate_wilder_rsi() returns a numpy array of length N-1 when given
a numpy array input. The pandas Series path correctly offsets via
rsi_series.iloc[n:] = rsi_values[n-1:], but the numpy path returns rsi_values
directly. The engine at line 421-422 uses symbol_rsis[curr_idx] which maps to
rsi_values[curr_idx], but the CORRECT value for candle curr_idx is
rsi_values[curr_idx - 1].

EXACT CHANGES REQUIRED:
1. In backtest/intraday_engine.py, line 419: Change guard from
   `if curr_idx < 1 or curr_idx >= len(symbol_rsis): continue`
   to
   `if curr_idx < 2 or curr_idx - 1 >= len(symbol_rsis): continue`

2. Line 421: Change
   `curr_rsi = symbol_rsis[curr_idx]`
   to
   `curr_rsi = symbol_rsis[curr_idx - 1]`

3. Line 422: Change
   `prev_rsi = symbol_rsis[curr_idx - 1]`
   to
   `prev_rsi = symbol_rsis[curr_idx - 2]`

VERIFICATION: After patching, write a unit test in tests/test_rsi_alignment.py
that:
(a) Creates a known price series as both pandas Series and numpy array
(b) Computes RSI via calculate_wilder_rsi for both
(c) Asserts that for any candle index k, the RSI value used in the backtest
    engine path (numpy[k-1]) matches the pandas Series path (series.iloc[k])
(d) Run the test and confirm PASS.

DO NOT modify strategy/expiry_rsi_breakout.py. Only patch the engine and add test.
```

---

### PATCH 2: Tighten Volume Filter

```
/gsd:execute Fix the volume filter in config.yaml and add a config validation guard.

EXACT CHANGES:
1. config.yaml line 63: Change min_volume_candles_pct from 0.9 to 0.3

2. backtest/intraday_engine.py: In the __init__ method, after loading config,
   add a startup warning if min_volume_candles_pct > 0.5:
   ```python
   vol_filter = self.config['strategy'].get('min_volume_candles_pct', 0.5)
   if vol_filter > 0.5:
       self.logger.warning(
           f"[CONFIG WARNING] min_volume_candles_pct={vol_filter} is dangerously loose. "
           f"Options with >{vol_filter*100:.0f}% zero-volume candles will be traded. "
           f"Recommended: 0.3 for realistic backtesting."
       )
   ```

DO NOT change any other config values. Only the volume filter.
```

---

### PATCH 3: Verify SENSEX Data Availability

```
/gsd:execute Add a pre-backtest data availability check for all configured indices.

In backtest/intraday_engine.py, in the run() method, after the existing
_validate_data_paths loop (line 62), add a check:

For each index in config['indices']:
  - Count the number of derivative CSV files in data/derivatives/{index}/
    across the year range [start_date.year, end_date.year]
  - If count == 0, log a CRITICAL warning:
    f"[DATA CHECK] {index}: NO derivative data found for {year_range}. "
    f"This index will generate ZERO trades. Remove from config or download data."
  - If count < 50 (per year), log a WARNING about sparse data.

Also: In config.yaml, RE-COMMENT the SENSEX section unless SENSEX data
exists in data/derivatives/SENSEX/ for the backtest date range. Check first.

This prevents phantom indices inflating the "days processed" count.
```

---

### PATCH 4: Pass `price_history` in Backtest Signal Check

```
/gsd:execute Fix the bypassed min_candles_for_signal check in backtest engine.

In backtest/intraday_engine.py line 426, the call:
  signal = strategy.check_signal(symbol, row, rsi_values=(curr_rsi, prev_rsi))

does not pass price_history, so strategy's min_candles_for_signal guard is
skipped. Change to:

  # Build price history up to current candle for min_candles check
  price_slice = df['close'].iloc[:curr_idx + 1]
  signal = strategy.check_signal(
      symbol, row,
      price_history=price_slice,
      rsi_values=(curr_rsi, prev_rsi)
  )

This ensures the backtest respects the same min_candles_for_signal filter
as live trading. Note: price_slice is a view (no copy), so performance
impact is negligible.
```

---

### PATCH 5: Re-Run Full OOS Validation

```
/gsd:execute Run the complete 5-year OOS validation with PATCHED code.

Steps:
1. Restore backtest config to 5-year range:
   start_date: '2020-01-01'
   end_date: '2025-12-31'
   offline_mode: true

2. Run scripts/run_oos_validation.py (or equivalent year-by-year runner)

3. Run scripts/compare_years.py on the new reports

4. Compare trade counts against baseline:
   - Old (buggy EWM, strict filter): 589 trades
   - Expected after patches: 650-900 trades (correct RSI + realistic filter)
   - If still >1200: investigate further

5. Save new FINAL_REPORTS and commit with message:
   "fix: RSI alignment + volume filter patch — re-validated OOS"
```

---

## 3. EXECUTION ORDER

```
PATCH 1 (RSI Fix)  →  PATCH 2 (Volume Filter)  →  PATCH 3 (SENSEX Check)
       ↓
PATCH 4 (Price History)  →  PATCH 5 (Full Re-Validation)
```

> Patches 1–4 are independent code fixes. Patch 5 is the integration test that validates all fixes together. Do not deploy live until Patch 5 produces a passing OOS table.
