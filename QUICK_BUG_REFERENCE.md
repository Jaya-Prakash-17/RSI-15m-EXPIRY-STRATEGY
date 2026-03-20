# QUICK BUG REFERENCE - One-Liner Fixes

## 🔴 CRITICAL BUGS (FIX BEFORE LIVE)

### BUG-001: P&L Calculation with Partial Exits
- **File:** `backtest/intraday_engine.py:343`
- **Issue:** Uses `trade['qty']` instead of `trade['remaining_qty']`
- **Fix:** Replace all `trade['qty']` with `trade['remaining_qty']` in `_manage_active_trade()` and `_close_trade()`

### BUG-002: RSI Caching Bug (Same RSI for All Symbols)
- **File:** `strategy/expiry_rsi_breakout.py:174-175`
- **Issue:** `prev_rsi` stale when processing multiple symbols at same time
- **Fix:** Add check `if current_candle_time != state['last_processed_time']:` before updating prev_rsi

### BUG-003: SL Trailing Not Implemented in Live
- **File:** `live/live_trader.py` - **ENTIRE MISSING FEATURE**
- **Issue:** Backtest trails SL after TP1/TP2, but live trading doesn't
- **Fix:** Implement `_modify_sl_after_partial_exit()` method in LiveTrader (see CRITICAL_AUDIT_REPORT.md)

### BUG-004: Hardcoded Lot Sizes
- **File:** Multiple locations
- **Issue:** NIFTY/BANKNIFTY lot size changed Sep 2025 (75→65, 35→30)
- **Fix:** Document data cutoff dates, note in config.yaml, regenerate pre-Sep 2025 CSVs with old lot sizes

### BUG-005: Exit Order Placement - No Retry
- **File:** `execution/order_manager.py:246`
- **Issue:** If exit order fails, position silently remains held
- **Fix:** Add retry loop (3 attempts) with 2s delay, raise exception on final failure

### BUG-006: Paper Trading Not Enforced Everywhere
- **File:** `execution/order_manager.py:246` (place_exit_order)
- **Issue:** Missing paper trading check in place_exit_order() and place_sl_order()
- **Fix:** Add `if self.paper_trading: return simulated_order` to all order placement methods

### BUG-007: Daily Loss Limit Checked AFTER Trade Entry
- **File:** `backtest/intraday_engine.py:200`
- **Issue:** Should check BEFORE entering, not after
- **Fix:** Move `if daily_pnl <= -max_loss_per_day: break` to line 198 (before trade entry)

### BUG-008: Pending Entry Not Persisted to Disk
- **File:** `live/live_trader.py:574`
- **Issue:** Pending orders not saved, can't recover after crash
- **Fix:** Add `self.tracker.save_pending_entries(self.pending_entries)` after pending order placed

### BUG-009: Trailing Stop Logic Doesn't Match Exit Mode
- **File:** `strategy/expiry_rsi_breakout.py` (doesn't know about exit modes)
- **Issue:** Strategy generates targets ignoring exit_mode config
- **Fix:** Make strategy aware of single_lot vs multi_lot mode when generating targets

### BUG-010: Config Validation Missing Critical Fields
- **File:** `run_live.py:51`
- **Issue:** Doesn't validate exit_mode, lots_per_trade, lot_sizes, expiry days
- **Fix:** Add comprehensive validation (see CRITICAL_AUDIT_REPORT.md for checklist)

### BUG-011: Option Symbol Construction Inconsistent
- **File:** `data/data_manager.py:340`, `backtest/intraday_engine.py:159`, `live/live_trader.py:350`
- **Issue:** Multiple places construct symbols differently (format mismatch)
- **Fix:** Create centralized `get_option_symbol()` function, use everywhere

---

## 🟠 MEDIUM SEVERITY ISSUES

| Issue | File | Line | Fix |
|-------|------|------|-----|
| No warmup data validation | backtest/intraday_engine.py | 140 | Assert `len(spot_df) >= warmup_candles` |
| No position limit per index | live/live_trader.py | 435 | Check active trades, not just pending entries |
| Telegram can fail silently | utils/telegram_notifier.py | N/A | Add try-catch + fallback logging |
| No volume requirement | backtest/intraday_engine.py | 238 | Add `if volume < min_volume: skip` |
| Charges unclear in backtest | reporting/performance.py | 51 | Add comment: "₹20 = brokerage on both entry+exit" |

---

## 📊 IMPACT SUMMARY

| Bug | Profitability Impact | Likelihood | Fix Priority |
|-----|---------------------|-----------|--------------|
| BUG-001: P&L Calculation | -5% (overstated) | High | 🔴 NOW |
| BUG-002: RSI Caching | -10% (missed trades) | High | 🔴 NOW |
| BUG-003: SL Trailing Missing | -15% (unmanaged risk) | Very High | 🔴 NOW |
| BUG-005: Exit Retry | -5% (locked capital) | Medium | 🔴 NOW |
| BUG-006: Paper Mode | -10% (accidental real trades) | Low | 🔴 NOW |
| BUG-007: Daily Loss Check | -8% (over-trading) | Medium | 🔴 NOW |
| Others | -5% combined | Low | 🟠 Before Live |

**Total Expected Impact Without Fixes:** -15% to -40% profitability reduction

---

## TESTING CHECKLIST BEFORE LIVE DEPLOYMENT

- [ ] Backtest 6 months of data, verify P&L matches expected range
- [ ] Test partial exit scenario: verify remaining_qty used correctly
- [ ] Test crash recovery: manually kill bot with pending orders, verify recovery
- [ ] Test exit order failure: mock API error, verify retry and exception
- [ ] Test paper trading: verify all orders simulated, no real trades
- [ ] Test config validation: provide invalid config, verify error messages
- [ ] Test multi-symbol processing: run with 3+ indices, verify RSI doesn't mix
- [ ] Test daily loss limit: enter trades until limit, verify no more trades
- [ ] Test symbol construction: verify same symbol format everywhere
- [ ] Test Telegram: verify all notification types work

---

## FILE MODIFICATION PRIORITY

**Tier 1 (Immediate - Do Today):**
1. `strategy/expiry_rsi_breakout.py` - RSI caching fix (15 min)
2. `backtest/intraday_engine.py` - Daily loss limit + warmup validation (20 min)
3. `execution/order_manager.py` - Paper mode enforcement (30 min)

**Tier 2 (This Week):**
4. `live/live_trader.py` - SL trailing implementation (1 hour)
5. `live/live_trader.py` - Pending entry persistence (30 min)
6. `execution/trade_tracker.py` - Verify persistence methods used correctly (15 min)

**Tier 3 (Before Live):**
7. `data/data_manager.py` - Centralize symbol construction (1 hour)
8. `run_live.py` - Comprehensive config validation (30 min)
9. Unit tests for exit logic (1-2 hours)

**Total Estimated Time:** 6-7 hours

---

## DO NOT DEPLOY UNTIL:

✅ All 11 critical bugs fixed
✅ Comprehensive backtest run successfully
✅ Paper trading test completed (5+ days)
✅ Crash recovery tested manually
✅ All unit tests passing
✅ Config validation strict
✅ Risk limits set appropriately
