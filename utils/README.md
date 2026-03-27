# Utils

Shared utility modules used across backtest and live trading.

## Files

| File | Purpose |
|---|---|
| `telegram_notifier.py` | **Alert System.** Supports multi-chat notifications and owner-only alerts (manual shutdown). Requires `TELEGRAM_CHAT_ID` (list) and `TELEGRAM_OWNER_ID` (single) in `.env`. |
| `trade_logger.py` | **Audit Log.** Captures every trade event in a CSV. |
| `expiry_calendar.py` | **Source of Truth.** Definitive calendar for NIFTY/BANKNIFTY/SENSEX expiry changes (Sep 2025 reforms). |
| `nse_calendar.py` | **NSE holiday calendar.** Hardcoded list of NSE market holidays. Used by backtest engine to skip non-trading days. `is_trading_day(date)` returns True/False. |
| `trading_day_checker.py` | **API-based trading day check.** Alternative to `nse_calendar.py` — checks if a date is a trading day by verifying actual data availability from the Groww API. More accurate for special trading days (e.g., Budget Day). Falls back to `nse_calendar.py` on API failure. |
| `chart_visualizer.py` | **Trade chart generator.** Creates candlestick charts with trade entry/exit markers, RSI subplot, and target/SL lines. Used by the performance reporter for visual trade analysis. |
| `__init__.py` | Package marker (empty). |

   ```
   TELEGRAM_BOT_TOKEN=your_token_here
   TELEGRAM_CHAT_ID=your_chat_id_here
   ```

## Quick Test

```bash
python -c "from dotenv import load_dotenv; load_dotenv(); from utils.telegram_notifier import TelegramNotifier; TelegramNotifier().test_connection()"
```
