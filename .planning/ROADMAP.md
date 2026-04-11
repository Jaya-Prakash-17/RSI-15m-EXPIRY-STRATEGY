# Project Roadmap — RSI Expiry Trading Bot

## Milestone 1: Production Hardening & Diagnostics (Current)

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Diagnostic Audit of 2020 Backtest Gap | [x] |
| 2 | Implementation of Atomic Live State Persistence | [ ] |
| 3 | Performance Optimization & Asyncio Refactor | [x] |
| 4 | Final Production Validation & Stress Test | [ ] |

## Backlog

### Phase 999.1: Vectorized RSI Smoothing (COMPLETED)
**Goal:** Remove Python loops from core RSI calculation using Pandas EWM.
**Impact:** 5-10x speedup in backtest throughput.

### Phase 999.2: O(log N) Data Filtering (COMPLETED)
**Goal:** Use binary search for time-range slicing in DataManager.
**Impact:** Significant reduction in data loading overhead during backtests.

### Phase 999.3: Fast Gap Detection via Sets (COMPLETED)
**Goal:** Replace O(N) list searches with O(1) set lookups in gap detection.

### Phase 999.4: Hot Loop Import Cleanup (COMPLETED)
**Goal:** Move imports out of build_option_symbol to prevent repeated overhead.
