# Backtest

Backtesting engine for historical strategy evaluation.

## Files

| File | Purpose |
|---|---|
| `intraday_engine.py` | **Main backtesting engine.** Replays historical data day-by-day, runs the strategy, simulates entries/exits with full multi-lot support. Handles expiry day detection for NIFTY/BANKNIFTY (Tuesday) and SENSEX (Thursday) post-Sep 2025. |

## How It Works

1. Iterates through each trading day in the date range.
2. Checks if the day is an expiry day for each configured index using `utils.expiry_calendar`.
3. Loads spot + option chain data (with RSI warmup period).
4. Scans all tracked options for RSI breakout signals on 15-minute candles.
5. Enters the best candidate (closest strike to ATM).
6. Manages active trade: partial exits at TP1/TP2/TP3, trailing SL, auto square-off at 15:25.

## Exit Modes

**Multi-lot (3 lots):**
- TP1 → Exit 1 lot, trail SL to `entry_price + buffer`.
- TP2 → Exit 1 lot, trail SL to `TP1_price`.
- TP3 → Exit remaining lot (full close).
- SL → Exit all remaining at stop loss.

**Single-lot:**
- Exit fully at configured target (default: T2).
- SL → Full exit at stop loss.

## Diagnostic Logging

The backtest engine includes enhanced diagnostic logging (using `[DIAG]` prefix) to help identify:
- Why a trade was skipped (e.g., `no_spot_data`, `no_alerts`).
- Pattern results for the day (e.g., `A`, `B`, `C`, `D`).
- RSI and Price values at trigger.

## Key Config Dependencies

| Config Key | Effect |
|---|---|
| `backtest.start_date` / `end_date` | Date range for backtesting |
| `strategy.lots_per_trade` | Number of lots per entry (required to be 3 for multi-lot mode) |
| `strategy.alert_validity` | Max candles to wait for breakout (default: 2) |
| `indices.{INDEX}.lot_size` | Dynamic lot sizes from config |

## Running

```bash
python run_backtest.py
```

Output goes to `reports/` directory (HTML report + JSON summary).
