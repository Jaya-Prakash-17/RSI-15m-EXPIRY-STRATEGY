# RSI-15 Minute Expiry Breakout Bot

Intraday Index Options Strategy based on RSI breakout on 15-minute candles, designed for Indian markets (NSE/BSE). Includes a backtesting engine with interactive dashboards and a live trading bot with Telegram alerts.

## Strategy Summary

| Parameter | Value |
|---|---|
| **Strategy** | Expiry RSI Breakout (15-Minute) |
| **Instruments** | Index Options only (NIFTY, BANKNIFTY, SENSEX) |
| **Trade Day** | Expiry day only (configurable: `trade_only_on_expiry`) |
| **Candle Timeframe** | 15 minutes |
| **RSI Period** | 11 (Wilder's RSI) |
| **RSI Threshold** | 60 (alert on cross above) |
| **Entry** | Price breaks the high of alert candle (SL-M BUY order) |
| **Stop Loss** | Alert candle low − 1 pt, capped by `safe_sl_max_loss` |
| **Targets (TP)** | T1 (1×), T2 (2×), T3 (3×) alert candle range |
| **Risk Cap** | `safe_sl_max_loss` per trade (default: Rs.2000 = 2% of capital) |

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
├── .env.example             # Template for environment variables (copy to .env)
├── run_backtest.py          # Entry point: run backtesting
├── run_live.py              # Entry point: run live/paper trading
├── daily_reconcile.py       # Post-market P&L reconciliation vs broker
│
├── strategy/                # Trading strategy implementation
│   └── expiry_rsi_breakout.py   # RSI breakout signal logic (ALERT → ENTRY → SL calc)
│
├── backtest/                # Backtesting engine
│   └── intraday_engine.py       # Replays historical data, simulates trades
│                                 # V10: circuit breaker, safe_sl recalc, SL compliance audit
│
├── live/                    # Live trading engine
│   ├── live_trader.py           # Real-time trading loop with Telegram alerts
│   └── live_trader_monitoring_methods.py  # Health check methods
│
├── core/                    # Infrastructure
│   ├── groww_client.py          # Groww broker API client (BSE/NSE support)
│   ├── exceptions.py            # Exception hierarchy (CircuitBreaker, OrderReject, etc.)
│   ├── logger.py                # Logging setup
│   └── retry_decorator.py       # Retry with exponential backoff
│
├── data/                    # Data layer
│   ├── data_manager.py          # Central data hub (cache + serve)
│   ├── historical_downloader.py # Bulk CSV downloader for backtests
│   ├── spot/                    # Spot index 15m candle CSVs
│   └── derivatives/             # Option chain 15m candle CSVs
│
├── execution/               # Order management (live only)
│   ├── order_manager.py         # Place/modify/cancel broker orders
│   └── trade_tracker.py         # Trade state persistence & recovery
│
├── reporting/               # Backtest reports
│   └── performance.py           # PNG dashboard + interactive HTML (Plotly) + JSON
│
├── scripts/                 # Operational scripts
│   ├── compare_years.py         # Cross-year backtest comparison (GO/NO-GO)
│   ├── verify_backtest_data.py  # Pre-flight data & lot size verification
│   ├── preflight_check.py       # Live trading pre-flight checks
│   ├── setup_service.sh         # Linux systemd service installer
│   ├── rsi-bot.service          # systemd unit file template
│   ├── check_bot.sh             # Bot health check (Linux)
│   └── paper_trading_checklist.md  # 20-session pre-live SOP
│
├── tests/                   # Test suite
│   ├── test_business_logic.py       # Unit tests: SL calc, lot sizing, risk
│   ├── test_integration.py          # Integration tests
│   ├── verify_fixes.py              # Bug fix regression tests
│   └── verify_residual_fixes.py     # V10 fix verification
│
└── utils/                   # Shared utilities
    ├── historical_lot_sizes.py  # SEBI lot size history (NIFTY/BN/SENSEX all dates)
    ├── expiry_calendar.py       # Expiry day lookup (handles Thursday→Tuesday transition)
    ├── nse_calendar.py          # NSE/BSE holiday calendar (2020–2026)
    ├── symbol_parser.py         # Extract underlying from option symbol
    ├── telegram_notifier.py     # Telegram alerts (multi-chat + owner-only)
    ├── trade_logger.py          # CSV trade audit log
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
