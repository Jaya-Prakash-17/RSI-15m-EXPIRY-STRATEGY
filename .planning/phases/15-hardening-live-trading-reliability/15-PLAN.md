# Phase 15-PLAN.md — Hardening Live Trading Reliability

<objective>
Implement a suite of critical safety and reliability patches in the `LiveTrader` to ensure zero-incident performance, robust disconnect recovery, and deterministic execution.
</objective>

## Tasks

### [COMPLETED] 1. Polling Cadence Hardening
- [x] Replace wall-clock modulo polling (`int(now.timestamp()) % 2 == 0`) with elapsed-time scheduling.
- [x] Implement `last_ltp_poll` timestamp for deterministic 2-second polling intervals.
- [x] Initialize poll timers before the main loop starts.

### [COMPLETED] 2. Live Slippage Abort Gate
- [x] Add `slippage_abort_pct` configuration (defaulting to `gap_abort_pct` or 0.04).
- [x] Implement immediate `MARKET EXIT` for fills exceeding the slippage abort threshold.
- [x] Ensure Telegram notification and state cleanup on abort.

### [COMPLETED] 3. SQ-OFF Pending-Entry Race Fix
- [x] Status-check non-paper pending orders before cancellation at square-off.
- [x] Activate trade if filled instead of cancelling.
- [x] Add fail-safe cancel attempt if status lookup fails.

### [COMPLETED] 4. Reconnect Cache Resync
- [x] Clear `_spot_cache` on reconnect in `_reconnect_resync`.
- [x] Add explicit logging for LTP, candle, and spot cache invalidation.

### [COMPLETED] 5. Paper Partial-Exit Quantity Correctness
- [x] Fix off-by-one and floor logic in `_handle_paper_tp_hit`.
- [x] Ensure partial exit qty is derived from actual remaining qty.
- [x] Add return-early guard for zero remaining quantity.

### [COMPLETED] 6. Emergency Flatten Hardening
- [x] Audit `_emergency_flatten()` in `live/live_trader.py`.
- [x] Implement cancellation of all live SL and target orders for every active trade.
- [x] Handle cancellation failures with critical logs.
- [x] Place the final emergency market exit only after order cleanup.
- [x] Force-close the tracker state to prevent orphaned monitoring.

### [COMPLETED] Verification
- [x] Verify `_emergency_flatten` logic via code audit.
- [x] Ensure syntax correctness of all applied patches.
- [x] Confirm no regression in paper trading simulation.

---
*Phase: 15-hardening-live-trading-reliability*
*Plan created: 2026-05-09*
