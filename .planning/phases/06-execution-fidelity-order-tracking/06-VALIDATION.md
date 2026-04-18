# Phase 06: Execution Fidelity & Order Tracking - Validation (Nyquist)

## Verification Dimensions

### 1. Weighted Average Accuracy
- **Test Case**: Simulate an order of 150 units (3 lots).
    - Fill 50 @ ₹100.
    - Fill 50 @ ₹102.
    - Fill 50 @ ₹105.
- **Success Criteria**: `active_trade['fill_price']` must be exactly ₹102.33.

### 2. Partial-Fill Recovery
- **Test Case**: Restart bot during a partial fill state.
- **Success Criteria**: Bot loads `pending_entries` with correct `cumulative_filled_qty` and continues monitoring the remaining 100 units.

### 3. Zero-Fill Persistence
- **Test Case**: Broker reports a partial fill with price `0`.
- **Success Criteria**: Bot rejects the fill and does NOT update the weighted average or clear the pending status (Safe-mode).

### 4. Reconciliation Integrity
- **Test Case**: Simulate order transition from `OPEN` -> `PARTIALLY_FILLED` -> `FILLED`.
- **Success Criteria**: `trade_tracker.json` reflects each state transition atomically.
