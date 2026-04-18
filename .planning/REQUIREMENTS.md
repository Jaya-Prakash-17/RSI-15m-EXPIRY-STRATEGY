# Milestone v1.0: Production Hardening & Reliability

## High Priority (Critical Safety)

### [SYNC] Sync & Time Integrity
- [ ] **[SYNC-01]**: Fix local-clock candle bug: all 15m candle boundaries MUST use exchange/tick timestamps instead of local wall-clock time.
- [ ] **[SYNC-02]**: Implement drift validation and hard-block trading if timestamp quality is unreliable.
- [ ] **[CONT-01]**: Fix warm-up/live continuity gap: detect missing intervals or time gaps > 15 minutes between historical warm-up and live feed.
- [ ] **[CONT-02]**: Force backfill/rebuild of bar series if gaps detected; abort signal generation until continuity restored.

### [EXEC] Execution & Order Fidelity
- [ ] **[EXEC-01]**: Partial-fill reconciliation: track weighted average fill price and actual filled qty for state, SL placement, and exit logic.
- [ ] **[EXEC-02]**: Build authoritative `active_orders` exit-order state machine with reconciliation on restart.
- [ ] **[EXEC-03]**: Fix zero/missing fill price fragility: hard-reject orders with `fill_price=0` or `null`; add follow-up broker fetch fallback.
- [ ] **[SLIP-01]**: Add live slippage realism: enforce configurable max adverse slippage for SL-M orders; abort if tolerance breached.

### [NET] Network & Recovery
- [ ] **[NETW-01]**: Idempotent API retries with exponential backoff for order placement, polling, and fill fetches.
- [ ] **[RECO-01]**: Reconnect resync path: explicitly include `_ltp_cache.clear()` and `_candle_cache` rebuild on API reconnect.
- [ ] **[SAFE-02]**: Prolonged-disconnect emergency flattening policy if connectivity lost beyond threshold with open positions.

### [SAFE] System Safety & Logic
- [ ] **[SAFE-01]**: Hard config safety blocks: reject max_position_pct > conservative threshold and excessive capital concentration.
- [ ] **[RECO-02]**: Fix crash-recovery same-bar entry bypass: fail safe by blocking entry if persisted alert timestamps cannot be parsed.
- [ ] **[INTE-01]**: Harden restored-state integrity: validate alert geometry (SL/Target, high/low) before use; fail closed.
- [ ] **[DATA-01]**: Bar-quality hard gate: block trading on thin, duplicate, or starved bars.
- [ ] **[CONF-01]**: Semantic fix: Rename `alert_validity` to `alert_validity_candles` everywhere with explicit runtime documentation.

---
## Traceability Matrix (Milestone v1.0)

| Requirement | Phase | Status |
|-------------|-------|--------|
| SYNC-01, SYNC-02 | 05 | Planned |
| CONT-01, CONT-02 | 05 | Planned |
| DATA-01 | 05 | Planned |
| EXEC-01, EXEC-02, EXEC-03 | 06 | Planned |
| PART-01 | 06 | Planned |
| NETW-01 | 07 | Planned |
| RECO-01 | 07 | Planned |
| SAFE-02 | 07 | Planned |
| SLIP-01 | 07 | Planned |
| SAFE-01 | 08 | Planned |
| RECO-02 | 08 | Planned |
| INTE-01 | 08 | Planned |
| CONF-01 | 08 | Planned |

*Generated: 2026-04-19 - v1.0 Roadmapping Complete*
