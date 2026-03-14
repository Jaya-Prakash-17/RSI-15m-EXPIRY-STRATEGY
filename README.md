# RSI-15 Minute Expiry Breakout Bot

Intraday Index Options Strategy based on RSI(14) breakout on 15-minute candles, designed for Indian markets (NSE/BSE). Includes both a backtesting engine and a live trading bot with Telegram alerts.

## Strategy Summary

| Parameter | Value |
|---|---|
| **Strategy** | Expiry RSI Breakout (15-Minute) |
| **Instruments** | Index Options only (NIFTY, BANKNIFTY, SENSEX) |
| **Trade Day** | Expiry day only (`trade_only_on_expiry: true`) |
| **Candle Timeframe** | 15 minutes |
| **RSI Period** | 14 (Wilder's RSI) |
| **RSI Threshold** | 60 (alert on cross above) |
| **Entry** | Price breaks the high of alert candle (SL-M BUY order) |
| **Stop Loss** | Alert candle low − 1 point |
| **T1** | Entry + 1× alert candle range |
| **T2** | Entry + 2× alert candle range |
| **T3** | Entry + 3× alert candle range |

### Expiry Schedule

| Index | Expiry Day | Type |
|---|---|---|
| NIFTY | Tuesday (from Sep 2025) | Weekly |
| BANKNIFTY | Last Tuesday of month (from Sep 2025) | Monthly |
| SENSEX | Thursday | Weekly |

### Exit Modes

**Multi-lot (3 lots):** TP1 → exit 1 lot + trail SL, TP2 → exit 1 lot + trail SL, TP3 → exit remaining

**Single-lot:** Exit fully at configured target (default: T2 via `single_lot_exit_target: 2`)

## Project Structure

```
RSI-15m-EXPIRY-STRATEGY/
├── config.yaml              # All strategy, risk, and trading parameters
├── .env.example             # Template for environment variables (copy to .env)
├── run_backtest.py          # Entry point: run backtesting
├── run_live.py              # Entry point: run live/paper trading
│
├── strategy/                # Trading strategy implementation
│   └── expiry_rsi_breakout.py   # RSI breakout signal logic (ALERT → ENTRY)
│
├── backtest/                # Backtesting engine
│   └── intraday_engine.py       # Replays historical data, simulates trades
│
├── live/                    # Live trading engine
│   └── live_trader.py           # Real-time trading loop with Telegram alerts
│
├── core/                    # Infrastructure
│   ├── groww_client.py          # Groww broker API client
│   ├── logger.py                # Logging setup
│   └── retry_decorator.py       # Retry with exponential backoff
│
├── data/                    # Data layer
│   ├── data_manager.py          # Central data hub (cache + serve)
│   ├── historical_downloader.py # Bulk CSV downloader
│   ├── spot/                    # Spot index candle CSVs
│   └── derivatives/             # Option chain candle CSVs
│
├── execution/               # Order management (live only)
│   ├── order_manager.py         # Place/modify/cancel broker orders
│   └── trade_tracker.py         # Trade state persistence
│
├── reporting/               # Backtest reports
│   └── performance.py           # HTML + JSON report generator
│
└── utils/                   # Shared utilities
    ├── telegram_notifier.py     # Telegram trade alerts (9 message types)
    ├── trade_logger.py          # CSV trade audit log
    ├── nse_calendar.py          # NSE holiday calendar
    ├── trading_day_checker.py   # API-based trading day verification
    └── chart_visualizer.py      # Candlestick chart generator
```

> Each folder has its own `README.md` with detailed file descriptions.

## Quick Start

### 1. Setup Environment

```bash
# Clone the repo
git clone https://github.com/Jaya-Prakash-17/RSI-15m-EXPIRY-STRATEGY.git
cd RSI-15m-EXPIRY-STRATEGY

# Install dependencies
pip install pandas numpy pyyaml requests python-dotenv

# Copy environment template and fill in your credentials
cp .env.example .env
```

### 2. Run Backtest

```bash
# Edit config.yaml to set backtest date range, then:
python run_backtest.py
```

Results are saved to `reports/` (HTML report + JSON summary).

### 3. Run Live Trading (Paper Mode)

```bash
# Paper trading is ON by default (config.yaml: paper_trading: true)
python run_live.py
```

### 4. Test Telegram Alerts

```bash
python -c "from dotenv import load_dotenv; load_dotenv(); from utils.telegram_notifier import TelegramNotifier; TelegramNotifier().test_connection()"
```

## Configuration

All parameters are in `config.yaml`. Key sections:

| Section | What it controls |
|---|---|
| `strategy.rsi` | RSI period (14), threshold (60), warmup (100 candles) |
| `strategy.exit_mode` | `multi_lot` (3 lots, partial exits) or `single_lot` |
| `strategy.trade_only_on_expiry` | `true` = trade only on expiry days |
| `strategy.single_lot_exit_target` | Which TP exits in single-lot mode (1/2/3) |
| `trading.paper_trading` | `true` = simulated, `false` = real money |
| `trading.window` | Trading hours (start, end, auto_square_off) |
| `risk.max_loss_per_day` | Daily loss limit in ₹ |
| `capital.initial` | Starting capital for backtest |
| `indices.{INDEX}.lot_size` | Current lot size (NIFTY: 65, BANKNIFTY: 30) |

## Environment Variables (`.env`)

| Variable | Required | Purpose |
|---|---|---|
| `GROWW_API_KEY` | Yes | Groww broker API JWT token |
| `GROWW_API_SECRET` | Yes | Groww broker API secret |
| `GROWW_MOCK_MODE` | No | Set to `True` for offline testing |
| `TELEGRAM_BOT_TOKEN` | No | Telegram bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | No | Your Telegram chat ID |

## Telegram Alerts

The live bot sends real-time Telegram notifications for:

| Alert | When |
|---|---|
| 🤖 Bot Started | On initialization |
| 🔔 Trade Setup Alert | RSI breakout detected (full entry/SL/target details) |
| ⏰ Setup Expired | Validity window passed without trigger |
| ✅ Trade Entered | Order filled (reference card with risk) |
| 🎯 Target Hit | TP1/TP2/TP3 reached (profit + new SL) |
| 🛑 Stop Loss Hit | SL triggered (loss + daily P&L) |
| 🔔 Square Off | End-of-day forced close |
| 🚨 Daily Loss Limit | Max loss breached — trading stopped |
| 📋 Daily Summary | End of session stats |

## License

Private repository. Not for public distribution.
