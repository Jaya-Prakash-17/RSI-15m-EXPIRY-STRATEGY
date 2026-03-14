# Data

Data management layer — downloading, caching, and serving market data.

## Files

| File | Purpose |
|---|---|
| `data_manager.py` | **Central data hub.** Serves spot and derivative candle data to both backtest and live engines. Handles caching (in-memory + CSV), symbol building, expiry lookups, and trading symbol resolution. Abstracts away the difference between historical (file-based) and live (API-based) data sources. |
| `historical_downloader.py` | **Bulk data downloader.** Downloads historical spot and derivative candle data from the Groww API and saves to CSV files in `data/spot/` and `data/derivatives/`. Used for populating backtest data. |
| `bot_trades.json` | **Trade state persistence.** JSON file used by `TradeTracker` to persist active trade state across bot restarts. Automatically managed — do not edit manually. |

## Directory Structure

```
data/
├── spot/                    # Spot index candle data (15-min)
│   ├── NIFTY_15m.csv
│   └── BANKNIFTY_15m.csv
├── derivatives/             # Option chain candle data (15-min)
│   ├── NIFTY/
│   │   └── 2026/
│   │       ├── NSE-NIFTY-07Jan26-23500-CE_15m.csv
│   │       └── ...
│   └── BANKNIFTY/
│       └── 2026/
│           └── ...
├── data_manager.py
├── historical_downloader.py
└── bot_trades.json
```

## Data Flow

```
Backtest mode:
  CSV files → DataManager → IntradayEngine

Live mode:
  Groww API → DataManager (cache) → LiveTrader
```
