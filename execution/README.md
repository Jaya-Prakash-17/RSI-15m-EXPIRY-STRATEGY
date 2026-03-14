# Execution

Order management and trade state tracking for live trading.

## Files

| File | Purpose |
|---|---|
| `order_manager.py` | **Order execution layer.** Places entry orders (SL-M BUY), SL orders (SL-M SELL), target orders (LIMIT SELL), and market exit orders via the Groww API. Handles partial exits, SL modification (trailing), and order cancellation. Supports paper trading mode where orders are simulated locally. |
| `trade_tracker.py` | **Trade state manager.** Tracks active and closed trades with persistence to `data/bot_trades.json`. Manages trade lifecycle: add → update (partial exits, trailing SL) → close. Calculates daily P&L and provides trade queries for monitoring. |

## Order Types Used

| Order | Type | When |
|---|---|---|
| Entry | SL-M BUY | When alert is generated (triggers on breakout) |
| Stop Loss | SL-M SELL | Immediately after entry fill |
| Target | LIMIT SELL | At TP1, TP2, TP3 prices |
| Exit | MARKET SELL | Square-off or emergency close |

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
