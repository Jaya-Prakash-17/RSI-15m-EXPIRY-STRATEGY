# Phase 06: Execution Fidelity & Order Tracking - Context

## Domain Boundary
Hardening the order execution and tracking layer to handle partial fills, broker state discrepancies, and atomic persistence of open trade states.

## [auto] Decisions

### [PFILL-01] Partial-Fill Weighted Average
- **Decision**: Implement a running weighted average fill price in `active_orders`.
- **Logic**: `new_avg = ((old_avg * old_qty) + (fill_price * fill_qty)) / (old_qty + fill_qty)`.
- **Rationale**: Ensures P&L calculation remains accurate even if a single order is filled at multiple price points across time.

### [RECO-01] Authoritative Order State Machine
- **Decision**: Poll `get_order_details` until status is terminal (`FILLED`, `CANCELLED`, `REJECTED`).
- **Persistence**: Update `trade_tracker.json` immediately upon any fill event (atomic fill capture).
- **Rationale**: Prevents "phantom trades" or state loss during broker API timeouts.

### [SAFE-01] Zero-Fill Rejection (Verified)
- **Decision**: Maintain the hard-reject for `fill_price <= 0` implemented in Phase 05.
- **Rationale**: Zero-fill values are invalid and indicate broker/API data corruption.

## Canonical Refs
- `live/live_trader.py`
- `core/groww_client.py`
- `utils/trade_tracker.py`

## Folded Todos (Scored >= 0.4)
- None identified in matched scan.

## Deferred Ideas
- Implementation of OCO (One-Cancels-Other) logic (Reserved for Phase 08).
