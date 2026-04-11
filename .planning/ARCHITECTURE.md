# Architecture Reference — RSI-15m Expiry Breakout Bot
> Place at: `docs/ARCHITECTURE.md`

## Strategy Summary
| Parameter | Value |
|-----------|-------|
| Instruments | NIFTY, BANKNIFTY index options (SENSEX commented out) |
| Timeframe | 15-minute candles |
| RSI | Wilder's RSI(11), threshold = 60 |
| Entry trigger | Price breaks high of alert candle (SL-M BUY) |
| Alert validity | 1 candle (alert candle + 1 window) |
| Stop loss | Alert candle low − 1pt, floored at 10% of entry, capped by `safe_sl_max_loss` |
| Targets | T1 = entry + 1×range, T2 = entry + 2×range, T3 = entry + 3×range |

## Backtest Execution Loop
```
for each spot timestamp T:
    option_row = get_latest_candle(option_df, T - 1 second)  # CLOSED candle
    signal = check_signal(option_row, rsi_values=batch_rsi[symbol])

    if signal.action == 'ALERT':
        store alert state, wait for next T

    if signal.action == 'ENTRY':
        entry_price = max(entry_candle.open, alert_high)  # SL-M simulation
        _enter_trade(...)
        # Management starts NEXT T → no same-candle SL risk

    if active_trade:
        _manage_active_trade(...)  # checks SL and TPs
```

## Safe SL Calculation (ORDER IS CRITICAL)
```python
# Step 1: Base distance
raw_dist = entry_price - alert_low + 1.0

# Step 2: Apply FLOOR first (minimum breathing room)
effective_dist = max(raw_dist, entry_price * min_sl_pct)  # min_sl_pct = 0.10

# Step 3: Apply CAP last (hard ceiling, always wins over floor)
if safe_sl_mode:
    effective_dist = min(effective_dist, safe_sl_max_loss / qty)

effective_sl = entry_price - effective_dist
```

## Multi-Index Independence
- Each index (NIFTY, BANKNIFTY) holds **separate** active trade state
- `tracker.get_active_trades_for_index(underlying)` guards per-index
- NIFTY trade does NOT block BANKNIFTY signal

## SL Trail Mechanism
```
single_lot mode:
  TP1 crossed → SL moves to entry_price (break-even)
  TP2 crossed → SL moves to targets[0] (T1 price)
  Configured target hit → full exit

multi_lot mode (3 lots):
  TP1 hit → exit 1 lot, SL → entry_price
  TP2 hit → exit 1 lot, SL → targets[0]
  TP3 hit → exit remaining 1 lot
```

## V16-P-08: TP-before-SL Rule
When SL has been trailed ABOVE entry (profitable trail), and same candle
triggers both TP and SL:
- Price must pass THROUGH target to reach SL from below
- Therefore TP takes priority → check TP first in `_manage_active_trade()`

## RSI Vectorization (V11)
```python
# Old: O(N²) — calculate full RSI series per symbol per candle
# New: O(N) — pre-calculate entire RSI series per symbol once
rsi_cache[symbol] = strategy.calculate_wilder_rsi(df['close'].values)

# At each timestamp: lookup by index
curr_rsi = rsi_cache[symbol][curr_idx]
prev_rsi = rsi_cache[symbol][curr_idx - 1]
```

## Historical Lot Size Lookup
```python
# CRITICAL: Use get_historical_lot_size() NOT config lot_size for backtest P&L
from utils.historical_lot_sizes import get_historical_lot_size
lot_size = get_historical_lot_size('NIFTY', date(2023, 6, 15))  # returns 75, not 65
```

## Expiry Calendar (Single Source of Truth)
All expiry logic delegates to `utils/expiry_calendar.py`.
Never hardcode weekday names. The calendar handles:
- NIFTY: Thu → Tue (Sep 2025)
- BANKNIFTY: Thu → Wed → Thu → Tue (multiple transitions)
- SENSEX: Fri → Tue → Thu (BSE reforms)

## Crash Recovery Flow
```
Bot crash → restart → _reconcile_positions()
  1. Restore strategy state from data/strategy_state.json
  2. Check active trades (bot_trades.json)
  3. Load pending entries (pending_entries.json)
  4. For each pending: check broker status → activate/resume/discard
  5. Clear pending_entries file after reconciliation
```

## Paper vs Live Mode
| Feature | Paper | Live |
|---------|-------|------|
| Orders | Simulated | Real Groww API |
| SL trigger | LTP ≤ current_sl | Broker SL-M order filled |
| TP trigger | LTP ≥ target price | Limit SELL order filled |
| Gap fill | 50% midpoint simulation | Actual fill price from API |
| Crash risk | None | Orders persist at broker |

## File I/O Safety
- `trade_tracker.py`: All writes via `tempfile + os.replace()` (atomic)
- `pending_entries.json`: Same atomic pattern
- `strategy_state.json`: Same atomic pattern
- Cache invalidation: `tracker.invalidate_cache()` if file modified externally
