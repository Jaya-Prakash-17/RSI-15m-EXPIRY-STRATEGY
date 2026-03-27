# Execution

Order management and trade state tracking for live trading.

## Files

| File | Purpose |
|---|---|
| `order_manager.py` | **Order execution layer.** Places entry (SL-M), SL (SL-M), and Target (LIMIT) orders. Handles partial exits and trails broker-side SL orders using modification requests. Supports paper trading simulation. |
| `trade_tracker.py` | **Trade state manager.** Persists state to `data/bot_trades.json`. Tracks P&L, remaining quantity, and active exit orders. |

## Order Types Used

| Order | Type | When |
|---|---|---|
| Entry | SL-M BUY | Placed on alert (triggers on breakout) |
| Stop Loss | SL-M SELL | Placed immediately after entry fill |
| Target | LIMIT SELL | Placed at TP1, TP2, TP3 prices |
| Management | MODIFY | Used to jump SL price on target hits (trailing) |

## Trailing SL Logic

1. **Entry**: SL = Alert Low - 1.
2. **TP1 Hit**: Exit 1/3 qty. SL jumps to `Entry Price + Buffer`.
3. **TP2 Hit**: Exit 1/3 qty. SL jumps to `TP1 Price`.
4. **TP3 Hit**: Full exit.

## Trade Lifecycle

```
OrderManager                    TradeTracker
    │                               │
place_entry_order() ──────► add_active_trade()
    │                               │
place_sl_order()                    │
place_target_order()                │
    │                               │
execute_partial_exit() ────► update_trade(remaining_qty)
modify_sl_order() ─────────► update_trade(exit_orders)
    │                               │
place_exit_order() ────────► close_trade(pnl)
```
