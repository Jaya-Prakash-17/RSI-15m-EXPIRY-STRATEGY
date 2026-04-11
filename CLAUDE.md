# RSI-15m Expiry Breakout Bot — Claude Context File
> Place at: **project root** `/CLAUDE.md`
> Read by: Claude Code, get-shit-done plugin, all AI assistants

---

## ROLE
Senior Quantitative Developer + Algo Auditor for JP's Indian index options bot.
No filler. No re-explaining settled decisions. Just precise, surgical code.

---

## PROJECT STATE (UPDATE AFTER EACH SESSION)

```
Audit:       V15 complete ✅ | V16 IN PROGRESS
Deployment:  NOT READY — gates below
OOS:         2026 YTD positive (73 trades, PF 4.27, +15.9%) ✅
Paper:       Partially done (need 20 full sessions)
```

### V16 Outstanding Tasks
| ID | Task | Status |
|----|------|--------|
| V16-P-01 | Negative `alert_range` guard in `check_signal()` | ❌ |
| V16-P-02 | 4-year OOS backtest (2022/23/24/25 via `run_oos_validation.py`) | ❌ |
| V16-P-03 | Test config RSI period = 11 (matches production) | ❌ |
| V16-P-04 | Position-scaled slippage (config: `position_scaled`) | ❌ |
| V16-P-05 | Option data quality guard | ❌ |
| V16-P-06 | Remove dead `same_candle_guard` code | ❌ |
| V16-P-07 | `avg_capital_deployed` in stats | ❌ |
| V16-P-08 | TP-before-SL when SL trailed above entry | ❌ |
| V16-P-09 | `verify_v16.py` regression test | ❌ |

**Priority:** P-01 → P-03 → P-02 (OOS run) → P-04..P-08 → P-09 → paper → live

### Deployment Gates
```
✅ Codebase audit V15: zero critical bias
✅ 2026 OOS: positive
✅ Infrastructure: SL, SQ_OFF, crash recovery, circuit breaker
❌ compare_years.py: 2022/2023/2024/2025 NOT yet run
❌ V16-P-01: negative alert_range bug NOT patched
❌ Paper trading: need 20 full sessions
```

---

## NEVER FLAG THESE (JP's intentional choices)
| Item | Reason |
|------|--------|
| `alert_validity: 1` | Deliberate safety gate |
| `trade_only_on_expiry: false` | Intentional — trades every day |
| RSI period = 11 | Evolved from 9, intentional |
| Per-index independent trades | Required feature |
| Inflated charges + Rs.65 slippage | Stress-test choice |
| Sharpe ~5.9 | Correct methodology for this strategy |
| SL fills at exact SL price | Offset by slippage buffer |
| 1240 trades with SL ≥ entry | Trailed SL, not a bug |
| `same_candle_guard` dead code | Architectural property |

---

## CRITICAL KNOWN BUG (V16-P-01, UNPATCHED)
```
Location: strategy/expiry_rsi_breakout.py → check_signal()
Bug:      alert_range not validated → 8 trades with high < low (corrupt data)
          produced inverted targets (T1 < entry_price)
Fix:      Add BEFORE alert state is set:
            if alert_range < self.min_alert_range:
                return None
```

---

## CODEBASE MAP

| File | Role | Key Functions |
|------|------|---------------|
| `strategy/expiry_rsi_breakout.py` | Signal logic | `check_signal()`, `_calculate_effective_sl()`, `batch_calculate_rsi()` |
| `backtest/intraday_engine.py` | Backtesting | `process_expiry_day()`, `_enter_trade()`, `_manage_active_trade()` |
| `live/live_trader.py` | Live trading | `run()`, `_process_strategy_logic()`, `_monitor_active_trades()` |
| `execution/order_manager.py` | Broker orders | `place_entry_order()`, `place_sl_order()`, `modify_sl_order()` |
| `execution/trade_tracker.py` | State persistence | `add_active_trade()`, `close_trade()`, atomic writes |
| `data/data_manager.py` | Data hub | `get_spot_candles()`, `get_derivative_candles()`, `build_option_symbol()` |
| `core/groww_client.py` | Broker API | `get_ltp()`, `get_historical_candles()`, `place_order()` |
| `utils/expiry_calendar.py` | Expiry logic | `is_expiry_day()`, `get_expiry_for_date()` — single source of truth |
| `utils/historical_lot_sizes.py` | Lot history | `get_historical_lot_size()` |
| `reporting/performance.py` | Reports | `generate_report()`, `calculate_advanced_stats()` |
| `scripts/compare_years.py` | OOS validation | **Primary deployment gate** |
| `scripts/run_oos_validation.py` | OOS runner | Runs all years in-process, no config mutation |

---

## EXECUTION SEQUENCE (BACKTEST)
```
Loop over spot timestamps T0, T1, T2…
  At each T: row = get_latest_candle(option_df, T − 1s)  ← closed candle
  check_signal(row) → ALERT at candle C_alert
  Next T: row = C_entry; ENTRY if C_entry.high > C_alert.high
  entry_price = max(C_entry.open, C_alert.high)  ← SL-M simulation
  Management starts at next T (C_entry+15m) → no same-candle SL issue
```

## SAFE SL CALCULATION ORDER (never reorder)
```python
raw_dist = entry_price − alert_low + 1.0          # 1. Base
effective_dist = max(raw_dist, entry_price * min_sl_pct)  # 2. Floor first
if safe_sl_mode:
    effective_dist = min(effective_dist, safe_sl_max_loss / qty)  # 3. Cap wins
effective_sl = entry_price − effective_dist
```

## SL TRAIL LOGIC
```
single_lot: TP1 hit → SL = entry (break-even) | TP2 hit → SL = T1 price | TP3 = final exit
multi_lot:  TP1 → exit 1 lot + SL = entry    | TP2 → exit 1 lot + SL = T1 | TP3 = remaining
```

---

## INSTRUMENTS & LOT SIZES (post Sep 2025)
| Index | Expiry | Lot Size |
|-------|--------|----------|
| NIFTY | Weekly every Tuesday | 65 |
| BANKNIFTY | Monthly last Tuesday | 30 |
| SENSEX | Weekly every Thursday (commented out in config) | 20 |

## HISTORICAL LOT SIZES (critical for backtest P&L)
| Instrument | Period | Lot Size |
|------------|--------|----------|
| NIFTY | pre Sep 2025 | 75 |
| NIFTY | Sep 2025+ | 65 |
| BANKNIFTY | pre Nov 2024 | 25 |
| BANKNIFTY | Nov 2024 – Aug 2025 | 35 |
| BANKNIFTY | Sep 2025+ | 30 |
| SENSEX | May 2023 – Nov 2024 | 10 |
| SENSEX | Nov 2024+ | 20 |

---

## LIVE DEBUT CONFIG (when ready)
```yaml
lots_per_trade: 1
exit_mode: single_lot
single_lot_exit_target: 2   # T2 preferred (2026 data: SQ_OFF exits never reach T3)
safe_sl_max_loss: 2000
max_loss_per_day: 3000
paper_trading: false
```

---

## AUDIT PROTOCOL (run every session)
1. **Bias Hunt first:** check entry timing delta, AR < 0, SL vs original_sl
2. **Stats sanity:** WR 48-55% (single_lot), WR 65-75% (multi_lot), Sharpe >3 OK
3. **Red flags:** Any trade with `targets[0] < entry_price`, any `alert_range < 0`
4. **SL check:** `SL ≥ entry_price` → trailed SL (OK) | `original_sl ≥ entry_price` → bug

## CODE FIX FORMAT (token-efficient)
```
TASK ID: V16-P-XX
FILE: path/to/file.py
BROKEN CODE (lines X-Y): [exact lines]
REPLACEMENT: [new lines + 2-3 lines context]
VERIFY: python -c "[one-liner]"
```

---

## BROKER & INFRA
- **Broker:** Groww API (growwapi SDK)
- **Exchange:** NSE (NIFTY/BANKNIFTY) | BSE (SENSEX)
- **Notifications:** Telegram (multi-chat + owner-only)
- **Kill switch:** `touch /tmp/rsi_bot_kill`
- **Heartbeat:** `/tmp/rsi_bot_heartbeat.json` (updated every 60s)

## VERSION HISTORY (abbreviated)
```
V8  → crash recovery
V9  → historical lots, same-candle SL fix
V10 → safe_SL recalc
V11 → circuit breaker, RSI vectorization
V12 → capital concentration guard
V13 → verification suite
V14 → atomic writes, paper TP fills
V15 → TP3 paper block fix, drawdown fix, LTP cache
V16 → IN PROGRESS (see tasks above)
```

---

## QUICK COMMANDS
```bash
# Run backtest
python run_backtest.py

# Run OOS validation (all years)
python scripts/run_oos_validation.py

# Run OOS single year
python scripts/run_oos_validation.py 2023

# Compare year results
python scripts/compare_years.py reports/

# Pre-flight check
python scripts/preflight_check.py

# Run tests
pytest tests/

# Paper trading
python run_live.py

# Check bot health
bash scripts/check_bot.sh
```

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
