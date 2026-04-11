# Audit Trail — RSI-15m Expiry Breakout Bot
> Place at: `docs/AUDIT_TRAIL.md`

## Completed Audits (V1–V15)

### V15 — Final Pre-Deployment Audit ✅ CLEAN
- **Zero look-ahead bias** — all 1762 entries verified at T+1
- **SL exits correct** — intraday uses SL price; gap open uses open price
- **Multi-index independent trade state** working
- **Crash recovery, circuit breaker, daily loss limit, gap-fill guard** all functional
- **One unpatched bug:** Negative `alert_range` → V16-P-01

### V14
- Atomic writes via tempfile in `trade_tracker.py`
- Paper TP fills fixed (was using LTP instead of limit target price)

### V13
- Verification suite added (`tests/verify_residual_fixes.py`)

### V12
- Capital concentration guard (V12-P-03)
- NameError fix in SQ_OFF/DAILY_LOSS block

### V11
- Per-index trade lock (was global, now per-underlying)
- Circuit breaker (`max_consecutive_losses`)
- RSI vectorized (`batch_calculate_rsi`)

### V10
- Safe SL recalculation at entry using actual historical lot size
- Post-backtest `_verify_safe_sl_compliance()` audit
- SL floor/cap order fixed (floor first, then cap — cap always wins)
- Intraday gap-below-SL handling

### V9
- Historical lot sizes implemented (`utils/historical_lot_sizes.py`)
- Same-candle SL bug fixed (management starts T+2, not T+1)

### V8
- Crash recovery (pending entries JSON persistence)

---

## Known Issues by Version

### Pre-V9 (all fixed)
- Same-candle SL check (SL evaluated at entry candle)

### Pre-V10 (all fixed)
- SL gap overshoot (intraday halt fills at open price incorrectly)
- Historical lot sizes ignored (used config value only)

### Pre-V11 (all fixed)
- Global trade lock blocked per-index independent trading
- NameError in `exit_order_id` variable before conditional block

### Pre-V12 (all fixed)
- Capital concentration: no guard against over-sized positions

### Pre-V14 (all fixed)
- Paper trading TP fills used LTP (should use exact target price)

### Pre-V15 (all fixed)
- TP3 paper mode block incomplete (trade stayed open past TP3)
- Drawdown calculation included initial capital incorrectly
- LTP fetched on every loop (now 1s TTL cached)

### V15 OPEN → V16-P-01
```
Bug: Corrupt option data (high < low candles) produces negative alert_range
     → inverted targets (T1 < entry_price)
     → 8 affected trades in 2020-2025 OOS sample
Fix: strategy/expiry_rsi_breakout.py, check_signal()
     Add: if alert_range < self.min_alert_range: return None
     (config key: strategy.min_alert_range_points = 0.5)
```

---

## Surgical Fix Discipline
> An overcorrected SL fix once swung backtest returns from +69% to -8%.
> **Always:** precise, targeted fix with evidence before touching working logic.

## Settled Decisions (never re-open without new evidence)
- `alert_validity: 1` — deliberate safety gate
- `trade_only_on_expiry: false` — intentional
- RSI period = 11 — evolved from 9
- Sharpe ~5.9 — correct for per-trade ≈ per-day frequency
- SL fills at exact SL price — optimistic, offset by slippage buffer
- 1240 trades with `SL ≥ entry` — trailed SL, not a bug
- `same_candle_guard` dead code — architectural property (management T+2)
