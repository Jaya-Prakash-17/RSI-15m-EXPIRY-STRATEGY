# Project Roadmap

## Milestone v1.0: Production Hardening & Reliability

### Phase 05: Data & Time Hardening
**Goal:** Ensure 100% deterministic candle boundaries and interval continuity between historical and live feeds.
- [ ] **[SYNC-01]**: Exchange-timestamp candle sync (fixing local clock drift)
- [ ] **[SYNC-02]**: Implementation of drift validation and trading block on bad quality.
- [ ] **[CONT-01]**: Warm-up/live continuity validation (> 15m gap check).
- [ ] **[CONT-02]**: Backfill/rebuild bar series on gaps.
- [ ] **[DATA-01]**: Bar-quality hard gates (thin/duplicate/starved bars).

**Success Criteria:**
1. Candle boundaries align perfectly with exchange tick timestamps regardless of system clock drift.
2. Bot detects gaps > 15m between data sources and aborts trading.
3. Gated health check blocks strategy execution on low-quality/thin data bars.

---

### Phase 06: Execution Fidelity & Order Tracking
**Goal:** Harden the internal state machine and fill-processing logic to handle the "real world" of partial fills and broker API errors.
- [ ] **[EXEC-01]**: Partial-fill reconciliation & weighted average logic.
- [ ] **[EXEC-02]**: Authoritative `active_orders` exit-order state machine.
- [ ] **[EXEC-03]**: Zero-fill protection: hard-reject `fill_price=0/null`.
- [ ] **[PART-01]**: Full reconciliation of actual filled qty across SL/TP and Tracker.

**Success Criteria:**
1. Strategy uses actual weighted average fill prices for all SL/Target calculations.
2. Order state tracker remains authoritative across system restarts (reconciles with broker).
3. Zero-cost trades are blocked before contaminating the trade logs.

---

### Phase 07: Resilience & Recovery Path
**Goal:** Implement automated recovery cycles for network instability and slippage enforcement.
- [ ] **[NETW-01]**: Idempotent API retries with exponential backoff for placement and polling.
- [ ] **[RECO-01]**: Reconnect resync path: `_ltp_cache.clear()` + `_candle_cache` rebuild.
- [ ] **[SAFE-02]**: Prolonged-disconnect emergency flattening policy.
- [ ] **[SLIP-01]**: Live slippage realism for SL-M and tolerance enforcement.

**Success Criteria:**
1. Bot recovers from transient 5xx API errors without placing duplicate orders.
2. Disconnects > threshold trigger emergency exit of open positions.
3. Actual slippage exceeding configurable tolerance aborts trade entry/exit.

---

### Phase 08: Safety Gating & Semantic Cleanup
**Goal:** Final hardening of config-safety blocks and removal of naming ambiguities.
- [ ] **[SAFE-01]**: Hard-block unsafe configs (concentration > threshold).
- [ ] **[RECO-02]**: Crash-recovery same-bar entry protection (parsing safety).
- [ ] **[INTE-01]**: Restored-state integrity validation (geometry check).
- [ ] **[CONF-01]**: Rename `alert_validity` to `alert_validity_candles` everywhere.

**Success Criteria:**
1. Unsafe position sizing or capital concentration configs are rejected at startup.
2. System detects invalid restored alerts (impossible SL/targets) and fails safe.
3. Zero ambiguity in alert validity units (logs/config/runtime).

---

## 999. Future Backlog (Post-v1.0)
- **999.1**: vectorized-rsi-smoothing-completed
- **999.2**: o-log-n-data-filtering-completed
- **999.3**: fast-gap-detection-via-sets-completed
- **999.4**: hot-loop-import-cleanup-completed
