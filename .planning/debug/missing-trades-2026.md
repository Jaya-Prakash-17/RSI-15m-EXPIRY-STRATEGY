# Debug Session: Missing Trades in 2026

**Date:** 2026-04-19
**Symptom:** Only 2 trades generated in 2026 backtest, expected 50-70.
**Status:** ## RESOLVED

## Hypothesis 1: Capital/Cost Mismatch (CONFIRMED)
- **Details:** Found that the engine was skipping trades with "Position too large" because `running_capital` had dropped to ~8,000 INR from 200,000 INR.
- **Root Cause:** A logic error in `IntradayEngine.process_expiry_day` where `active_trade` was reset to `None` at every candle interval, regardless of whether the trade was closed.
- **Impact:**
  1. Trades were "orphaned" after 1st candle.
  2. Entry cost was subtracted but never credited back on exit (since management stopped).
  3. After a few orphans, capital hit the floor, and all new trades were skipped by the risk guard.

## Hypothesis 2: RSI Warmup (NOT THE CAUSE)
- **Evidence:** Diagnostics showed alerts were firing (alerts=24), so data was loaded and RSI was calculating.

## Hypothesis 3: Lot Size Lookup (NOT THE CAUSE)
- **Evidence:** Historical lot sizes for 2026 are correctly defined.

## Resolution
- Fixed indentation/placement of `active_trade = None` in `backtest/intraday_engine.py`.
- Trades will now be managed until a legitimate `CLOSED` status (SL or TP) is reached.
- Capital will no longer leak from orphans.

## Verification
- User to run `run_backtest.py` again. Expected trade count: 50-70.
