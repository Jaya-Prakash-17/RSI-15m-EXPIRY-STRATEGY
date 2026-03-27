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
| **Targets (TP)** | T1 (1x), T2 (2x), T3 (3x) alert candle range |

### Expiry Schedule (Current)

| Index | Expiry Day | Type |
|---|---|---|
| NIFTY | Tuesday (since Sep 2025) | Weekly |
| BANKNIFTY | Last Tuesday of month (since Sep 2025) | Monthly |
| SENSEX | Thursday (since Sep 2025) | Weekly |

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
│   ├── groww_client.py          # Groww broker API client (BSE/NSE support)
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
├── scripts/                 # Operational scripts
│   ├── setup_service.sh         # Linux systemd service installer
│   ├── rsi-bot.service          # systemd unit file template
│   └── paper_trading_checklist.md # 20-session pre-live SOP
│
├── reporting/               # Backtest reports
│   └── performance.py           # HTML + JSON report generator
│
├── tests/                   # Test suite
│   └── test_integration.py      # Integration and regression tests
│
└── utils/                   # Shared utilities
    ├── telegram_notifier.py     # Telegram alerts (Multi-chat + Owner only)
    ├── trade_logger.py          # CSV trade audit log
    ├── nse_calendar.py          # NSE/BSE holiday calendar
    ├── trading_day_checker.py   # API-based trading day verification
    └── chart_visualizer.py      # Candlestick chart generator
```

## Quick Start

### 1. Setup Environment

```bash
# Clone the repo
git clone https://github.com/Jaya-Prakash-17/RSI-15m-EXPIRY-STRATEGY.git
cd RSI-15m-EXPIRY-STRATEGY

# Install dependencies
pip install -r requirements.txt

# Copy environment template and fill in your credentials
cp .env.example .env
```

### 2. Run Backtest

```bash
# Edit config.yaml to set backtest date range, then:
python run_backtest.py
```

### 3. Run Live Trading (Paper Mode)

```bash
# Initialize paper trading checklist (scripts/paper_trading_checklist.md)
python run_live.py
```

## Configuration (config.yaml)

- `trading.window.auto_square_off`: Times after 15:20 (e.g., 15:25) are allowed but trigger a warning (Groww MIS cutoff starts at 15:20).
- `risk.max_loss_per_day`: Daily loss limit enforced per bot session.
- `strategy.alert_validity`: Candles allowed for breakout after alert (recommended: 2).

## Environment Variables (`.env`)

| Variable | Required | Purpose |
|---|---|---|
| `GROWW_API_KEY` | Yes | Groww broker API JWT token |
| `GROWW_API_SECRET` | Yes | Groww broker API secret |
| `TELEGRAM_BOT_TOKEN` | Yes | Telegram bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | Comma-separated list of IDs for alerts |
| `TELEGRAM_OWNER_ID` | Yes | Owner-specific ID for shutdown/critical alerts |

## Telegram Alerts

The live bot sends real-time Telegram notifications for:
- 🤖 **Bot Started**: On initialization.
- 🔔 **Trade Setup Alert**: RSI breakout detected.
- ✅ **Trade Entered**: Order filled.
- 🎯 **Target Hit**: TP1/TP2/TP3 reached.
- 🛑 **Stop Loss Hit**: SL triggered.
- 🚦 **Manual Shutdown**: Alert sent ONLY to owner on Ctrl+C.
- 🚨 **Daily Loss Limit**: Max loss breached.
- 📋 **Daily Summary**: End of session stats.

## License

Private repository. Not for public distribution.
