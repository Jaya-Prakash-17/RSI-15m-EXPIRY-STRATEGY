# RSI-15 Minute Expiry Breakout

This repository implements an Intraday Index Options Strategy based on RSI(14) breakout on 15-minute candles, designed for Indian markets (NSE/BSE).

## Strategy Summary

- **Strategy Name**: Expiry RSI Breakout (15-Minute)
- **Instruments**: Index Options only (NIFTY, BANKNIFTY, SENSEX)
- **Trade Day**: Expiry day only
  - NIFTY → Thursday
  - BANKNIFTY → Wednesday
  - SENSEX → Friday
- **Candle Timeframe**: 15 minutes
- **Signal Logic**:
  - Calculate RSI(14) on option candle closes
  - Alert candle is generated when RSI crosses above 60
  - Only on expiry day
  - Only within trading window (e.g. 10:15–15:00)
- **Entry**: Price breaks the high of alert candle
- **Stop Loss**: Alert Candle Low - 1 point
- **Targets**:
  - T1 = Entry + (High - Low)
  - T2 = Entry + 2 × (High - Low)
  - T3 = Entry + 3 × (High - Low)

## Architecture

- **Backtesting**: Fully reproducible, local-first data architecture. No API calls during backtest loop.
- **Live Trading**: Uses Groww API for spot prices and order placement.
- **Data**: Central `DataManager` handles data serving, caching, and downloading.

## Usage

1. Configure `config.yaml`.
2. Run backtest: `python run_backtest.py`
