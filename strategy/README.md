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

- **T1** = Entry + 1× alert candle range
- **T2** = Entry + 2× alert candle range
- **T3** = Entry + 3× alert candle range

## Key Config Dependencies

| Config Key | Effect |
|---|---|
| `strategy.rsi.period` | RSI calculation period (default: 14) |
| `strategy.rsi.threshold` | RSI level that triggers alert (default: 60) |
| `strategy.rsi.warmup_periods` | Candles needed before RSI is stable (default: 100) |
| `strategy.alert_validity` | Candles allowed for breakout after alert (default: 1) |
| `strategy.exit_mode` | `multi_lot` or `single_lot` |
| `strategy.single_lot_exit_target` | Which target exits in single-lot mode (1=T1, 2=T2, 3=T3) |
