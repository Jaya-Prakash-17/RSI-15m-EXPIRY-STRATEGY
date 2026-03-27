# Core

Low-level infrastructure modules shared across backtest and live trading.

## Files

| File | Purpose |
|---|---|
| `groww_client.py` | **Groww Broker API client.** Handles authentication, order placement, LTP polling, and historical data. Supports both **NSE** (NIFTY/BANKNIFTY) and **BSE** (SENSEX) indices and derivatives. Identifies exchange based on symbol prefix (`NSE-` or `BSE-`). |
| `logger.py` | **Logging setup utility.** Configures Python loggers with console + optional file output. Used for unified logging across all modules. |
| `retry_decorator.py` | **Retry decorator.** Wraps API calls with exponential backoff handling to manage transient network or broker-side timeouts. |
