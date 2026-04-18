# Phase 05: Data & Time Hardening - Context

**Gathered:** 2026-04-19
**Status:** Ready for planning
**Source:** User-provided production requirements

<domain>
## Phase Boundary
This phase hardens the temporal and qualitative integrity of the data feed. It moves the system from local-clock dependency to authoritative exchange-timestamp synchronization and implements strict boundary continuity.

</domain>

<decisions>
## Implementation Decisions

### [SYNC] Exchange Timestamp Sync
- All 15m candle boundaries MUST use exchange/tick timestamps (from Groww feed) instead of local wall-clock time.
- Implementation must handle clock drift validation between local and exchange.
- Hard-block trading if timestamp quality/drift exceeds reliable thresholds.

### [CONT] Data Continuity
- Continuity validation required between historical warm-up candles and live feed.
- Detect missing intervals or time gaps > 15 minutes.
- If continuity is broken, force a backfill/rebuild and abort signal generation until restored.

### [DATA] Quality Gates
- Implementation of "Bar Quality" hard gates to block trading on thin, duplicate, or starved bars.
- Cache Integrity: Explicit invalidation of `_ltp_cache` and `_candle_cache` during resync/reconnect.

### [CONF] Configuration Semantic Fix
- Rename `alert_validity` to `alert_validity_candles` everywhere (config, logic, logs).
- Add explicit runtime documentation/logs for this unit.

### the agent's Discretion
- Selection of specific drift thresholds for "unreliable" quality.
- Logic for "weighting" bar quality (e.g. tick count per bar).

</decisions>

<canonical_refs>
## Canonical References

### Core Logic
- `CandleBuilder` class (handling bar construction)
- `live_trader.py` (main feed handling and clock logic)
- `config.yaml` (alert_validity location)

</canonical_refs>

---
*Phase: 05-data-time-hardening*
*Context gathered: via conversation context*
