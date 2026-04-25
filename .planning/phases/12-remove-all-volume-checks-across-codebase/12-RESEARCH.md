# Phase 12: Remove all volume checks across codebase - Research

**Date:** 2026-04-19
**Status:** ## RESEARCH COMPLETE

## Objective
Identify and document every location where volume is used as a filter or sorting criterion in the codebase, to ensure total removal as requested by the user.

## Findings

### 1. Configuration
- **File:** `config.yaml`
- **Line:** 69
- **Entry:** `min_volume_candles_pct: 0.3`
- **Action:** Remove this entry or mark it as deprecated (user wants it removed).

### 2. Backtest Engine
- **File:** `backtest/intraday_engine.py`
- **`__init__` (Lines 20-26):** Loads `min_volume_candles_pct` and logs a warning if it's too loose.
- **`_is_option_data_tradeable` (Lines 247-255):** Rejects options if the percentage of zero-volume candles on expiry day exceeds the threshold.
- **`process_expiry_day` (Lines 549, 557):**
    - Captures `volume` in the candidate dictionary.
    - Sorts candidates by `(dist, -volume)`, using volume as a tie-breaker for same distance strikes.
- **Action:**
    - Remove volume check in `_is_option_data_tradeable`.
    - Remove volume-based tie-breaker in `process_expiry_day`.
    - Remove the warning in `__init__`.

### 3. Live Trader
- **File:** `live/live_trader.py`
- **`_update_option_universe` (Lines 576-579):** Comment mentioning "Issue #8: Minimum Volume Filter".
- **`_process_strategy_logic` (Line 941):** Captures `volume` in `alert_candidates`.
- **`_process_strategy_logic` (Line 990 [approx]):** Sorts candidates by `(dist, -volume)`.
- **Action:**
    - Remove volume-based tie-breaker in candidate sorting.
    - Remove volume capture in `alert_candidates`.
    - Clean up outdated comments.

### 4. Data Fetchers / Utils
- **Files:** `core/groww_client.py`, `scripts/download_spot_15m_independent.py`, `utils/candle_builder.py`.
- **Finding:** These files handle the fetching, parsing, and resampling of volume data.
- **Recommendation:** Although the user said "remove em all", in the context of trading bots, "volume checks" refers to the *logical gates and filters*. Removing the `volume` field from the OHLCV data structure itself is high-risk and provides no benefit (it's part of the standard exchange response). I will focus on removing the **checks and filters** while keeping the data structure intact for future-proofing and standard compatibility.

## Validation Architecture
- **Criteria 1:** Backtest engine must run without `min_volume_candles_pct` in config.
- **Criteria 2:** `IntradayEngine` must not filter out options due to low volume (verified by running a backtest on a known low-volume instrument).
- **Criteria 3:** `live_trader.py` candidate selection must only rely on distance (or other non-volume factors).
- **Criteria 4:** No warnings about volume filters should appear in logs.
