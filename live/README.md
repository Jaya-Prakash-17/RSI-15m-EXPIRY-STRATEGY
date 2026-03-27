# Live

Live trading engine for real-time execution on Groww.

## Files

| File | Purpose |
|---|---|
| `live_trader.py` | **Main live trading engine.** Runs the full trading loop: polls candle closes, scans for RSI signals, places SL-M pending entry orders, monitors fills, manages partial exits with broker-side SL trailing, and auto-squares-off at session end. Supports both paper and live modes. Sends Telegram alerts at every key event. |
| `live_trader_monitoring_methods.py` | **DEPRECATED — do not use.** Previously contained duplicate monitoring functions. All canonical code now lives in `live_trader.py`. Kept as empty stub to prevent accidental re-creation. |

## Trading Flow (15-min cycle)

1.  **Signal Scan**: At each 15-min candle close.
2.  **Alert Generated**: RSI > 60 + Green Candle.
3.  **Order Placed**: SL-M BUY at `alert_high`. Valid for `alert_validity` candles.
4.  **Monitoring**: If price crosses `alert_high`, trade activates.
5.  **Management**: Automated multi-lot exits and trailing SL.
6.  **Shutdown**: Manual shutdown (Ctrl+C) sends alert but LEAVES trades open for manual management.

## Paper vs Live

-   **Paper Trading**: Virtual execution. No broker risk.
-   **Live Trading**: Real orders on Groww API. Auto-square-off enforced at 15:20-15:25.

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
| `trading.paper_trading` | `true` = simulated, `false` = real |
| `strategy.alert_validity` | Lifespan of a breakout order (default: 2 candles) |
| `trading.window.auto_square_off` | Warning triggered if scheduled after 15:20 |
| `risk.max_loss_per_day` | Daily loss limit — bot stops if breached |
