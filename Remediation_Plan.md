# Remediation Plan: RSI-15m-EXPIRY

This plan defines the exact steps required to resolve the vulnerabilities identified in the Comprehensive Codebase Audit. Execution of these phases will clear the path for Live Production deployment.

## PHASE 1: Execution Safety (Partial Fill Tracking)
**Target:** `execution/order_manager.py` & `live/live_trader.py`
**Vulnerability:** Untracked partially filled entry orders.

1.  **Refactor `check_order_fill` (Order Manager):**
    *   Modify the return signature from a flat `float` (or `None`) to a detailed dictionary: `{'status': str, 'fill_price': float, 'filled_qty': int}`.
    *   Upon a 30s timeout and subsequent cancellation, if `filled_qty > 0`, explicitly return the partial details rather than yielding `None`.

2.  **Adapt Order Ingestion (Live Trader):**
    *   Update the logic where `check_order_fill` is called.
    *   If the result dictates `filled_qty > 0` (even if `PARTIALLY_FILLED` or `CANCELLED`), accept the entry but initialize the active trade state with the *actual* `filled_qty`.
    *   Dynamically recalculate position sizing guards (`max_loss_per_day` ratio) against the smaller footprint.
    *   Submit SL and TP orders parameterized to the newly constrained `filled_qty`.

## PHASE 2: Performance Architecture (Memory Optimization)
**Target:** `backtest/intraday_engine.py` & `strategy/expiry_rsi_breakout.py`
**Vulnerability:** Redundant $O(N)$ Pandas Series allocations in $O(N^2)$ loop.

1.  **Decouple `check_signal` Dependency:**
    *   Refactor `check_signal()` in `expiry_rsi_breakout.py` to accept an integer `history_len` argument alongside `price_history`.
    *   Only invoke `len(price_history)` if `history_len` is absent.

2.  **Eliminate Slicing Allocation:**
    *   In `intraday_engine.py`, within the core `for t in timestamps` loop, remove `price_slice = df['close'].iloc[:curr_idx + 1]`.
    *   Directly feed `history_len = curr_idx + 1` into the `check_signal` function call.
    *   RSI calculations are already bypassed by the pre-calculated `rsi_values=(curr_rsi, prev_rsi)`, removing any need for the physical price array payload.

## PHASE 3: Telemetry & Hardening (Advisory)
**Target:** `live/live_trader.py`
**Vulnerability:** Silent API backoff drops.

1.  **State Preservation on Halt:**
    *   When `_is_market_open` fails 5 times consecutively, ensure that existing `active_trades` are explicitly checkpointed to `strategy_state.json` or `TradeTracker` to survive a potential hard crash.
    *   Enhance Telegram logging to broadcast the last known status of all open limit/stop orders prior to the disconnect.

## GO/NO-GO CRITERIA
Upon completion of Phase 1 and Phase 2, the codebase will be elevated to **GO** status for live capital deployment. Phase 3 is recommended but non-blocking.
