# RSI Expiry Trading Bot

## What This This
A specialized trading system implementing an RSI-based breakout strategy for Indian index options (NIFTY, BANKNIFTY, SENSEX) on their respective expiry days. It features a vectorized backtesting engine and a live execution client integrated with the Groww API.

## Core Value
Reliable signal generation and safe, automated execution of expiry breakout trades with strictly enforced risk management.

## Requirements

### Validated
- ✓ 15-minute RSI Breakout Strategy — v1.0
- ✓ Multi-index Support (NIFTY, BANKNIFTY, SENSEX) — v1.0
- ✓ Vectorized Wilder's RSI Calculation — v1.0
- ✓ Historical Lot Size Lookup — v1.0
- ✓ Groww API Integration — v1.0

### Active
- [ ] Diagnostic audit of backtest trade generation (fixing zero-trade issues)
- [ ] Implementation of atomic state persistence for live trading (CR-01)
- [ ] Dynamic Gap-Fill adjustment logic (CR-02)
- [ ] Asyncio refactor of live polling loop (WR-01)
- [ ] Platform-independent Kill-Switch implementation (WR-05)

### Out of Scope
- [ ] Direct Equity Trading — Focus is exclusively on Index Options.
- [ ] Non-Expiry Day Trading — Current strategy is optimized for expiry-day volatility.

## Context
- High-performance backtesting using vectorized operations.
- Historical data is stored locally in CSV format under `data/`.
- Authenticates with Groww via custom `GrowwClient`.
- Uses a tiered exit system (Multi-lot/Single-lot) with trailing stop-losses.

## Constraints
- **Broker**: Groww (API limited)
- **Timeframe**: 15-minute candles
- **Tech Stack**: Python 3.13, Pandas, NumPy
- **Safety**: Hard Safe-SL limit (Rs. 8000/day) and Daily Loss Limit.

## Key Decisions
| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Vectorized RSI | Efficiency for 5-year backtests | ✓ Good |
| Safe SL Mode | Protect against "fat finger" or flash crashes | ✓ Good |
| Multi-lot Exit | Scale out of winning positions for better expectancy | ✓ Good |

---
*Last updated: 2026-04-11 after Milestone Reset*
