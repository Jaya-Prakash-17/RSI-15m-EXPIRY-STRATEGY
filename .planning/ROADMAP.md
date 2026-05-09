# Project Roadmap

## Milestone History
- **[v2.0: Portfolio Diversification & Scaling](milestones/v2.0-ROADMAP.md)** [COMPLETED 2026-04-18]
- **[v1.0: Production Hardening & Reliability](milestones/v1.0-ROADMAP.md)** [COMPLETED 2026-04-18]

## Milestone v3.0: Analytics & Operational Excellence [DRAFT]
- **Goal**: Enhance multi-index performance transparency and infrastructure reliability without altering the core trading strategy.

### Phase 10: Multi-Index Attribution Reporting
- [ ] Upgrade `performance.py` for instrument-level segmentation.
- [ ] Implement per-index performance cards in the dashboard.
- [ ] Deliverable: Dashboard v2 with segmented analytics.

### Phase 11: Operational Hardening & Recovery Logs
- [ ] Implement log rotation and compression logic.
- [ ] Enhance boot-up recovery visualization and state reporting.
- [ ] Deliverable: Self-maintaining log system and transparent boot-up.

### 999. Future Backlog
- **999.1**: vectorized-rsi-smoothing-completed
- **999.2**: o-log-n-data-filtering-completed
- **999.3**: fast-gap-detection-via-sets-completed
- **999.4**: hot-loop-import-cleanup-completed
- **999.5**: dynamic-margin-monitoring (Deferred)

### Phase 12: Remove all volume checks across codebase

**Goal:** [To be planned]
**Requirements**: TBD
**Depends on:** Phase 11
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 12 to break down)

### Phase 13: NIFTY Morning Strangle Backtest implementation and 5-year run

**Goal:** [To be planned]
**Requirements**: TBD
**Depends on:** Phase 12
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 13 to break down)

### Phase 14: Gap Directional Spread Backtest

**Goal:** Implement Bull Call / Bear Put spread based on 9:15 gap direction and backtest over 5 years.
**Requirements**:
- If gap up/neutral: Buy ATM CE, Sell 5-strike OTM CE.
- If gap down: Buy ATM PE, Sell 5-strike OTM PE.
- Execution at 9:45 AM, Exit at 3:15 PM.
**Depends on:** Phase 13
**Plans:** 0 plans

Plans:
### Phase 15: Hardening Live Trading Reliability [COMPLETED 2026-05-09]
- [x] Implement emergency flatten hardening (live SL/target cancellation).
- [x] Fix SQ-OFF pending-entry race conditions.
- [x] Implement deterministic LTP polling cadence.
- [x] Hardening reconnect cache resync.
- [x] Implement live slippage abort gate.
- [x] Fix paper partial-exit quantity logic.
- Deliverable: Robust live trading bot with zero-incident safety guardrails.

**Goal:** Implement a series of critical safety and reliability patches to ensure robust live trading performance.
**Requirements:**
- Emergency flatten must cancel all live orders before exiting.
- Pending orders must be status-checked before cancellation at SQ-OFF.
- LTP polling must be time-delta based, not modulo based.
- Caches must be cleared on reconnect.
- High slippage must abort trades immediately.
- Paper trading must handle partial exits correctly for all lot sizes.
**Depends on:** Phase 14
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 15 to break down)
