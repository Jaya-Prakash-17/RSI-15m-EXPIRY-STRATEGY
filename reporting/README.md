# Reporting

Backtest performance analysis and report generation.

## Files

| File | Purpose |
|---|---|
| `performance.py` | **Performance reporter.** Generates detailed backtest analysis from trade DataFrames. Outputs: HTML report with charts, JSON summary with key metrics (total P&L, win rate, max drawdown, Sharpe ratio, average R-multiple, monthly breakdown). Saves to `reports/` directory with timestamped filenames. |

## Output Files

After running a backtest, reports are saved to `reports/`:

```
reports/
├── backtest_20260314_152603_summary.json    # Machine-readable metrics
└── backtest_20260314_152603_report.html     # Visual report with charts
```

## Key Metrics Calculated

- Total P&L and return %
- Win rate and loss rate
- Average winner vs average loser
- Max drawdown (peak-to-trough)
- Profit factor
- Average R-multiple per trade
- Monthly P&L breakdown
- Trade distribution by index and type (CE/PE)
