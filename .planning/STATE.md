## Current Position

Phase: Completed (Multi-Index Attribution Reporting)
Plan: —
Status: Milestone v3.0: Analytics & Operational Excellence
Last activity: 2026-04-18 — Phase 10: Multi-Index Attribution Reporting completed.


## Accumulated Context

### Concurrency Logic (Validated)
- **Parallel Fetching**: ThreadPoolExecutor used for spot candle discovery across NIFTY, SENSEX, BANKNIFTY.
- **Priority sorting**: Deterministic precedence (NIFTY > SENSEX > BANKNIFTY) ensures capital is allocated to highest liquidity/probability signals.
- **Correlation tracking**: Pending orders must be tracked in `_check_correlation_limit` to prevent directional over-leverage during simultaneous multi-index breakouts.

### Visual Logic (Validated)
- Forced vertical chart orientation and list serialization in `performance.py` to prevent scale distortions (binary blob issue).
- Added drawdown absolute monetary values to hover tooltips.
- Re-activated P&L Distribution bars via explicit `tolist()` serialization.

### Strategy (Current Preferred)
- RSI(11), Threshold(60), TP(3.0), Lots(3).
- 3X Stress-Test charges.

## Validated Decisions
| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Parallel Spot Fetch | Reduce loop lag when scanning 3+ instruments | ✅ |
| Index Priority Map | Deterministic capital scaling during simultaneous signals | ✅ |
| Pending-State Risk | Catch concentration risk in-iteration before order placement | ✅ |
| .tolist() for Plotly | Prevents numpy-binary bdata artifacts in HTML export | ✅ |

---
*Last updated: 2026-04-18*
