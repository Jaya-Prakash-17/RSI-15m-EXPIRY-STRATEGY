# Research: NIFTY Morning Strangle

## Strategy Rules
- **Instrument**: NIFTY 50
- **Timeframe**: Daily execution on all trading days (2020-2025).
- **Entry Time**: 09:45 AM.
- **Selection**:
    - Current Spot Price at 09:45 AM.
    - Sell CE at (Spot + 500) rounded to nearest 50.
    - Sell PE at (Spot - 500) rounded to nearest 50.
    - Use Current Weekly Expiry.
- **Exit Time**: 03:15 PM (15:15).
- **Position**: Short Strangle (Sell 1 lot of CE, 1 lot of PE).

## Implementation Details
- **Data Source**: Re-use `data/data_manager.py` for spot and derivative CSV loading.
- **Lot Sizes**: Use `utils/historical_lot_sizes.py` to ensure accurate quantity for 5-year period.
- **Expiry Logic**: Use `utils/expiry_calendar.py` to find the nearest expiry for any given date.
- **Reporting**: Re-use `reporting/performance.py`. It takes a DataFrame of trades.

## Key Challenges
1. **Strike Availability**: 500 points away might not always have data in the `data/derivatives` folder.
2. **Backtest Speed**: 5 years (approx. 1250 days) shouldn't be too slow if fetching is efficient.
3. **Report Integration**: `PerformanceReporter` expects certain columns. Ensure the trade list conforms.

## Expected Columns for Trades DataFrame
- `symbol`
- `entry_time`
- `exit_time`
- `entry_price`
- `exit_price`
- `qty`
- `pnl`
- `reason` (e.g., "TIME_EXIT")
- `underlying`
- `running_capital` (optional but good for charts)
