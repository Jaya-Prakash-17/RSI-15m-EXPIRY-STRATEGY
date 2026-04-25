# RSI-15 Minute Expiry Breakout Bot

Intraday Index Options Strategy based on RSI breakout on 15-minute candles, designed for Indian markets (NSE/BSE). Includes a backtesting engine with interactive dashboards and a live trading bot with Telegram alerts.

## Strategy Suite Summary

### 1. Primary: Expiry RSI Breakout (15-Minute)
| Parameter | Value |
|---|---|
| **Instruments** | Index Options (NIFTY, BANKNIFTY, SENSEX) |
| **Trade Day** | Expiry day only |
| **Entry** | RSI (11) > 60 + High Breakout on 15m candle |
| **Risk Cap** | `safe_sl_max_loss` (Default: Rs.2000) |
| **Exit** | T1 (1x), T2 (2x), T3 (3x) alert range |

### 2. Specialized: Morning Strangle
| Parameter | Value |
|---|---|
| **Entry** | 09:20 AM on Expiry Day |
| **Legs** | Short ATM Call + Short ATM Put |
| **Exit** | 11:30 AM or SL hit |

### 3. Specialized: Gap Directional Spread
| Parameter | Value |
|---|---|
| **Entry** | 09:15 AM based on Gap Direction |
| **Legs** | Bull Call / Bear Put Spreads |
| **Exit** | 15:25 EOD or SL hit |

### Expiry Schedule (Current — since Sep 2025)

| Index | Expiry Day | Type |
|---|---|---|
| NIFTY | Tuesday | Weekly |
| BANKNIFTY | Last Tuesday of month | Monthly |
| SENSEX | Thursday | Weekly |

### Exit Modes

**Single-lot (default):** Exit fully at configured target (T2 recommended — higher hit rate)

**Multi-lot (3 lots):** TP1 → exit 1 lot + trail SL, TP2 → exit 1 lot + trail SL, TP3 → exit remaining

## Risk Management (V10)

| Feature | Description |
|---|---|
| **Safe SL Cap** | `safe_sl_max_loss` enforced at entry using actual historical lot size (not config) |
| **SL Floor** | `min_sl_pct` (8%) ensures SL is never too tight |
| **Floor/Cap Order** | Floor applied first, then cap — cap always wins |
| **Circuit Breaker** | `max_consecutive_losses` pauses trading after N losses in a row |
| **Intraday Gap Fix** | SL exit uses SL price (not candle open) for intraday. Only 09:15 candle uses gap logic |
| **Historical Lot Sizes** | Correct lot sizes for all dates (NIFTY 75→65, BANKNIFTY 25→35→30, SENSEX 10→20) |
| **Post-Backtest Audit** | `_verify_safe_sl_compliance()` scans all trades for safe_sl breaches |

## Project Structure

```
RSI-15m-EXPIRY-STRATEGY/
├── config.yaml              # All strategy, risk, and trading parameters
├── .env.example             # Template for environment variables
├── run_backtest.py          # Entry point: Primary RSI backtesting
├── run_live.py              # Entry point: Live/Paper trading
│
├── strategy/                # Strategy logic implementations
│   └── expiry_rsi_breakout.py   # Primary RSI signal logic
│
├── backtest/                # Backtesting engines
│   ├── intraday_engine.py       # RSI Engine (V10)
│   └── optimize.py              # Parameter optimizer
│
├── strangle_backtest/       # Specialized strategy tests
│   ├── run_strangle.py          # Morning Strangle backtest
│   └── run_gap_spread.py        # Gap Directional Spread backtest
│
├── live/                    # Live trading infrastructure
│   ├── live_trader.py           # Real-time execution loop
│   └── live_trader_monitoring_methods.py
│
├── core/                    # System core (Broker API, logging)
│   ├── groww_client.py          # Groww API client
│   └── exceptions.py            # Custom error types
│
├── data/                    # Data persistence & management
│   ├── data_manager.py          # Central data hub
│   └── historical_downloader.py # CSV downloader
│
├── execution/               # Order management
│   ├── order_manager.py         # Broker order placement
│   └── trade_tracker.py         # State recovery
│
├── reporting/               # Performance analysis
│   └── performance.py           # Dashboard generator
│
├── tests/                   # Safety & validation suite
│   ├── verify_safety.py         # SL compliance audit
│   ├── verify_multi_index.py    # Multi-index attribution
│   └── verify_resilience.py     # System resilience tests
│
├── scripts/                 # Operational & utility scripts
│   ├── daily_reconcile.py       # P&L reconciliation
│   ├── compare_years.py         # Year-over-year comparison
│   ├── preflight_check.py       # Live trading pre-flight
│   └── trade_inspector.py       # Visual trade debugger
│
└── utils/                   # Shared utilities
    ├── historical_lot_sizes.py  # SEBI lot size history
    ├── expiry_calendar.py       # Expiry day logic
    └── telegram_notifier.py     # Multi-channel alerts
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

**Output:** Three report files in `reports/`:
- `backtest_YYYYMMDD_HHMMSS.json` — Raw trade data + summary stats
- `backtest_YYYYMMDD_HHMMSS.png` — 6-panel dark theme dashboard (Equity, P&L, Monthly, Distribution, Drawdown, Stats)
- `backtest_YYYYMMDD_HHMMSS.html` — Interactive Plotly dashboard (hover, zoom, trade log table)

### 3. Pre-flight Verification

```bash
# Verify data availability, lot sizes, and calendar before backtest:
python scripts/verify_backtest_data.py

# Compare multiple year backtests against GO/NO-GO criteria:
python scripts/compare_years.py reports/
```

### 4. Run Live Trading (Paper Mode)

```bash
python run_live.py
```

## Configuration (config.yaml)

### Key Parameters

| Parameter | Default | Description |
|---|---|---|
| `strategy.lots_per_trade` | 1 | Lots per trade (1 for live debut, 3 for backtest analysis) |
| `strategy.safe_sl_max_loss` | 2000 | Max loss per trade in Rs. (2% of 1L capital) |
| `strategy.safe_sl_mode` | true | Enable SL distance capping |
| `strategy.trade_only_on_expiry` | true | Only trade on index expiry days |
| `strategy.exit_mode` | single_lot | `single_lot` or `multi_lot` |
| `strategy.single_lot_exit_target` | 2 | Target level for single-lot exit (1=T1, 2=T2, 3=T3) |
| `risk.max_consecutive_losses` | 3 | Pause after N consecutive losses |
| `trading.paper_trading` | true | Set `false` for real money (**danger!**) |

### Charges (applied in backtest reports)

| Charge | Config Key | Default |
|---|---|---|
| Brokerage | `charges.brokerage_per_trade` | Rs.20/leg |
| STT | `charges.stt` | 0.2% on sell side |
| Exchange fees | `charges.exchange_txn_fee` | 0.09% |
| GST | `charges.gst` | 20% on brokerage+fees |
| Slippage buffer | `reporting.slippage_buffer_per_trade` | Rs.50/trade |

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
- 🤖 **Bot Started**: On initialization
- 🔔 **Trade Setup Alert**: RSI breakout detected
- ✅ **Trade Entered**: Order filled
- 🎯 **Target Hit**: TP1/TP2/TP3 reached
- 🛑 **Stop Loss Hit**: SL triggered
- 🚦 **Manual Shutdown**: Alert sent ONLY to owner on Ctrl+C
- 🚨 **Daily Loss Limit**: Max loss breached
- ⚡ **Circuit Breaker**: Consecutive loss limit triggered
- 📋 **Daily Summary**: End of session stats

## Backtest Report Dashboard

Each backtest generates a **6-panel dark theme PNG** and an **interactive HTML** dashboard:

| Panel | Content |
|---|---|
| **Equity Curve** | Capital over time with drawdown shading and peak line |
| **Stats Panel** | Returns, Risk Metrics (Win Rate, PF, Sharpe, Sortino, Max DD) |
| **P&L Per Trade** | Green/red bar chart for every trade |
| **Monthly P&L** | Aggregated monthly returns with labels |
| **P&L Distribution** | Histogram of wins vs losses with average line |
| **Drawdown %** | Percentage drawdown timeline |

The HTML report adds: hover tooltips, zoom/pan, and a full **trade log table** with symbol, prices, and P&L.

## License

Private repository. Not for public distribution.
