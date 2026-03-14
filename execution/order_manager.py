# execution/order_manager.py
import logging
import time
from core.groww_client import GrowwClient

class OrderManager:
    def __init__(self, config):
        self.logger = logging.getLogger("OrderManager")
        self.config = config
        self.client = GrowwClient()
        
        # Paper trading mode - simulates orders without real execution
        self.paper_trading = config.get('trading', {}).get('paper_trading', False)
        if self.paper_trading:
            self.logger.warning("*** PAPER TRADING MODE ENABLED - No real orders will be placed ***") 

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
                'groww_order_id': f"PAPER_{symbol}_{int(pd.Timestamp.now().timestamp())}",
                'status': 'PAPER',
                'message': 'Paper trade - no real order'
            }
        
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
        Returns fill_result dict with filled_qty and avg_price, or None if failed.
        Automatically cancels order on timeout.
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
            avg_price = float(status.get('avg_price', 0) or 0)
            
            if s in ['EXECUTED', 'COMPLETED']:
                self.logger.info(f"Order {order_id} FILLED: Qty={filled_qty}, Price=₹{avg_price}")
                return avg_price  # Returning just price for backward compatibility
            
            elif s == 'PARTIALLY_FILLED':
                # For options, partial fills are rare, but handle it
                self.logger.warning(f"Order {order_id} PARTIALLY FILLED: {filled_qty} filled")
                # Wait a bit more to see if it completes
                time.sleep(2)
                continue
            
            elif s in ['REJECTED', 'CANCELLED', 'FAILED']:
                self.logger.error(f"Order {order_id} {s}")
                return None
            
            time.sleep(1)
        
        # Timeout - cancel the order
        self.logger.warning(f"Order {order_id} check timed out after {timeout}s. Attempting to cancel...")
        try:
            # Cancel order (implement if Groww API supports)
            # cancel_resp = self.client.cancel_order(order_id)
            self.logger.warning("Order cancellation not implemented. Manual check required.")
            
            # Final status check
            time.sleep(2)
            final_status = self.client.get_order_status(order_id)
            if final_status and final_status.get('status') in ['EXECUTED', 'COMPLETED']:
                avg_price = float(final_status.get('avg_price', 0) or 0)
                self.logger.info(f"Order {order_id} filled during final check: ₹{avg_price}")
                return avg_price
        except Exception as e:
            self.logger.error(f"Error during timeout handling: {e}")
        
        return None

    def place_exit_order(self, symbol, qty, trading_symbol, reason="TARGET"):
        self.logger.info(f"Placing EXIT for {symbol} (TS: {trading_symbol}) Qty: {qty} Reason: {reason}")
        
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
    
    def place_partial_exits(self, symbol, trading_symbol, signal, entry_price):
        """
        Place partial exit orders for multi-lot mode.
        
        Args:
            symbol: Base symbol (e.g., 'NSE-BANKNIFTY-27Jan26-59700-PE')
            trading_symbol: Broker trading symbol
            signal: Entry signal with targets and exit config
            entry_price: Actual entry fill price
        
        Returns:
            dict: Exit orders info with order IDs and tracking state
        """
        exit_mode = signal.get('exit_mode', 'multi_lot')
        lots = signal.get('lots_per_trade', 3)
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
            # Place 3 partial exit orders
            lot_qty = lots // 3
            remaining_qty = lots - (2 * lot_qty)
            
            # TP1: 33% (1 lot)
            self.logger.info(f"Setting up partial exit TP1: {lot_qty} lots at ₹{targets[0]}")
            exit_orders['orders'].append({
                'target_level': 1,
                'target_price': targets[0],
                'quantity': lot_qty,
                'status': 'pending'
            })
            
            # TP2: 33% (1 lot)
            self.logger.info(f"Setting up partial exit TP2: {lot_qty} lots at ₹{targets[1]}")
            exit_orders['orders'].append({
                'target_level': 2,
                'target_price': targets[1],
                'quantity': lot_qty,
                'status': 'pending'
            })
            
            # TP3: 34% (remaining lot)
            self.logger.info(f"Setting up partial exit TP3: {remaining_qty} lots at ₹{targets[2]}")
            exit_orders['orders'].append({
                'target_level': 3,
                'target_price': targets[2],
                'quantity': remaining_qty,
                'status': 'pending'
            })
            
        elif exit_mode == 'single_lot':
            # Single exit at TP3
            self.logger.info(f"Setting up single-lot exit at TP3: {lots} lots at ₹{targets[2]}")
            exit_orders['orders'].append({
                'target_level': 3,
                'target_price': targets[2],
                'quantity': lots,
                'status': 'pending'
            })
        
        return exit_orders
    
    def execute_partial_exit(self, symbol, trading_symbol, quantity, reason="TARGET"):
        """
        Execute a partial exit (market order).
        
        Args:
            symbol: Symbol to exit
            trading_symbol: Trading symbol for API
            quantity: Number of lots to exit
            reason: Exit reason for logging
        
        Returns:
            Order response or None
        """
        return self.place_exit_order(symbol, quantity, trading_symbol, reason)

    def place_sl_order(self, symbol, qty, trigger_price, trading_symbol):
        """
        Place a broker-side Stop Loss order.
        This order persists with the broker even if bot crashes.
        
        Args:
            symbol: Option symbol
            qty: Quantity to sell on SL trigger
            trigger_price: Price at which SL triggers
            trading_symbol: Trading symbol for API
        
        Returns:
            Order response with groww_order_id for tracking
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

    def modify_sl_order(self, order_id, new_trigger_price, new_qty=None):
        """
        Modify an existing SL order (for trailing SL).
        
        Args:
            order_id: groww_order_id of the SL order
            new_trigger_price: New trigger price for trailing
            new_qty: New quantity (optional, for partial exits)
        
        Returns:
            Modified order response or None
        """
        self.logger.info(f"Modifying SL Order {order_id} → New Trigger: ₹{new_trigger_price}")
        
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
        Called when target is hit or position is closed manually.
        
        Args:
            order_id: groww_order_id of the SL order to cancel
        
        Returns:
            Cancellation response or None
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
        This order remains pending until price reaches target.
        
        Args:
            symbol: Option symbol
            qty: Quantity to sell at target
            target_price: Price at which to sell (limit price)
            trading_symbol: Trading symbol for API
        
        Returns:
            Order response with groww_order_id for tracking
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
        
        Args:
            order_id: groww_order_id of the order to cancel
        
        Returns:
            Cancellation response or None
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
