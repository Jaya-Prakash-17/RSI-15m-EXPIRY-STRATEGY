# Phase 15: Hardening Live Trading Reliability - Context

**Gathered:** 2026-05-09
**Status:** Ready for planning
**Source:** User Prompts

<domain>
## Phase Boundary
This phase focuses on critical safety and reliability hardening of the `LiveTrader` implementation. It addresses race conditions, non-deterministic timing, and safety guardrails required for robust production trading.

</domain>

<decisions>
## Implementation Decisions

### 1. Emergency Flatten Hardening
- Guarantee that `_emergency_flatten()` first cancels every live SL and target order for each active trade.
- Tolerate cancellation failures with critical logs.
- Place the emergency market exit only after cancellation attempts.
- Force-close the tracker state to prevent orphan monitoring.

### 2. SQ-OFF Pending-Entry Race Fix
- Status-check every non-paper pending order before cancellation.
- If already filled, activate the trade instead of cancelling.
- If status lookup fails, fail-safe toward broker cancel while preserving monitoring.

### 3. Polling Cadence Hardening
- Replace wall-clock modulo polling (`% 2 == 0`) with elapsed-time scheduling using `last_poll_at` timestamps.
- Ensure deterministic 2-second LTP polling even when loop execution drifts.

### 4. Reconnect Cache Resync
- Invalidate all stale market-data caches (LTP, candle, and spot) on reconnect.
- Add explicit logs for each cleared cache.

### 5. Live Slippage Abort Gate
- Add a configurable `slippage_abort_pct` threshold.
- If broker fill slippage exceeds this threshold, immediately exit the position, consume the alert, notify Telegram, and do not activate the trade.
- Keep warning-only behavior for smaller slippage above normal tolerance.

### 6. Paper Partial-Exit Quantity Correctness
- Compute TP1/TP2/TP3 exit quantity from actual remaining quantity.
- Prevent over-exit.
- Return early if remaining quantity is zero.

</decisions>

<canonical_refs>
## Canonical References
- `live/live_trader.py` — Central trading logic and loop.
- `config.yaml` — Risk and resilience parameters.
- `strategy/expiry_rsi_breakout.py` — RSI calculation and signal logic.

</canonical_refs>

---
*Phase: 15-hardening-live-trading-reliability*
*Context gathered: 2026-05-09 via user instructions*
