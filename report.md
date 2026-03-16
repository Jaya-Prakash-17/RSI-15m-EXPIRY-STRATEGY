# RSI-15 Expiry Breakout Bot - Bug Fix & API Reconnaissance Report
**Date:** March 2026
**Version:** 3.0

## 1. Overview
As requested, a comprehensive review of the active Bug Fix Specifications was performed against the Groww API documentation. The requisite fixes for order parsing, data tracking, paper-trading discrepancies, and API limits have been incorporated.

## 2. Bug Fixes Applied

### BUG-024: Order fill status tracking failing
**Problem:** Groww SDK returned slightly different variants of string values for completed order (`COMPLETED`, `COMPLETE`, `FILLED`, `EXECUTED`). This caused live trades to never activate and miss tracking.
**Fix:** Created a unified `is_order_filled(status: str) -> bool` helper in `execution/order_manager.py` that normalizes string status handling across the entire `live_trader.py`.

### BUG-023: Average Price Extraction Mismatch
**Problem:** The core wrapper `core/groww_client.py` was pulling `"avg_price": resp.get("average_fill_price", 0)`, but the live trading script was looking for `order_status.get('average_price')` or `.get('price')`. If unhandled, this returned 0 and skewed daily P&L limits to infinity.
**Fix:** Added fallback lookups (`.get('average_price') or .get('avg_price') or .get('price')`) globally in `live_trader.py` for pending entries, SL, and Target exits so it will accurately locate fill prices.

### BUG-022: Paper Trading Simulation Breakages
**Problem:** In Paper mode, when `get_ltp()` missed polling (returned None) during the square-off/loss limit exits, it threw TypeError exceptions and blocked loop execution. Also, Target Hit simulated P&Ls weren't recorded correctly against the daily limits in paper mode.
**Fix:** Implemented safe fallbacks (`ltp = client.get_ltp() or trade['entry_price']`) in square-off routines. Ensured `_handle_paper_tp_hit` calculates P&L correctly by lot sizes.

### BUG-021: Global vs Per-Index Active Trade tracking
**Problem:** Once ONE trade was entered on NIFTY, the bot blocked new setups on BANKNIFTY due to a global `has_active_trades` guard logic constraint.
**Fix:** Created `has_active_trade_for_index(index)` in `TradeTracker` array parsing. The monitoring logic checks per underlying instead of blocking across all indices globally.

### BUG-002: Broker SL modification failing after partial exits
**Problem:** A bug prevented SL (Stop Loss) orders from dynamically trailing after TP1 and TP2 were reached due to missing modification tracking.
**Fix:** Handled explicitly inside `_handle_multi_lot_exits()` by extracting standard `self.om.modify_sl_order(sl_order_id, new_sl, remaining_qty)` modifications dynamically.

### BUG-003: Single Exit config inconsistencies
**Problem:** The single-lot targets incorrectly exited fully at T3 in live execution whereas the backtest targeted T2 by default configuration.
**Fix:** Used `target_idx = self.config['strategy'].get('single_lot_exit_target', 2) - 1` strictly rather than hardcoded variables within `_handle_single_lot_exits()`.

### BUG-007: Backtesting Data Limitation handling
**Problem:** The official Groww documentation explicitly highlights Backtesting and chunk limits for fetching derivative candles dynamically. Overloading historical days caused silent DataFrame truncation.
**Fix:** Ensured `MAX_DAYS_PER_CHUNK` limits align effectively allowing `15` and `30` minute timeframe data limits to download efficiently across chunks using `HistoricalDownloader`.

## 3. Order Strategy Recon (Smart Orders vs SL-M)
As per your query regarding `https://groww.in/trade-api/docs/python-sdk/smart-orders`:
The Groww SDK documentation for Smart Orders (`GTT` / `OCO` Orders) indicates that OCO orders work phenomenally well for Single-Take Profit / Single SL exits, immediately canceling the opposing pending order when one fills. Current native integration within Groww handles it smoothly:
- **Challenge specific to our Strategy:** The RSI-15 breakout heavily relies on **Partial Execution (Trailing SL on multi-lots at TP1, TP2, TP3)**. Smart OCO orders natively do not support three partial target branches linking back to one continuously trailing Stop Loss.
- **Action Taken:** Due to this strict risk management format in the strategy, the standard SL / SL-M fallback tracking loop previously implemented in `live_trader.py` with the updated code holds the highest structural reliability over implementing standard fixed OCOs.

## 4. Final Cleanup
- Extraneous test files (`tmp_download_test.py`) deleted.
- Local historical datasets retained for smooth functioning.
- End-to-end unit regression backtest executes optimally.

Codebase committed effectively maintaining production standards.
