# Strangle & Gap Spread Backtesting

This directory contains specialized backtesting scripts for strategies that differ from the main Expiry RSI Breakout strategy.

## Strategies

### 1. Morning Strangle (`run_strangle.py`)
- **Objective**: Capture decay in NIFTY options on expiry mornings.
- **Entry**: 09:20 AM on expiry day.
- **Legs**: Sell 1 ATM Call + 1 ATM Put.
- **Exit**: 11:30 AM (fixed time) or SL hit.
- **Risk**: Fixed stop-loss per leg.

### 2. Gap Directional Spread (`run_gap_spread.py`)
- **Objective**: Trade the gap direction on NIFTY expiry days using spreads to limit risk.
- **Entry**: 09:15 AM based on gap direction relative to previous day's 15:15 close.
- **Legs**: Bull Call Spread (Gap Up) or Bear Put Spread (Gap Down).
- **Exit**: 15:25 (EOD) or SL hit.
- **Risk Management**: Monitoring combined spread P&L on a 15-minute basis with a daily loss cap.

## Usage

```bash
# Run 5-year Morning Strangle backtest
python strangle_backtest/run_strangle.py

# Run 5-year Gap Directional Spread backtest
python strangle_backtest/run_gap_spread.py
```

Reports are generated in the `reports/` directory with specific prefixes.
