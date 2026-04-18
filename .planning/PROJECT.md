# RSI Expiry Trading Bot

## What This This
A specialized trading system implementing an RSI-based breakout strategy for Indian index options (NIFTY, BANKNIFTY, SENSEX) on their respective expiry days. It features a vectorized backtesting engine and a live execution client integrated with the Groww API.

## Current Milestone: v1.0 Production Hardening & Reliability

**Goal:** Engineering a resilient, "fail-closed" trading environment for live capital deployment by resolving structural bugs in execution, data sync, and error recovery.

**Target features:**
- Execution Fidelity: Partial-fill reconciliation, state machine order tracking, and slippage tolerance.
- Sync & Integrity: Exchange-timestamp candle sync, warm-up continuity, and cache invalidation.
- Fault Tolerance: Idempotent API retries, reconnect resync, and emergency disconnect flattening.
- Safety Gating: Hard-blocking unsafe configs and crash-recovery entry protections.

## Requirements

### Validated
- o" 15-minute RSI Breakout Strategy ?" v1.0
- o" Multi-index Support (NIFTY, BANKNIFTY, SENSEX) ?" v1.0
- o" Vectorized Wilder's RSI Calculation ?" v1.0
- o" Historical Lot Size Lookup ?" v1.0
- o" Groww API Integration ?" v1.0
- o" Diagnostic Dashboard Visuals (Fixed Scales/Dist) ?" v1.0

### Active
- [ ] **[SYNC-01]**: Exchange-timestamp candle sync (fixing local clock drift)
- [ ] **[EXEC-01]**: Partial-fill reconciliation & weighted average logic
- [ ] **[EXEC-02]**: Authoritative `active_orders` exit-order state machine
- [ ] **[NETW-01]**: Idempotent API retries with exponential backoff
- [ ] **[SAFE-01]**: Hard config safety blocks & crash-recovery guards
- [ ] **[SAFE-02]**: Prolonged-disconnect emergency flattening policy
- [ ] **[DATA-01]**: Bar-quality health gates & continuity validation
- [ ] **[SLIP-01]**: Live slippage realism & tolerance enforcement
- [ ] **[CONF-01]**: Semantic fix: `alert_validity` -> `alert_validity_candles`
- [ ] **[RECO-01]**: Reconnect resync: `_ltp_cache.clear()` + `_candle_cache` rebuild


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
