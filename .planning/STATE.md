## Current Position

Phase: Not started (Inializing Milestone v1.0)
Plan: —
Status: Scoping Production Hardening Milestone
Last activity: 2026-04-19 — Milestone v1.0 "Production Hardening" started. All requirements scoped with REQ-IDs.

## Accumulated Context

### Visual Logic (Validated)
- Forced vertical chart orientation and list serialization in `performance.py` to prevent scale distortions (binary blob issue).
- Added drawdown absolute monetary values to hover tooltips.
- Re-activated P&L Distribution bars via explicit `tolist()` serialization.

### Trade Inspector (Validated)
- High-fidelity markers: Filled green/red triangles for entries/exits.
- Horizontal rays extend to right edge with SL/TP price tags.

### Strategy (Current Preferred)
- RSI(11), Threshold(60), TP(3.0), Lots(3).
- 3X Stress-Test charges.

## Validated Decisions
| Decision | Rationale | Outcome |
|----------|-----------|---------|
| .tolist() for Plotly | Prevents numpy-binary bdata artifacts in HTML export | ✅ |
| Vertical Bar Orientation | Forces correct Y-axis scaling for discrete trades | ✅ |
| Absolute DD Amounts | Required for P&L risk context | ✅ |

---
*Last updated: 2026-04-19*
