# Phase 05: Data & Time Hardening - Validation Strategy

## Quality Dimensions (Nyquist)

### 1. Exchange Sync (Dimension 1)
- **Constraint**: `feed()` must not receive `None` timestamps in live mode.
- **Verification**: `grep` check on `live_trader.py` calls to `candle_builder.feed`.
- **Unit Test**: Test `CandleBuilder.feed` with various timestamps to ensure boundary alignment is correct regardless of current `datetime.now()`.

### 2. Continuity Hard-Gate (Dimension 4)
- **Constraint**: Gaps > 15m must trigger `abort_signal_generation`.
- **Verification**: Mock a 30-minute data gap and verify that `live_trader` sends a critical alert and pauses execution.

### 3. Cache Integrity (Dimension 2)
- **Constraint**: LTP cache must be empty after `_reconnect_resync`.
- **Verification**: Insert dummy data into `_ltp_cache`, trigger simulated reconnect, and assert `cache` is empty.

### 4. Semantic Safety (Dimension 7)
- **Constraint**: `alert_validity` variable must no longer exist in the codebase.
- **Verification**: `grep -r "alert_validity" .` should return zero matches (except in historical logs/reports).

---
*Generated: 2026-04-19 - Phase 05 Validation Strategy*
