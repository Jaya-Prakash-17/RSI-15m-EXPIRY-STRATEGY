# Project Milestones

## v2.0: Portfolio Diversification & Scaling [2026-04-18]
**Goal**: Expand from single-instrument tracking to multi-index concurrent trading and automated hedge detection.

### Deliverables
- **Phase 09**: Concurrent monitoring of NIFTY, BANKNIFTY, SENSEX signal streams.
- **Priority Allocation**: Deterministic NIFTY > SENSEX > BANKNIFTY capital scaling.

### Accomplishments
- Parallelized spot data ingestion using `ThreadPoolExecutor`.
- Deterministic signal sorting based on index priority map.
- Hardened `_check_correlation_limit` to track pending entries.

---

## v1.0: Production Hardening & Reliability [2026-04-18]
**Goal**: Production-grade stability and fail-closed safety.

### Deliverables
- **Phase 05**: Data & Time Hardening.
- **Phase 06**: Execution Fidelity & Order Tracking.
- **Phase 07**: Resilience & Recovery Path.
- **Phase 08**: Safety Gating & Semantic Cleanup.
