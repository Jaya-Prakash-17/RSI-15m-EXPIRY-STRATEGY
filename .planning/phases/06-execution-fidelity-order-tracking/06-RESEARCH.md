# Phase 06: Execution Fidelity & Order Tracking - Research

## Technical Analysis

### 1. Partial-Fill Weighted Average Price (Bug #8 Related)
- **Current State**: `LiveTrader` assumes a single fill price. If a broker fills 50% at ₹100 and 50% at ₹102, the bot currently takes whichever status check it sees first or the final fill price (which might be just the last leg).
- **Proposed Solution**:
    - Update `pending_entries` structure to include `cumulative_filled_qty` and `weighted_sum_fill`.
    - `new_avg = (weighted_sum_fill + (recent_fill_price * recent_fill_qty)) / total_filled`.
- **Injection Point**: `live_trader.py:_monitor_pending_entries`.

### 2. State Machine Reconciliation ([RECO-01])
- **Current problem**: If a status check returns `None` or `ERROR`, the bot might skip monitoring or orphan the order.
- **Proposed Solution**:
    - Implement a `fail_count` per pending order. If broker returns consecutive errors, alert the owner but DO NOT delete the order from tracking until a terminal status is confirmed.
    - Ensure `active_orders` captures ALL fills and partials.

### 3. Atomic Persistence
- **Requirement**: Any change in `filled_qty` must be saved to `trade_tracker.json` immediately.
- **Implementation**: Call `self.tracker.save_pending_entries()` after every detected partial fill.

## Impact Analysis
- **utils/trade_tracker.py**: Needs to support saving/loading the new weighted average fields.
- **execution/order_manager.py**: `check_order_fill` needs to return a dict with `fill_price` and `filled_qty` instead of just a float (breaking change, needs careful migration).

## Risk Assessment
- **Slippage**: Multiple fills might result in an average price that triggers the `GAP-FILL` guard late.
- **Quantization**: Rounding errors in weighted average calculation.
