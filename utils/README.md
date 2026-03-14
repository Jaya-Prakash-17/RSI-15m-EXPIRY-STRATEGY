# Utils

Shared utility modules used across backtest and live trading.

## Files

| File | Purpose |
|---|---|
| `telegram_notifier.py` | **Telegram alert system.** Sends formatted trade alerts to your Telegram chat. 9 methods: `alert_setup()`, `alert_expired()`, `entry_confirmed()`, `target_hit()`, `sl_hit()`, `square_off()`, `daily_summary()`, `bot_started()`, `daily_loss_limit_hit()`. All fire-and-forget — never crashes the bot. Requires `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`. |
| `trade_logger.py` | **CSV trade audit log.** Writes every trade event (entry, partial exit, full exit) to a CSV file for post-session review. Configured via `trading.trade_log_file` in config.yaml. |
| `nse_calendar.py` | **NSE holiday calendar.** Hardcoded list of NSE market holidays. Used by backtest engine to skip non-trading days. `is_trading_day(date)` returns True/False. |
| `trading_day_checker.py` | **API-based trading day check.** Alternative to `nse_calendar.py` — checks if a date is a trading day by verifying actual data availability from the Groww API. More accurate for special trading days (e.g., Budget Day). Falls back to `nse_calendar.py` on API failure. |
| `chart_visualizer.py` | **Trade chart generator.** Creates candlestick charts with trade entry/exit markers, RSI subplot, and target/SL lines. Used by the performance reporter for visual trade analysis. |
| `__init__.py` | Package marker (empty). |

## Telegram Setup (one-time)

1. Open Telegram → search `@BotFather` → `/newbot` → copy BOT_TOKEN
2. Send any message to your new bot
3. Open: `https://api.telegram.org/botYOUR_TOKEN/getUpdates`
4. Copy the `chat.id` number from the JSON response
5. Add to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=your_token_here
   TELEGRAM_CHAT_ID=your_chat_id_here
   ```

## Quick Test

```bash
python -c "from dotenv import load_dotenv; load_dotenv(); from utils.telegram_notifier import TelegramNotifier; TelegramNotifier().test_connection()"
```
