# Config Reference — RSI-15m Bot
> Place at: `docs/CONFIG_REFERENCE.md`

## Current Production config.yaml (key values)

```yaml
capital.initial: 200000          # Rs. 2L capital

strategy:
  rsi.period: 11                 # INTENTIONAL — do not change
  rsi.threshold: 60
  rsi.warmup_periods: 100
  rsi.min_candles_for_signal: 33  # = 11 * 3
  alert_validity: 1              # INTENTIONAL safety gate
  trade_only_on_expiry: false    # INTENTIONAL — trades every day
  exit_mode: single_lot
  lots_per_trade: 3              # For backtest analysis
  single_lot_exit_target: 3      # T3 in backtest; use T2 for live debut
  safe_sl_mode: true
  safe_sl_max_loss: 8000         # Rs. per trade (backtest)
  min_sl_pct: 0.10               # 10% floor
  min_alert_range_points: 0.5    # V16-P-01 guard

risk:
  max_consecutive_losses: 3      # Circuit breaker
  max_loss_per_day: 6000

trading:
  paper_trading: true            # ALWAYS true until all gates pass
  window.start: '09:45'
  window.end: '13:45'
  window.auto_square_off: '15:15'
```

## Live Debut Values (differ from above)
```yaml
lots_per_trade: 1
exit_mode: single_lot
single_lot_exit_target: 2    # T2, not T3 (more reliable per 2026 data)
safe_sl_max_loss: 2000       # Rs. 2000 (2% of 1L capital)
max_loss_per_day: 3000       # Rs. 3000
paper_trading: false
```

## Validation Rules (enforced by validate_config() in run_live.py)
| Parameter | Rule |
|-----------|------|
| `rsi.period` | > 0 |
| `alert_validity` | > 0 |
| `max_loss_per_day` | > 0 |
| `lots_per_trade` | > 0 |
| `single_lot_exit_target` | 1, 2, or 3 |
| `exit_mode` | 'single_lot' or 'multi_lot' |
| multi_lot mode | requires lots_per_trade ≥ 3 |
| `window.start < end ≤ auto_square_off` | required |
| `auto_square_off` | ≤ 15:30 (market close) |
| `safe_sl_max_loss / capital` | ≤ 5% (warn at 3%) |
| `warmup_periods` | > rsi.period |
| `paper_trading` | must be bool, not string |

## Charges (stress-tested, intentionally inflated)
```yaml
charges:
  brokerage_per_trade: 20   # Rs. per leg
  stt: 0.001                # 0.1% on sell premium
  exchange_txn_fee: 0.0006
  gst: 0.20                 # 20% (vs 18% actual — inflated intentionally)
  sebi_charges: 0.000003
  stamp_duty: 0.00006

reporting:
  slippage_model: position_scaled
  slippage_ticks_per_side: 1
  slippage_min_per_trade: 50
  slippage_max_per_trade: 500
```
