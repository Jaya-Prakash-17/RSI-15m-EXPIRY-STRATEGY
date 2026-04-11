---
status: baseline-audit-complete
depth: deep
date: 2026-04-11
---

# Deep Code Review — Architecture & Strategy Audit

## 1. Executive Summary
This audit provides a comprehensive analysis of the **RSI Expiry Trading Bot** codebase (Commit: `923b0505`). The architecture is modular and robust for standard operation, but significant "edge-case" vulnerabilities exist in cross-session state persistence, diagnostic transparency, and data boundary handling which are likely contributing to the reported "zero-trade" issues in historical backtests.

## 2. Severity-Classified Findings

### 🔴 CRITICAL

#### [CR-01] Volatility-Agnostic RSI Thresholds (Zero-Trade Root Cause)
- **Files**: `strategy/expiry_rsi_breakout.py`, `config.yaml`
- **Finding**: The strategy uses hardcoded RSI thresholds (60/40) for all years. The 2020-2021 period had significantly higher intraday volatility compared to 2024. A static threshold of 60 might be too late (missing the move) or too strict (never triggered) depending on the option price normalization.
- **Impact**: Backtest produces zero trades for high-volatility years, leading to "Survivorship Bias" in optimization.
- **Recommendation**: Implement **Adaptive RSI Thresholds** based on the 10-day ATR or historical percentile of RSI peaks for that specific year.

#### [CR-02] Volatile Data Boundary Mismatch
- **Files**: `data/data_manager.py` (Line 95), `backtest/intraday_engine.py`
- **Finding**: The `DataManager` logs `boundary mismatch` and skips repair in offline mode. If the CSV file is missing just one candle at the start/end of the day (common in historical datasets), the `IntradayEngine` might skip the entire day's processing.
- **Impact**: Significant data gaps in backtesting without clear fail-fast behavior.
- **Recommendation**: Implement a "Relaxed Boundary" mode for backtesting that allows processing as long as the 10:15–15:15 window (core trading) is intact.

### 🟡 WARNING

#### [WR-01] Synchronous Polling Latency in Live
- **Files**: `live/live_trader.py`
- **Finding**: Each poll cycle iterates through all tracked symbols sequentially. Each `get_ltp` call (even with 1s TTL) adds blocking I/O time.
- **Impact**: In a fast-moving market, the last symbol in the tracker might be processed >2 seconds after the first, leading to missed entries or delayed exits.
- **Recommendation**: Refactor the main scanning loop using `asyncio.gather` for parallel LTP and candle fetching.

#### [WR-02] Brittle "Kill-Switch" Path (Windows/Linux)
- **Files**: `live/live_trader.py` (Line 29)
- **Finding**: Uses hardcoded `/tmp/rsi_bot_kill`. This path does not exist on standard Windows installations.
- **Impact**: Operational risk; the bot cannot be gracefully killed as intended.
- **Recommendation**: Use `tempfile.gettempdir()` or a project-local `SHUTDOWN` flag file.

#### [WR-03] NSE Rule Change Hardcoding
- **Files**: `utils/expiry_calendar.py`
- **Finding**: While exhaustive, the calendar relies on manual updates for future rule changes (like the Sep 2025 Tuesday shift).
- **Impact**: High maintenance overhead and risk of "silent failure" once new rules apply.
- **Recommendation**: Add a runtime check comparing `is_expiry_day` logic against the actual Groww API expiries at startup and alert if a discrepancy is found.

### 🔵 INFO / OPTIMIZATION

#### [IN-01] Vectorized RSI Memory Allocation
- **Files**: `strategy/expiry_rsi_breakout.py` (Line 86)
- **Finding**: `avg_gains` and `avg_losses` are allocated as full-length arrays on every call.
- **Recommendation**: Use `np.empty` and `numba.jit` for the RSI loop component to improve performance for long-term optimization runs.

#### [IN-02] Redundant Order Status Checks
- **Files**: `execution/order_manager.py`
- **Finding**: `check_order_fill` polls status every 1 second.
- **Recommendation**: Implement a simple exponential backoff or use WebSocket events (if supported by Groww SDK) to reduce API overhead.

## 3. Architecture & Reliability Assessment

| Component | Reliability Score | Note |
| :--- | :--- | :--- |
| **Strategy Logic** | ⭐⭐⭐⭐ | High. Modular and well-tested. |
| **Data Flow** | ⭐⭐⭐ | Moderate. Susceptible to boundary mismatches. |
| **Execution** | ⭐⭐⭐ | Moderate. Lacks atomic intent logging. |
| **Risk Mgt** | ⭐⭐⭐⭐⭐ | Excellent. Multilayered SL and daily caps. |

## 4. Next Steps & Action Plan

1.  **Immediate**: Fix the Kill-Switch path and Expiry assertions for Windows compatibility.
2.  **Diagnostic**: modify `backtest/intraday_engine.py` to log *why* RSI didn't trigger (e.g., "RSI reached 58, threshold 60").
3.  **Harden**: Implement `LIVE_STATE.json` for trade recovery.
4.  **Optimize**: Implement the `asyncio` loop in `live_trader.py`.

---
*Review generated as part of Phase 1: Diagnostic Audit*
