# Plan: NIFTY Morning Strangle Backtest

## Objective
Implement a standalone backtest script for a NIFTY 9:45 AM strategy and generate a 5-year performance report.

## Step 1: Initialize Directory
- [x] Create `strangle_backtest` directory in the project root.

## Step 2: Implementation of `run_strangle.py`
- [x] Import `DataManager`, `get_historical_lot_size`, `ExpiryCalendar`, `is_trading_day`, and `PerformanceReporter`.
- [x] Implement `BacktestRunner` class:
    - [x] `__init__`: Setup data manager and reporter.
    - [x] `get_symbols(date, spot_price)`: Determine CE/PE symbols 500 pts away.
    - [x] `process_day(date)`: Fetch data for 9:45 and 15:15 and compute MTM.
    - [x] `run_backtest(start_date, end_date)`: Loop through calendar.
- [x] Integrate `PerformanceReporter` to save files in `reports/strangle/`.

## Step 3: Execution and Verification
- [x] Run `python strangle_backtest/run_strangle.py`.
- [x] Check `reports/` for the new HTML report.

## Verification Criteria
- [ ] Report covers period 2020-2025.
- [ ] 9:45 entry and 3:15 exit are clearly visible in the logs.
- [ ] Trades are recorded with appropriate historical lot sizes.
- [ ] HTML report shows P&L curve, drawdown, and trade list.
