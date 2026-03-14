# Core

Low-level infrastructure modules shared across backtest and live trading.

## Files

| File | Purpose |
|---|---|
| `groww_client.py` | **Groww Broker API client.** Handles authentication, order placement, LTP polling, position queries, balance checks, and historical data fetching. Supports both real and mock modes via `GROWW_MOCK_MODE` env var. |
| `logger.py` | **Logging setup utility.** Configures Python loggers with console + optional file output. Used by `run_backtest.py` and `run_live.py` to initialize logging. |
| `retry_decorator.py` | **Retry decorator for API calls.** Wraps functions with exponential backoff retry logic. Catches transient network/API failures and retries up to N times before raising. Used on broker API calls. |
