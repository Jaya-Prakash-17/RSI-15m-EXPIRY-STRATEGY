# Phase 10: Multi-Index Attribution Reporting - Context

**Gathered:** 2026-04-18
**Status:** Ready for planning
**Source:** Discussed via /gsd-discuss-phase (scouting session)

<domain>
## Phase Boundary

This phase delivers an upgraded performance reporting engine capable of segmenting P&L, hit rates, and risk metrics by index (NIFTY, SENSEX, BANKNIFTY). It culminates in "Dashboard v2" which provides instrument-level transparency.

</domain>

<decisions>
## Implementation Decisions

### Analytics Segmentation
- Segment all core metrics (Total P&L, Win Rate, Max Drawdown) by instrument.
- Support "All" combined view and individual instrument views.
- **the agent's Discretion**: We will also segment by Option Type (CE vs PE) within each index to detect directional performance bias.

### Data Infrastructure
- **the agent's Discretion**: Update `TradeLogger` to include an `underlying` column in `trade_log.csv`. This prevents repeated parsing of symbols and makes reporting robust.
- Handle legacy logs by auto-detecting `underlying` from `symbol` during ingestion if the column is missing.

### Visualization (Dashboard v2)
- Implement a "Summary Grid" at the top of the HTML report showing hit-rates and P&L cards for each index.
- Use distinct colors for each instrument in combined equity charts.
- Maintain existing "Deep Inspect" (Trade Inspector) functionality.

</decisions>

<canonical_refs>
## Canonical References

### Reporting Core
- `reporting/performance.py` — Main reporting logic.
- `utils/trade_logger.py` — Trade audit log persistence.
- `utils/symbol_parser.py` — Symbol-to-index parsing logic.

### Concurrency Context (Phase 09)
- `.planning/milestones/v2.0-ROADMAP.md` — Context on multi-index implementation.

</canonical_refs>

<specifics>
## Specific Requirements
- Metric: Instrument Win Rate = (Index Winners) / (Index Total Trades).
- Metric: Instrument P&L Contribution = (Index P&L) / (Total Portfolio P&L).
- Ensure "Charge Calculation" logic in `performance.py` correctly handles index-specific lot sizes (NIFTY: 25/50/75, SENSEX: 10/20, etc.).

</specifics>

<deferred>
## Deferred Ideas
- **Dynamic Charting**: Real-time dashboard updates (kept as post-market report for now).
- **Log Compression**: Moved to Phase 11.

</deferred>

---

*Phase: 10-multi-index-attribution-reporting*
*Context gathered: 2026-04-18*
