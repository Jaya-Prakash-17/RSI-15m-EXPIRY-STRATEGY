# Phase 2: Implementation of Atomic Live State Persistence - Context

**Gathered:** 2026-04-12
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase delivers a robust, crash-resilient state management system for the live trading bot. It ensures that active trade positions, Stop-Loss/Target levels, and historical candle data (required for RSI calculation) are preserved across application restarts, network failures, or system crashes.

</domain>

<decisions>
## Implementation Decisions

### Synchronization Strategy
- **Triggered + Heartbeat**: State will be serialized to disk immediately upon any trade event (Entry, Sl/TP update, Exit). A periodic "heartbeat" save will occur every 60 seconds to capture metadata and forming candles.

### Data Scope
- **Active Trades**: Full trade dictionaries including entry time, price, status, and rationale.
- **Candle History**: The last 150 closed bars from the `CandleBuilder` to ensure technical indicators (RSI) are available immediately upon restart.
- **Circuit Breakers**: Daily loss counters and consecutive loss counts.

### Atomicity & Safety
- **Temp-and-Rename**: All writes will use `tempfile.NamedTemporaryFile` followed by `os.replace` to guarantee atomicity.
- **Validation**: JSON integrity will be verified on load; if corrupted, the system will attempt to restore from a `.bak` file or alert the user.

### Format
- **JSON with Schema Version**: Maintain human-readability while supporting future field additions via version tracking.

### the agent's Discretion
- Choice of specific JSON library (standard `json` vs `ujson` for speed).
- Internal method naming for save/load hooks in `LiveTrader`.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `TradeTracker`: Existing locking and `_save_data` logic using `tempfile`.
- `CandleBuilder`: `warm_up_from_df` and `bars` deque structure.

### Established Patterns
- `config.yaml` as the source of truth for file paths.
- `logger` for persistence event tracking.

</code_context>

<specifics>
## Specific Ideas
- Ensure `CandleBuilder` data is stored in a separate JSON key or file to prevent trade state bloat.

</specifics>

<deferred>
## Deferred Ideas
- Moving to SQLite (deferred until trade volume exceeds 10,000 records/day).

</deferred>
