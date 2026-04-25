# Phase 12: Remove all volume checks across codebase - Validation Strategy

**Date:** 2026-04-19
**Phase:** 12

## Verification Gaps
- Low-volume option rejection: Previously, options with many zero-volume candles were rejected. We need to verify they are now accepted and traded.
- Candidate sorting: Distance is the primary sort, volume was the secondary. We need to verify sorting still works correctly without volume.

## Must-Haves (Goal-Backward Verification)
- [ ] No volume filter logic in `backtest/intraday_engine.py`.
- [ ] No volume filter logic in `live/live_trader.py`.
- [ ] No `min_volume_candles_pct` in `config.yaml`.
- [ ] Sorting of candidates works correctly without volume as a tie-breaker.
- [ ] Backtest succeeds for periods that previously failed due to low volume (e.g., historical outliers).

## Automated Checks
- `grep -r "min_volume_candles_pct" .` should find no active usage in Python code.
- `grep -r "zero_vol_pct" .` should find no active usage.
- Unit test for `IntradayEngine._is_option_data_tradeable` (if exists) should be updated.

## Manual Verification (UAT cases)
1. Run `run_backtest.py` with a config that previously triggered volume warnings.
2. Inspect log output for `Filtered low_volume_XX%` messages - none should appear.
3. Verify candidate sorting in debug logs - distances should be the sole factor.
