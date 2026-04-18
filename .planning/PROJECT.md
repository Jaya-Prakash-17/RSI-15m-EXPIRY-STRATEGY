# RSI Expiry Trading Bot

## What This This
A specialized trading system implementing an RSI-based breakout strategy for Indian index options (NIFTY, BANKNIFTY, SENSEX) on their respective expiry days. It features a vectorized backtesting engine and a live execution client integrated with the Groww API.

## Shipped Versions
- **v2.0 (2026-04-18)**: Portfolio Diversification & Scaling. Implemented parallel multi-index discovery and signal concurrency with deterministic priority allocation.
- **v1.0 (2026-04-18)**: Production Hardening & Reliability. Established a resilient, "fail-closed" environment with time-sync, recovery paths, and safety gates.

## Current Milestone: v3.0 Advanced Risk Analytics & Performance Polishing
**Goal**: Implement real-time margin management, probabilistic stop-loss scaling, and enhanced performance visualization for multi-index operations.

## Requirements

### Validated & Core
- ✅ **Multi-Index Concurrency**: Parallel spot ingestion and signal processing across 3+ indices. (v2.0)
- ✅ **Execution Fidelity**: Partial-fill WA pricing and broker reconciliation. (v1.0)
- ✅ **Resilience**: Exponential backoff retries and reconnect resync paths. (v1.0)
- ✅ **Safety**: Capital concentration guards and directional correlation limits. (v2.0)
- ✅ **Priority Allocation**: Deterministic NIFTY > SENSEX > BANKNIFTY capital scaling. (v2.0)

### Active
- [ ] **Margin Monitoring**: Real-time integration with broker margin endpoints to prevent "Insufficient Funds" rejection during simultaneous spikes.
- [ ] **Dynamic SL Scaling**: Adjust Stop-Loss based on current VIX or ATR during the trade session.
- [ ] **P&L Attribution**: Improved reporting to attribute profits/losses by index and specific strategy variant.

### Out of Scope
- [ ] Direct Equity Trading — Focus is exclusively on Index Options.
- [ ] Non-Expiry Day Trading — Current strategy is optimized for expiry-day volatility.

## Context
- High-performance backtesting using vectorized operations.
- Parallelized Live Engine using ThreadPoolExecutor for low-latency multi-index monitoring.
- Authenticates with Groww via custom `GrowwClient`.
- Uses a tiered exit system (Multi-lot/Single-lot) with trailing stop-losses.

## Constraints
- **Broker**: Groww (API limited)
- **Timeframe**: 15-minute candles
- **Concurrency**: Python Threads (I/O bound)
- **Safety**: Hard Safe-SL limit (Rs. 8000/day) and Daily Loss Limit.

## Key Decisions
| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Parallel Fetching | Reduce latency when monitoring 3+ indices simultaneously | ✓ Good |
| Priority Queue | Ensure capital is reserved for high-probability NIFTY signals first | ✓ Good |
| Pending-State Correlation| Prevent over-leverage during simultaneous multi-index breakouts | ✓ Good |
| Vectorized RSI | Efficiency for 5-year backtests | ✓ Good |

---
*Last updated: 2026-04-18 after Milestone v2.0 Closure*
