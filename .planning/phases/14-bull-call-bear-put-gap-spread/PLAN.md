# Plan: Gap Directional Spread Backtest

1.  **[x] Script Creation**: Create `strangle_backtest/run_gap_spread.py` (we'll reuse the `strangle_backtest` directory since it's meant for these standalone daily automated backtests).
2.  **[x] Logic**:
    *   [x] Initialize `DataManager` and `PerformanceReporter`.
    *   [x] Iterate over calendar days from `2020-01-01` to `2025-12-31`.
    *   [x] For each day:
        *   [x] Determine gap by looking back 1-5 days to find the last trading day's 15:15 close, and compare it to today's 09:15 open.
        *   [x] Determine spread type (Bull Call vs Bear Put).
        *   [x] Get 09:45 Spot Price to compute ATM strike.
        *   [x] Execute ATM Buy and 5-strike OTM Sell (2 legs).
        *   [x] Get 15:15 exit prices.
    *   [x] Aggregate P&L and metrics.
3.  **[x] Reporting**: Call `PerformanceReporter` with `custom_prefix="GAP_SPREAD_NIFTY_5Yr"`.
