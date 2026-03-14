# Backtest

Backtesting engine for historical strategy evaluation.

## Files

| File | Purpose |
|---|---|
| `intraday_engine.py` | **Main backtesting engine.** Replays historical data day-by-day, runs the strategy, simulates entries/exits with full multi-lot support (partial exits at TP1/TP2/TP3 with trailing SL). Handles expiry day detection for NIFTY (Tuesday), BANKNIFTY (last Tuesday of month), and SENSEX (Thursday). |

## How It Works

1. Iterates through each trading day in the date range
2. Checks if the day is an expiry day for each configured index
3. Loads spot + option chain data (with RSI warmup period)
4. Scans all tracked options for RSI breakout signals
5. Enters the best candidate (closest strike, highest volume)
6. Manages active trade: partial exits at TP1/TP2/TP3, trailing SL, auto square-off at 15:25

## Exit Modes

**Multi-lot (3 lots):**
- TP1 → Exit 1 lot, trail SL by alert range
- TP2 → Exit 1 lot, trail SL by alert range
- TP3 → Exit remaining lot (full close)
- SL → Exit all remaining at stop loss

**Single-lot:**
- Exit fully at configured target (default: T2)
- SL → Full exit at stop loss

## Key Config Dependencies

| Config Key | Effect |
|---|---|
| `backtest.start_date` / `end_date` | Date range for backtesting |
| `capital.initial` | Starting capital for position sizing |
| `strategy.exit_mode` | `multi_lot` or `single_lot` |
| `strategy.lots_per_trade` | Number of lots per entry (default: 3) |
| `strategy.trade_only_on_expiry` | `true` = expiry days only, `false` = all trading days |
| `indices.{INDEX}.lot_size` | Lot size from config (no hardcoded values) |

## Running

```bash
python run_backtest.py
```

Output goes to `reports/` directory (HTML report + JSON summary).
