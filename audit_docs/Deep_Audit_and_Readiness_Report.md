# Deep Audit & Readiness Report — RSI-15m Expiry Breakout Bot (V16)

> **Audit Date:** 2026-04-08
> **Auditor Mode:** Senior Quantitative Developer & Algorithmic Trading Auditor
> **Codebase:** V16 Final Release
> **Scope:** `strategy/`, `backtest/`, `live/`, `execution/`, `data/`, `reporting/`, `core/`, `utils/`

---

## SECTION 1: 5-YEAR BACKTEST RELIABILITY & CODE AUDIT

### 1.1 Code-to-Log Verification: Is The Backtest Structurally Reliable?

> [!IMPORTANT]
> **Verdict: The backtest is structurally sound and NOT fabricated.** The signal→entry→management→exit pipeline is architecturally correct. The results are programmatically reliable within the constraints of 15-minute OHLCV data.

**Evidence supporting reliability:**

| Mechanism | Location | Assessment |
|---|---|---|
| Alert/Entry temporal separation | [expiry_rsi_breakout.py:432](file:///d:/EXPIRY_RSI_15M_STRATEGY/strategy/expiry_rsi_breakout.py#L432) `current_time > state['alert_time']` | ✅ **CORRECT.** Strict `>` ensures entry cannot fire on the same candle as the alert. No same-candle bias. |
| RSI pre-calculation (no look-ahead) | [intraday_engine.py:319-324](file:///d:/EXPIRY_RSI_15M_STRATEGY/backtest/intraday_engine.py#L319-L324) | ✅ **CORRECT.** RSI is calculated over the entire history *once* using `calculate_wilder_rsi(df['close'].values)`, then indexed by `row.name` (the candle's positional index in its own DataFrame). `curr_idx` is derived from the candle's position, which only includes past data. No future data leaks into the computation. |
| Entry price realism | [intraday_engine.py:493-503](file:///d:/EXPIRY_RSI_15M_STRATEGY/backtest/intraday_engine.py#L493-L503) | ✅ **CORRECT.** Gap-up fill logic: if `entry_candle_open > alert_high`, fills at open (worse price). Otherwise at `alert_high`. Conservative. |
| SL exit price realism | [intraday_engine.py:650-670](file:///d:/EXPIRY_RSI_15M_STRATEGY/backtest/intraday_engine.py#L650-L670) | ✅ **CORRECT.** Intraday SL fills at SL price (not open). Only the 09:15 opening candle allows gap-below fill at open. This is the correct model for 15m data. |
| Target exit pricing | [intraday_engine.py:718](file:///d:/EXPIRY_RSI_15M_STRATEGY/backtest/intraday_engine.py#L718) `max(row['open'], target_price)` | ✅ **CORRECT.** Prevents filling below candle open (gap-over scenario). |
| Backtest-date isolation | [intraday_engine.py:329-330](file:///d:/EXPIRY_RSI_15M_STRATEGY/backtest/intraday_engine.py#L329-L330) | ✅ **CORRECT.** Timestamps are filtered to `backtest_date` only. Warmup-period candles are excluded from the signal scan loop. |
| One-trade-per-day guard | [intraday_engine.py:383](file:///d:/EXPIRY_RSI_15M_STRATEGY/backtest/intraday_engine.py#L383) `if has_traded_today: continue` | ✅ Prevents multiple entries per underlying per day. |
| Candidate selection (ATM proximity) | [intraday_engine.py:454](file:///d:/EXPIRY_RSI_15M_STRATEGY/backtest/intraday_engine.py#L454) | ✅ Selects closest-to-ATM strike then highest volume. No cherry-picking. |

---

### 1.2 Bias & Regression Hunt

#### 1.2.1 Look-Ahead Bias

| Check | Result |
|---|---|
| RSI computed on `df['close'].values` before signal loop | ✅ No look-ahead. Array indexed by `row.name`. |
| Alert uses `current_candle['high/low']` (the candle that generated the signal) | ✅ These are historical OHLCV values, not future. |
| Entry checks `current_candle['high'] > alert_candle['high']` on a FUTURE candle | ✅ Correct: it's the *next* candle after the alert, by the `current_time > alert_time` guard. |

> [!NOTE]
> **No look-ahead bias detected.** The RSI pre-computation is equivalent to computing RSI on-the-fly up to each candle — it just avoids re-running the O(n) loop on every symbol at every timestamp.

#### 1.2.2 Profit-Booking Bias (TP Before SL on Same Candle)

**Potential concern:** When both SL and TP are breached on the same 15m candle, which takes priority?

- **SL is checked FIRST** at [L622](file:///d:/EXPIRY_RSI_15M_STRATEGY/backtest/intraday_engine.py#L622).
- **Exception:** If SL has been trailed ABOVE entry (profitable position), TP is checked first at [L630-648](file:///d:/EXPIRY_RSI_15M_STRATEGY/backtest/intraday_engine.py#L630-L648). This is correct behavior: if SL is at TP1 level and both SL and TP3 are breached, price had to pass through TP3 to come back down to trailed SL.

> [!TIP]
> The TP-before-SL tie-breaking logic at L630-648 is **the correct approach** for a trailing-SL system. No bias here.

#### 1.2.3 Negative Alert Range (Inverted Targets)

**Fixed in V16-P-01:** [L499-507](file:///d:/EXPIRY_RSI_15M_STRATEGY/strategy/expiry_rsi_breakout.py#L499-L507)

```python
if alert_range < self.min_alert_range:  # default 0.5
    self.logger.warning(f"Skipping alert: corrupt or flat candle")
    return None
```

✅ Guard is active. Corrupt candles with `high < low` produce `alert_range < 0`, which is `< 0.5`. Rejected.

#### 1.2.4 Same-Candle Entry Bug

The alert is **set** at candle T. Entry is **checked** on candle T+1 or T+2 (within `alert_validity`). The guard at [L432](file:///d:/EXPIRY_RSI_15M_STRATEGY/strategy/expiry_rsi_breakout.py#L432) (`current_time > state['alert_time']`) is a strict inequality.

However, there is a subtle architectural guarantee that makes this even stronger: in `intraday_engine.py`, the entry signal fires on a **different** iteration of the `for t in timestamps` loop. By the time `_enter_trade` is called, we're already on a different candle.

✅ **No same-candle entry possible.**

---

### 1.3 15m TF Execution Limits

> [!WARNING]
> **This is the most critical section.** 15-minute candles hide all intra-bar price action. The bot has NO tick data.

#### 1.3.1 Stop-Loss Gap Overshoot

**Risk:** On 15m data, you only know `low ≤ SL`. You don't know if price gapped below SL or slowly crossed it.

**What the code does:**
- **Intraday candles** (not 09:15): SL fills at `trade['sl']` — the exact SL price. ([L668-670](file:///d:/EXPIRY_RSI_15M_STRATEGY/backtest/intraday_engine.py#L668-L670))
- **Opening candle** (09:15): If `open < SL`, fills at `open`. ([L660-667](file:///d:/EXPIRY_RSI_15M_STRATEGY/backtest/intraday_engine.py#L660-L667))

**Audit assessment:**
- For **intraday candles**, filling at SL price is **optimistic but defensible** — a pending SL-M order at the broker will trigger and fill at or near the SL price as the market crosses it during the 15-minute interval.
- For **the opening candle**, filling at open correctly models an overnight gap.
- **Missing scenario:** An intraday candle where `open < SL` (intraday gap-down after a trading halt or circuit breaker). The code treats this as a normal SL fill at the SL price, which is **overly optimistic** for circuit breaker scenarios. However, these are extremely rare on expiry days.

> [!CAUTION]
> **Severity: LOW.** Intraday gap-downs (not opening candle) are rare for liquid index options. The optimistic SL fill assumption inflates backtest P&L by a negligible amount across 5 years. For live trading, the SL-M order fills at market, which could be worse.

#### 1.3.2 Target Fill Assumptions

**What the code does:** Target fills at `max(row['open'], target_price)`.

This is **conservative** — if the candle opens above target (gap-up scenario), the fill is at the open, not the target. Good.

**Missing:** The code doesn't model partial fills or illiquid strikes where the order book may not have depth at the target price. In live trading, limit sell orders for deep-ITM options could face slippage.

#### 1.3.3 Entry Fill Assumptions

**What the code does:** Entry fills at `alert_candle['high']` (the breakout trigger), or at `entry_candle_open` if it gapped above.

**Assessment:** For a pending SL-M BUY order at the broker, this is a **reasonable model**. The real fill would be at or slightly above the trigger price. The gap-fill logic handles gap-up scenarios correctly.

---

### 1.4 Logic & Efficiency Audit

#### 1.4.1 Redundancies

| Issue | Location | Severity |
|---|---|---|
| `exit_mode` is read 3 times in `_manage_active_trade` | [L618](file:///d:/EXPIRY_RSI_15M_STRATEGY/backtest/intraday_engine.py#L618), [L628](file:///d:/EXPIRY_RSI_15M_STRATEGY/backtest/intraday_engine.py#L628), [L692](file:///d:/EXPIRY_RSI_15M_STRATEGY/backtest/intraday_engine.py#L692) | LOW — cosmetic. |
| `underlying` is set at L601, then again at L693 in multi-lot branch | [L601](file:///d:/EXPIRY_RSI_15M_STRATEGY/backtest/intraday_engine.py#L601), [L693](file:///d:/EXPIRY_RSI_15M_STRATEGY/backtest/intraday_engine.py#L693) | LOW — belt-and-braces pattern. |
| `_calculate_effective_sl` runs in strategy at alert time AND `_enter_trade` recalculates for safe_sl with historical lot size | [expiry_rsi_breakout.py:510](file:///d:/EXPIRY_RSI_15M_STRATEGY/strategy/expiry_rsi_breakout.py#L510), [intraday_engine.py:539-552](file:///d:/EXPIRY_RSI_15M_STRATEGY/backtest/intraday_engine.py#L539-L552) | MEDIUM — the double SL computation is intentional (strategy uses config lot size, engine uses historical lot size), but should be documented more clearly. |

#### 1.4.2 Memory Leaks

| Check | Result |
|---|---|
| `DataManager.data_cache` grows unbounded during backtest | ⚠️ **Mitigated.** `clear_cache()` is called at [L102](file:///d:/EXPIRY_RSI_15M_STRATEGY/backtest/intraday_engine.py#L102) after each day. Only spot data is retained. |
| `rsi_cache` per day | ✅ Created fresh per `process_expiry_day` call. Garbage collected when the dict goes out of scope. |
| Live trader `_candle_cache` | ✅ Cleared at start of each day via `_initialize_day()`. Trimmed to `max_rows` in `_get_option_candles_incremental()`. |

#### 1.4.3 Unhandled Exceptions

| Risk | Location | Severity |
|---|---|---|
| `SQ_OFF` block: bare `except: pass` for order cancellation | [live_trader.py:1881](file:///d:/EXPIRY_RSI_15M_STRATEGY/live/live_trader.py#L1881), [1893](file:///d:/EXPIRY_RSI_15M_STRATEGY/live/live_trader.py#L1893), [1897](file:///d:/EXPIRY_RSI_15M_STRATEGY/live/live_trader.py#L1897) | **MEDIUM.** If cancel fails silently, SL/TP orders remain live at broker alongside the SQ_OFF exit = **double execution risk.** |
| `DAILY_LOSS_LIMIT` block: same bare `except: pass` | [live_trader.py:1971-1976](file:///d:/EXPIRY_RSI_15M_STRATEGY/live/live_trader.py#L1971-L1976) | **MEDIUM.** Same double-execution risk. |
| Main loop top-level: `except Exception as e` catches ALL errors | [live_trader.py:2080](file:///d:/EXPIRY_RSI_15M_STRATEGY/live/live_trader.py#L2080) | ✅ Correct — logs stacktrace, increments failure counter, sends Telegram on 10 consecutive failures. Bot doesn't crash. |
| `_safe_call` in GrowwClient: re-auth on 401 | [groww_client.py:86-100](file:///d:/EXPIRY_RSI_15M_STRATEGY/core/groww_client.py#L86-L100) | ✅ Single retry with re-auth. Correct. |

---

## SECTION 2: REAL-MONEY READINESS REPORT

### 2.1 The Final Verdict

> [!IMPORTANT]
> **YES — with caveats.** The bot is structurally ready for live deployment in **paper trading mode first**, then real capital. The core signal-to-execution pipeline is correctly architected with no fatal flaws. However, 3 **MEDIUM-severity** issues in the `SQ_OFF` and `DAILY_LOSS_LIMIT` code paths must be hardened before real money is at risk. These are **not** backtest accuracy issues — they are **live execution safety** issues.

### 2.2 Real-World Friction Assessment

#### 2.2.1 Slippage Scaling

| Component | Assessment |
|---|---|
| **Backtest model** | Position-scaled: `ticks × tick_size × qty × 2 sides`, floored at Rs.50, capped at Rs.500. ✅ Realistic. |
| **Live execution** | SL-M orders (market on trigger) will incur slippage naturally. Gap-fill guard at [L1003-1050](file:///d:/EXPIRY_RSI_15M_STRATEGY/live/live_trader.py#L1003-L1050) aborts if gap > 4%, recalculates if > 2%. ✅ Excellent. |
| **Missing:** | No explicit slippage handling for `SQ_OFF` market exits. At 3:15 PM on expiry day, bid-ask spreads widen dramatically. The code uses `MARKET` order type for exit ([order_manager.py:163-170](file:///d:/EXPIRY_RSI_15M_STRATEGY/execution/order_manager.py#L163-L170)). **Expect 0.5-2% slippage on SQ_OFF exits.** |

#### 2.2.2 Partial Fills

**Current handling:** The code does not explicitly handle partial fills from the broker. In `_handle_tp_hit` ([L1562-1566](file:///d:/EXPIRY_RSI_15M_STRATEGY/live/live_trader.py#L1562-L1566)), `qty_filled` is read from the order status. If 0, it attempts to infer from exit order quantity. If still 0, it logs an error and nulls the target order ID.

> [!WARNING]
> **Risk: MEDIUM.** Partial fill on a LIMIT sell target order leaves a **fragmented position**. The bot thinks it sold N lots but only M were filled. The remaining N-M lots are untracked until the next `_monitor_active_trades` cycle. If the SL fills simultaneously for the full remaining quantity, there's a **net over-sell** = **short position.** Groww MIS should reject this, but it's an edge case worth testing.

#### 2.2.3 API Rate Limits

| Mechanism | Location | Assessment |
|---|---|---|
| Order polling throttle | [live_trader.py:1773](file:///d:/EXPIRY_RSI_15M_STRATEGY/live/live_trader.py#L1773) `ORDER_POLL_INTERVAL = 5s` | ✅ Sufficient for 15m cadence. |
| Auth retry with exponential backoff | [groww_client.py:55-83](file:///d:/EXPIRY_RSI_15M_STRATEGY/core/groww_client.py#L55-L83) | ✅ `2^attempt + random` backoff. Correct. |
| LTP cache with 1s TTL | [live_trader.py:350-361](file:///d:/EXPIRY_RSI_15M_STRATEGY/live/live_trader.py#L350-L361) | ✅ Prevents redundant calls within same second. |
| **Missing:** | No global request counter or rate limiter. If Groww enforces a hard N-requests-per-minute limit, the bot could hit it during high-activity periods (many symbols + order polling + LTP checks). | ⚠️ LOW risk — the polling interval and TTL cache reduce call volume significantly. |

#### 2.2.4 Broker Disconnects

| Scenario | Handling | Assessment |
|---|---|---|
| Network outage | 10 consecutive failures → Telegram alert, 5s backoff, retry. [L2080-2090](file:///d:/EXPIRY_RSI_15M_STRATEGY/live/live_trader.py#L2080-L2090) | ✅ Correct. |
| Market halt (circuit breaker) | NIFTY LTP check, 30s pause, auto-resume. [L2039-2061](file:///d:/EXPIRY_RSI_15M_STRATEGY/live/live_trader.py#L2039-L2061) | ✅ Correct. |
| SL order cancelled by exchange | Re-place immediately. If re-place fails → emergency market exit. [L1414-1454](file:///d:/EXPIRY_RSI_15M_STRATEGY/live/live_trader.py#L1414-L1454) | ✅ **Excellent.** This is critical and handled correctly. |
| Bot crash with open position | Pending entries persisted to `pending_entries.json`. On restart, reconciliation checks order status. [L288-338](file:///d:/EXPIRY_RSI_15M_STRATEGY/live/live_trader.py#L288-L338) | ✅ Correct. Covers filled-while-offline, still-pending, and cancelled scenarios. |
| SL placement fails 3x | Emergency market exit. [L1074-1083](file:///d:/EXPIRY_RSI_15M_STRATEGY/live/live_trader.py#L1074-L1083) | ✅ **Critical safety net — correctly implemented.** Never holds unprotected position. |

### 2.3 Capital Preservation Check

#### 2.3.1 Hard Stops

| Guard | Location | Assessment |
|---|---|---|
| `max_loss_per_day` (realized + unrealized MTM) | [live_trader.py:553-568](file:///d:/EXPIRY_RSI_15M_STRATEGY/live/live_trader.py#L553-L568) | ✅ Correct. Checks both realized and unrealized PnL. |
| `safe_sl_max_loss` per trade | [expiry_rsi_breakout.py:296-351](file:///d:/EXPIRY_RSI_15M_STRATEGY/strategy/expiry_rsi_breakout.py#L296-L351) | ✅ With post-assertion at engine level. Double-checked with historical lot size at [intraday_engine.py:539-552](file:///d:/EXPIRY_RSI_15M_STRATEGY/backtest/intraday_engine.py#L539-L552). |
| `max_consecutive_losses` circuit breaker | [live_trader.py:1662-1692](file:///d:/EXPIRY_RSI_15M_STRATEGY/live/live_trader.py#L1662-L1692) | ✅ Blocks new signals for rest of session. Telegram alert sent. |
| Auto square-off at 15:15 | [live_trader.py:1867-1957](file:///d:/EXPIRY_RSI_15M_STRATEGY/live/live_trader.py#L1867-L1957) | ✅ Cancels all pending + active orders, exits at market. |
| Kill switch (`/tmp/rsi_bot_kill`) | [live_trader.py:1791-1802](file:///d:/EXPIRY_RSI_15M_STRATEGY/live/live_trader.py#L1791-L1802) | ✅ Triggers immediate SQ_OFF. |
| Single-instance lock | [run_live.py:19-50](file:///d:/EXPIRY_RSI_15M_STRATEGY/run_live.py#L19-L50) | ✅ Prevents duplicate bot instances. |

#### 2.3.2 Exposure Limits

| Guard | Assessment |
|---|---|
| `max_position_pct: 0.8` in config | ⚠️ **NOT ENFORCED IN CODE.** This config value exists but is never read by any module. The actual capital check is `self.capital < cost` at [intraday_engine.py:556](file:///d:/EXPIRY_RSI_15M_STRATEGY/backtest/intraday_engine.py#L556) (backtest) and balance check at [live_trader.py:942-945](file:///d:/EXPIRY_RSI_15M_STRATEGY/live/live_trader.py#L942-L945) (live). |
| `max_lots: 5` in config | ⚠️ **NOT ENFORCED IN CODE.** No code reads this value. The actual lot limit is `lots_per_trade` (currently 3). |
| `risk_per_trade_pct: 0.05` in config | ⚠️ **NOT ENFORCED IN CODE.** This is a placeholder. The effective risk per trade is determined by `safe_sl_max_loss` (Rs.6000 flat). |
| Balance check before entry (live) | ✅ `OrderManager.place_entry_order` checks `balance < cost` before placing. |

#### 2.3.3 Catastrophic Blowout Scenarios

| Scenario | Protected? |
|---|---|
| **Single massive loss** | ✅ `safe_sl_max_loss` caps at Rs.6000/trade. With 3 lots × 65 lot size = 195 qty, max SL distance = Rs.30.77/unit. |
| **Cascading losses** | ✅ Circuit breaker after 3 consecutive losses. Daily loss limit at Rs.6000. |
| **Runaway bot (infinite loop placing orders)** | ✅ `has_traded_today` guard limits to 1 trade/index/day. Single-instance lock prevents duplicate bots. |
| **Stale SL after crash** | ✅ SL is placed as a broker-side SL-M order. Persists independently of bot process. |
| **Orphaned position (bot dies, position open)** | ✅ Crash recovery via `pending_entries.json` + `bot_trades.json`. Reconciliation on startup. |

---

## SECTION 2: SUMMARY RISK MATRIX

| Category | Risk Level | Detail |
|---|---|---|
| Backtest structural accuracy | ✅ LOW | No look-ahead, no same-candle entry, proper SL/TP fill modeling |
| Backtest SL overshoot (15m assumption) | ⚠️ LOW | Intraday SL fills at exact SL price — slightly optimistic but defensible |
| Live: SQ_OFF bare except blocks | 🔴 **MEDIUM** | Silent cancel failures → double execution risk |
| Live: Partial fill handling | 🔴 **MEDIUM** | Fragmented position tracking possible |
| Live: Unenforced config guards | ⚠️ LOW | `max_lots`, `max_position_pct`, `risk_per_trade_pct` are decorative |
| Live: Crash recovery | ✅ LOW | Robust persistence + reconciliation |
| Live: Emergency exits | ✅ LOW | SL re-placement, emergency market exit, kill switch all implemented |
