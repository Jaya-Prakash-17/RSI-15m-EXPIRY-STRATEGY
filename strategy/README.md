# Strategy

The trading strategy implementation. One strategy per file.

## Files

| File | Purpose |
|---|---|
| `expiry_rsi_breakout.py` | **RSI Breakout strategy for expiry days.** Implements the full signal lifecycle: ALERT → ENTRY → NEGATED/EXPIRED. Calculates RSI(14) on 15-minute option candles, generates an alert when RSI crosses above 60 on a green candle, and triggers entry when price breaks the alert candle's high within the validity window. |

## Signal Lifecycle

```
RSI crosses 60 on green candle
        ↓
   ALERT generated
   (entry = alert_high, SL = alert_low - 1)
        ↓
  ┌─────┴──────┐
  │            │
Price breaks   Validity window
alert_high     expires (1 candle)
  │            │
ENTRY        EXPIRED / NEGATED
```

## Targets

- **T1 (1x)** = Entry + Alert Candle Range
- **T2 (2x)** = Entry + 2 × Alert Candle Range (Recommended)
- **T3 (3x)** = Entry + 3 × Alert Candle Range

## Config Dependencies

| Key | Purpose |
|---|---|
| `strategy.rsi.threshold` | Cross-above level (default: 60) |
| `strategy.alert_validity` | Max candles to wait for breakout (default: 2) |
| `strategy.single_lot_exit_target` | Multiplier used for exit in single-lot mode |
