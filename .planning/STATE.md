## Current Position

Phase: Completed (Hardening Live Trading Reliability)
Plan: —
Status: Milestone v3.0: Analytics & Operational Excellence
Last activity: 2026-05-09 — Phase 15: Hardening Live Trading Reliability completed.


## Accumulated Context

### Live Hardening (Validated 2026-05-09)
- **Deterministic Polling**: LTP polling switched to time-delta scheduling (`last_poll_at`) to prevent loop drift skips.
- **Emergency Flatten**: Hardened `_emergency_flatten` to cancel all live SL/target orders before market exit and force-close state.
- **Slippage Abort**: Implemented configurable `slippage_abort_pct` for immediate MARKET EXIT on high-slippage fills.
- **SQ-OFF Integrity**: Pending entry status-checked before cancel; if filled, it is activated rather than orphaned.
- **Reconnect Resilience**: Spot and candle caches explicitly cleared on reconnect to ensure fresh signal generation.

### Concurrency Logic (Validated)
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

### Roadmap Evolution
- Phase 12 added: Remove all volume checks across codebase
- Phase 13 added: NIFTY Morning Strangle Backtest implementation and 5-year run
- Phase 14 added: Gap Directional Spread Backtest (Bull Call / Bear Put)
- Phase 15 added: Hardening Live Trading Reliability (Prompts 1-6 implemented)

---
*Last updated: 2026-05-09*
