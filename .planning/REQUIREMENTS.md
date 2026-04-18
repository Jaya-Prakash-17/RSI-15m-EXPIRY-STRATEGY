# Milestone v3.0: Analytics & Operational Excellence - Requirements

## Status
- **Milestone**: v3.0
- **Goal**: Multi-index transparency and infrastructure reliability.
- **Progress**: [ ] [ ] [ ] [ ] [ ]

## Requirements

### Multi-Index Attribution (ATTR)
- [ ] **ATTR-01**: Segment performance reports by instrument (NIFTY, SENSEX, BANKNIFTY) in `performance.py`.
- [ ] **ATTR-02**: Add "Trade Count" and "Win Rate" cards per index to the main dashboard.
- [ ] **ATTR-03**: Implement instrument-specific P&L heatmaps to identify which expiry performs best.

### Operational Excellence (OPS)
- [ ] **OPS-01**: Implement `TimedRotatingFileHandler` for both `live_trader.py` and `backtest.py`.
- [ ] **OPS-02**: Configure automatic log compression and retention (keep last 7 days).
- [ ] **OPS-03**: Enhance `LiveTrader` boot logs to explicitly list "RESTORED POSITIONS" with index/symbol/entry during recovery.
- [ ] **OPS-04**: Add a summary console table at startup showing current bot state and time-sync status.

## Future Backlog
- [ ] Dynamic Margin Monitoring (REQ-OPS-DF)
- [ ] ATR-based position sizing (REQ-STRAT-DF)

## Traceability

| REQ-ID | Phase | Status |
|--------|-------|--------|
| ATTR-01 | 10 | [ ] |
| ATTR-02 | 10 | [ ] |
| ATTR-03 | 10 | [ ] |
| OPS-01 | 11 | [ ] |
| OPS-02 | 11 | [ ] |
| OPS-03 | 11 | [ ] |
| OPS-04 | 11 | [ ] |
