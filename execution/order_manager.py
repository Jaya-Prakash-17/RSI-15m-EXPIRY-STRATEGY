# execution/order_manager.py
import logging
import time
from core.groww_client import GrowwClient
from core.exceptions import InsufficientMarginError

def is_order_filled(status: str) -> bool:
    """
    Unified order fill check.
    Covers all Groww API status string variants.
    """
    if not status:
        return False
    return status.upper() in {'COMPLETE', 'FILLED', 'EXECUTED', 'COMPLETED'}

def is_partially_filled(status: str) -> bool:
    """Check for partial fill status."""
    if not status:
        return False
    return status.upper() in {'PARTIALLY_FILLED', 'PARTIAL'}

class OrderManager:
    def __init__(self, config):
        self.logger = logging.getLogger("OrderManager")
        self.config = config
        self.client = GrowwClient()

        # V17-H-01: Explicit tick sizes for Indian Indices (Real Money Safety)
        self.tick_sizes = {
            'NIFTY': 0.05,
            'BANKNIFTY': 0.05,
            'MIDCPNIFTY': 0.05,
            'FINNIFTY': 0.05,
            'SENSEX': 0.05,
            'BANKEX': 0.05
        }

        # Paper trading mode - simulates orders without real execution
        self.paper_trading = config.get('trading', {}).get('paper_trading', False)
        if self.paper_trading:
            self.logger.warning("*** PAPER TRADING MODE ENABLED - No real orders will be placed ***")

    def _resolve_lot_size(self, symbol, trading_symbol=None):
        """
        Resolve lot size from symbol. Checks in specificity order to avoid
        substring collision ('NIFTY' is a substring of 'BANKNIFTY').
        """
        symbol_text = f"{symbol or ''} {trading_symbol or ''}"

        # Check in order from most specific to least specific.
        # BANKNIFTY must come before NIFTY to avoid substring false match.
        check_order = ['BANKNIFTY', 'MIDCPNIFTY', 'SENSEX', 'NIFTY']

        for underlying in check_order:
            details = self.config.get('indices', {}).get(underlying, {})
            if details and underlying in symbol_text:
                lot_size = details.get('lot_size', 1)
                self.logger.debug(f"Resolved lot_size={lot_size} for {underlying} from symbol")
                return lot_size

        self.logger.warning(f"Could not resolve lot_size for symbol: {symbol}. Defaulting to 1.")
        return 1

    def _round_to_tick(self, price, symbol):
        """Round price to nearest valid tick (0.05) to avoid exchange rejection."""
        if price is None: return None

        # Resolve tick size (default 0.05 for Indian indices)
        tick = 0.05
        for index in self.tick_sizes:
            if index in str(symbol).upper():
                tick = self.tick_sizes[index]
                break

        return round(round(price / tick) * tick, 2)

    def place_entry_order(self, symbol, qty, price, trading_symbol, order_type="SL-M"):
        """
        Places an entry order.
        Requires trading_symbol for API safety.
        Returns full response to track order_id.
        """
        self.logger.info(f"Placing ENTRY for {symbol} (TS: {trading_symbol}) Qty: {qty} Trigger: {price}")

        # Paper trading mode - simulate order without API call
        if self.paper_trading:
            self.logger.info("[PAPER TRADE] Simulated entry order (no real order placed)")
            return {
                'groww_order_id': f"PAPER_{symbol}_{int(time.time())}",
                'status': 'PAPER',
                'message': 'Paper trade - no real order'
            }

        # Balance check - V6-P-007 (Defensive Check for Real Money)
        try:
            balance = self.client.get_balance()
            cost = qty * price
            if balance is None:
                self.logger.warning("Could not fetch balance. Proceeding with caution...")
            elif balance < cost:
                self.logger.warning(f"Insufficient margin: available ₹{balance}, required ₹{cost}")
                raise InsufficientMarginError(
                    f"Balance ₹{balance:.0f} < required ₹{cost:.0f}"
                )
        except InsufficientMarginError:
            raise
        except Exception as e:
            self.logger.error(f"Balance check error: {e}")

        # Ensure price is valid for exchange
        price = self._round_to_tick(price, symbol)

        resp = self.client.place_order(
            symbol=symbol,
            qty=qty,
            side="BUY",
            order_type=order_type,
            price=price,
            product="MIS",
            trading_symbol=trading_symbol
        )

        if resp and "groww_order_id" in resp:
            self.logger.info(f"Entry Order Placed: {resp['groww_order_id']}")
            return resp

        self.logger.error(f"Entry Order Failed: {resp}")
        return None

    def check_order_fill(self, order_id, timeout=30):
        """
        Polls order status until filled or timeout.

        Returns:
            float: The fill price if the order was filled.
            None:  If the order was cancelled, rejected, or timed out.

        Note: Automatically cancels the order on timeout to prevent orphaned fills.
        """
        start = time.time()
        while time.time() - start < timeout:
            status = self.client.get_order_status(order_id)
            if not status or status.get('status') == 'ERROR':
                self.logger.error(f"Error checking status for {order_id}")
                time.sleep(1)
                continue

            s = status.get('status')
            filled_qty = int(status.get('filled_quantity', 0))
            fill_price = float(status.get('fill_price', 0) or 0)

            if is_order_filled(s):
                self.logger.info(f"Order {order_id} FILLED: Qty={filled_qty}, Price=₹{fill_price}")
                return fill_price  # Returning just price for backward compatibility

            elif is_partially_filled(s):
                # For options, partial fills are rare, but handle it
                self.logger.warning(f"Order {order_id} PARTIALLY FILLED: {filled_qty} filled")
                # Wait a bit more to see if it completes
                time.sleep(2)
                continue

            elif s in ['REJECTED', 'CANCELLED', 'FAILED']:
                self.logger.error(f"Order {order_id} {s}")
                return None

            time.sleep(1)

        # Timeout - cancel the order to prevent orphaned fills
        self.logger.warning(f"Order {order_id} check timed out after {timeout}s. Cancelling to prevent orphan fill...")
        try:
            cancel_resp = self.client.cancel_order(order_id)
            if cancel_resp:
                self.logger.warning(f"Order {order_id} cancelled after timeout")
            else:
                self.logger.error(f"Failed to cancel order {order_id} after timeout — may still fill!")

            # Final status check — order may have filled between timeout and cancel
            time.sleep(2)
            final_status = self.client.get_order_status(order_id)
            if final_status and is_order_filled(final_status.get('status', '')):
                fill_price = float(final_status.get('fill_price', 0) or 0)
                self.logger.info(f"Order {order_id} filled during final check: ₹{fill_price}")
                return fill_price
        except Exception as e:
            self.logger.error(f"Error during timeout handling: {e}")

        return None

    def place_exit_order(self, symbol, qty, trading_symbol, reason="TARGET"):
        self.logger.info(f"Placing EXIT for {symbol} (TS: {trading_symbol}) Qty: {qty} Reason: {reason}")

        if self.paper_trading:
            self.logger.info("[PAPER TRADE] Simulated exit order (no real order placed)")
            return {
                'groww_order_id': f"PAPER_EXIT_{symbol}_{int(time.time())}",
                'status': 'PAPER',
                'message': 'Paper trade - no real order'
            }

        resp = self.client.place_order(
            symbol=symbol,
            qty=qty,
            side="SELL",
            order_type="MARKET",
            product="MIS",
            trading_symbol=trading_symbol
        )

        if resp and "groww_order_id" in resp:
            self.logger.info(f"Exit Order Placed: {resp['groww_order_id']}")
            return resp

        self.logger.error(f"Exit Order Failed: {resp}")
        return None

    def check_order_status(self, order_id):
        return self.client.get_order_status(order_id)

    def place_partial_exits(self, symbol, trading_symbol, signal, entry_price, actual_qty=None):
        """
        Place partial exit orders for multi-lot mode.
        """
        exit_mode = signal.get('exit_mode', 'multi_lot')
        lot_size = self._resolve_lot_size(symbol, trading_symbol)

        if actual_qty is not None:
            lots = actual_qty // lot_size if lot_size > 0 else 1
            total_qty = actual_qty
        else:
            lots = signal.get('lots_per_trade', 3)
            total_qty = lots * lot_size

        targets = signal['targets']
        sl_price = signal['sl']

        exit_orders = {
            'mode': exit_mode,
            'orders': [],
            'trail_state': 0,  # 0=initial, 1=after TP1, 2=after TP2, 3=after TP3
            'current_sl': sl_price,
            'alert_range': signal.get('alert_range', 0)
        }

        if exit_mode == 'multi_lot':
            # Use floor division step function for lots
            lots_per_tp = lots // 3          # floor division — always whole lots
            remainder   = lots - (2 * lots_per_tp)  # goes to TP3

            quantities = [
                lots_per_tp * lot_size,
                lots_per_tp * lot_size,
                total_qty - (2 * lots_per_tp * lot_size)
            ]

            for i, (qty, target_price) in enumerate(zip(quantities, targets)):
                tp_level = i + 1
                if qty <= 0:
                    exit_orders['orders'].append({
                        'target_level': tp_level,
                        'target_price': target_price,
                        'quantity': qty,
                        'status': 'skipped',
                        'order_id': None
                    })
                    continue
                lots_count = qty // lot_size if lot_size > 0 else qty
                self.logger.info(
                    f"Setting up partial exit TP{tp_level}: {qty} units ({lots_count} lot(s)) at ₹{target_price}"
                )

                # CRITICAL FIX #2: Actually place broker target orders (not just tracking)
                order_id = None
                if not self.paper_trading:
                    order_resp = self.place_target_order(symbol, qty, target_price, trading_symbol)
                    if order_resp and 'groww_order_id' in order_resp:
                        order_id = order_resp['groww_order_id']
                        self.logger.info(f"🎯 Broker Target TP{tp_level} placed: {order_id} @ ₹{target_price}")
                    else:
                        self.logger.warning(f"⚠️ Failed to place broker TP{tp_level} order — using software monitoring")

                exit_orders['orders'].append({
                    'target_level': tp_level,
                    'target_price': target_price,
                    'quantity': qty,
                    'status': 'pending',
                    'order_id': order_id
                })

        elif exit_mode == 'single_lot':
            # CRITICAL FIX #4: Use config-driven target
            target_idx = self.config.get('strategy', {}).get('single_lot_exit_target', 2) - 1
            target_price = targets[target_idx] if target_idx < len(targets) else targets[-1]
            tp_level = target_idx + 1
            exit_qty = total_qty

            self.logger.info(
                f"Setting up single-lot exit at TP{tp_level}: {exit_qty} units "
                f"({exit_qty // lot_size if lot_size > 0 else exit_qty} lot(s)) at ₹{target_price}"
            )

            # Place broker order in live mode
            order_id = None
            if not self.paper_trading:
                order_resp = self.place_target_order(symbol, exit_qty, target_price, trading_symbol)
                if order_resp and 'groww_order_id' in order_resp:
                    order_id = order_resp['groww_order_id']
                    self.logger.info(f"🎯 Broker Target TP{tp_level} placed: {order_id} @ ₹{target_price}")

            exit_orders['orders'].append({
                'target_level': tp_level,
                'target_price': target_price,
                'quantity': exit_qty,
                'status': 'pending',
                'order_id': order_id
            })

        return exit_orders

    def execute_partial_exit(self, symbol, trading_symbol, quantity, reason="TARGET"):
        """
        Execute a partial exit (market order).
        """
        return self.place_exit_order(symbol, quantity, trading_symbol, reason)

    def place_sl_order(self, symbol, qty, trigger_price, trading_symbol):
        """
        Place a broker-side Stop Loss order.
        """
        self.logger.info(f"Placing SL Order: {symbol} | Trigger: ₹{trigger_price} | Qty: {qty}")

        if self.paper_trading:
            import time
            self.logger.info("[PAPER TRADE] Simulated SL order placed")
            return {
                'groww_order_id': f"PAPER_SL_{int(time.time())}",
                'status': 'PAPER',
                'trigger_price': trigger_price
            }

        # Ensure trigger price is valid
        trigger_price = self._round_to_tick(trigger_price, symbol)

        resp = self.client.place_order(
            symbol=symbol,
            qty=qty,
            side="SELL",
            order_type="SL-M",  # Stop Loss Market
            price=trigger_price,  # Trigger price
            product="MIS",
            trading_symbol=trading_symbol
        )

        if resp and "groww_order_id" in resp:
            self.logger.info(f"SL Order Placed: {resp['groww_order_id']} @ ₹{trigger_price}")
            return resp

        self.logger.error(f"SL Order Failed: {resp}")
        return None

    def modify_sl_order(self, order_id, new_trigger_price, symbol, new_qty=None):
        """
        Modify an existing SL order (for trailing SL).
        """
        self.logger.info(f"Modifying SL Order {order_id} → New Trigger: ₹{new_trigger_price}")

        # Round new trigger price
        new_trigger_price = self._round_to_tick(new_trigger_price, symbol)

        if self.paper_trading:
            self.logger.info(f"[PAPER TRADE] SL order modified to ₹{new_trigger_price}")
            return {'groww_order_id': order_id, 'status': 'MODIFIED'}

        resp = self.client.modify_order(
            order_id=order_id,
            trigger_price=new_trigger_price,
            qty=new_qty
        )

        if resp:
            self.logger.info(f"SL Order Modified: {order_id} → ₹{new_trigger_price}")
            return resp

        self.logger.error(f"SL Order Modification Failed: {order_id}")
        return None

    def cancel_sl_order(self, order_id):
        """
        Cancel an existing SL order.
        """
        self.logger.info(f"Cancelling SL Order: {order_id}")

        if self.paper_trading:
            self.logger.info(f"[PAPER TRADE] SL order cancelled")
            return {'groww_order_id': order_id, 'status': 'CANCELLED'}

        resp = self.client.cancel_order(order_id)

        if resp:
            self.logger.info(f"SL Order Cancelled: {order_id}")
            return resp


        self.logger.error(f"SL Order Cancellation Failed: {order_id}")
        return None

    def place_target_order(self, symbol, qty, target_price, trading_symbol):
        """
        Place a broker-side Target (limit sell) order.
        """
        self.logger.info(f"Placing Target Order: {symbol} | Target: ₹{target_price} | Qty: {qty}")

        if self.paper_trading:
            import time
            self.logger.info("[PAPER TRADE] Simulated Target order placed")
            return {
                'groww_order_id': f"PAPER_TGT_{int(time.time())}_{target_price}",
                'status': 'PAPER',
                'target_price': target_price
            }

        # Ensure target price is valid
        target_price = self._round_to_tick(target_price, symbol)

        resp = self.client.place_order(
            symbol=symbol,
            qty=qty,
            side="SELL",
            order_type="LIMIT",  # Limit order at target price
            price=target_price,
            product="MIS",
            trading_symbol=trading_symbol
        )

        if resp and "groww_order_id" in resp:
            self.logger.info(f"Target Order Placed: {resp['groww_order_id']} @ ₹{target_price}")
            return resp

        self.logger.error(f"Target Order Failed: {resp}")
        return None

    def cancel_order(self, order_id):
        """
        Cancel any pending order by its order ID.
        """
        self.logger.info(f"Cancelling Order: {order_id}")

        if self.paper_trading:
            self.logger.info(f"[PAPER TRADE] Order {order_id} cancelled")
            return {'groww_order_id': order_id, 'status': 'CANCELLED'}

        resp = self.client.cancel_order(order_id)

        if resp:
            self.logger.info(f"Order Cancelled: {order_id}")
            return resp

        self.logger.error(f"Order Cancellation Failed: {order_id}")
        return None
