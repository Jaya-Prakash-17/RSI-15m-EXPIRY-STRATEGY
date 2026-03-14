# Live

Live trading engine for real-time execution on Groww.

## Files

| File | Purpose |
|---|---|
| `live_trader.py` | **Main live trading engine.** Runs the full trading loop: polls candle closes, scans for RSI signals, places SL-M pending entry orders, monitors fills, manages partial exits with broker-side SL trailing, and auto-squares-off at session end. Supports both paper and live modes. Sends Telegram alerts at every key event. |
| `live_trader_monitoring_methods.py` | **DEPRECATED — do not use.** Previously contained duplicate monitoring functions. All canonical code now lives in `live_trader.py`. Kept as empty stub to prevent accidental re-creation. |

## Trading Flow

```
Bot starts → _initialize_day()
    ↓
Main loop (1-second poll):
    ↓
_poll_candle_close() → New 15-min candle?
    ↓ yes
_update_option_universe() → Refresh option chain
    ↓
_process_strategy_logic() → Scan for RSI alerts
    ↓ ALERT found
_place_pending_entry() → SL-M BUY order on broker
    ↓
_monitor_pending_entries() → Check if order filled
    ↓ FILLED
_activate_trade_from_pending() → Place SL + Target orders
    ↓
_monitor_active_trades() → Check TP/SL hits
    ↓
_handle_multi_lot_exits() or _handle_single_lot_exits()
    ↓
_close_entire_position() → Final exit + P&L calculation
    ↓
Auto square-off at 15:25
```

## Telegram Integration

The live trader sends Telegram notifications at every key event:

| Event | Method |
|---|---|
| Bot started | `telegram.bot_started()` |
| RSI alert detected | `telegram.alert_setup()` |
| Alert expired | `telegram.alert_expired()` |
| Trade entered | `telegram.entry_confirmed()` |
| Target hit | `telegram.target_hit()` |
| Stop loss hit | `telegram.sl_hit()` |
| Position squared off | `telegram.square_off()` |
| Daily loss limit hit | `telegram.daily_loss_limit_hit()` |
| End of session | `telegram.daily_summary()` |

## Running

```bash
# Paper trading (default — no real orders)
python run_live.py

# Live trading — set paper_trading: false in config.yaml
python run_live.py
```

## Key Config Dependencies

| Config Key | Effect |
|---|---|
| `trading.paper_trading` | `true` = simulated orders, `false` = real broker orders |
| `trading.window.start` / `end` | Trading signal window (default: 10:15–15:00) |
| `trading.window.auto_square_off` | Forced exit time (default: 15:25) |
| `risk.max_loss_per_day` | Daily loss limit — bot stops if breached |
