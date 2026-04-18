# Phase 05: Data & Time Hardening - Research

## Current State Analysis

### 1. Candle Binning Logic (`utils/candle_builder.py`)
- **Method**: `feed(symbol, ltp, timestamp=None)`
- **Line 75**: `now = timestamp or datetime.now()` — This is the primary point of local-clock dependency.
- **Line 76**: `boundary = self._get_boundary_time(now)` — Standardizes boundary to 15m intervals.
- **Issue**: `live_trader.py` (Line 630) currently calls `feed(symbol, ltp)` without passing a timestamp, causing the builder to use the system clock.

### 2. LTP Polling & Time (`live/live_trader.py`)
- **Method**: `_poll_option_ltps` (Lines 611-656)
- **Batch Results**: `batch_results = self.client.get_batch_ltp(symbols)` returns a dict of `{symbol: price}`.
- **Timestamp Discovery**: `GrowwClient.get_ltp` (in `core/groww_client.py`) extracts only the price from the API response.
- **Drift Risk**: There is no exchange-side timestamp passed into `CandleBuilder`. If the polling loop stalls, the local `datetime.now()` will bin the LTP into the wrong candle.

### 3. Cache Management (`live/live_trader.py`)
- **Caches**: `self._candle_cache` and `self._ltp_cache` are used for PNL and gap validation.
- **Persistence**: `_candle_cache` is populated by `_get_closed_df` which reads from the builder.
- **Issue**: On reconnect, these caches must be explicitly cleared to prevent "stale price" triggers.

### 4. Alert Validity Unit Mismatch
- **Config**: `config.yaml` (Line 54) describes it as "Minutes".
- **Logic**: `strategy/expiry_rsi_breakout.py` (Line 400) uses it as "Candles" against `state['age']`.
- **Impact**: Multiplier error (1 candle = 15 minutes). A setting of 15 (intended minutes) currently results in standard 225-minute validity.

### 5. Fill Price Protection (Bug #8)
- **Current Logic**: `fill_price = status.get('fill_price') or pending.get('trigger_price')` in multiple places in `live_trader.py`.
- **Issue**: If the broker returns `0` or `None`, it silently reverts to the trigger price.

## Technical Approach for Implementation

### Data Sync (SYNC-01)
- Modify `GrowwClient.get_ltp` to return `(price, timestamp)` if available in the API response, or capture the "Exchange Time" if provided by the broker's heartbeat/LTP.
- Update `live_trader.py` to pass the exchange-aware timestamp to `CandleBuilder.feed`.

### Continuity (CONT-01)
- Implement a `_validate_continuity(self, symbol, new_bar_time)` check in `CandleBuilder`.
- Compare `new_bar_time` with the `datetime` of the last bar in `self.bars[symbol]`.
- Trigger warning/abort if `delta > 15m`.

### Cache & Reconnect (RECO-01)
- Identify `_reconnect_resync` handler in `live_trader.py`.
- Ensure `self._ltp_cache.clear()` and `self._candle_cache.clear()` are the first actions.

### Semantic Cleanup (CONF-01)
- Bulk rename `alert_validity` to `alert_validity_candles` across the project.
- Update `run_backtest.py`, `run_live.py`, `config.yaml`, and strategy logic.

---
*Generated: 2026-04-19 - Phase 05 Research*
