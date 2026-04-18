# RSI Expiry Trading Bot

## What This This
A specialized trading system implementing an RSI-based breakout strategy for Indian index options (NIFTY, BANKNIFTY, SENSEX) on their respective expiry days. It features a vectorized backtesting engine and a live execution client integrated with the Groww API.

## Shipped Versions
- **v1.0 (2026-04-18)**: Production Hardening & Reliability. Established a resilient, "fail-closed" environment with time-sync, recovery paths, and safety gates.

## Current Milestone: v2.0 Portfolio Diversification & Scaling
**Goal**: Expand from single-instrument tracking to multi-index concurrent trading and automated hedge detection.

## Requirements

### Validated & Core
- ✅ **Execution Fidelity**: Partial-fill WA pricing and broker reconciliation.
- ✅ **Resilience**: Exponential backoff retries and reconnect resync paths.
- ✅ **Safety**: Capital concentration guards and same-bar entry protection.
- ✅ **Data Sync**: Exchange-timestamp candle sync and drift validation.

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
| Deterministic Sync | Eliminate clock drift in candle formation | ✓ Good |

---
*Last updated: 2026-04-18 after Milestone v1.0 Closure*
