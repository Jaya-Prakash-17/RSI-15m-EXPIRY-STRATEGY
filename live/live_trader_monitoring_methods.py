# live_trader.py - Enhanced _monitor_active_trades Method
# 
# REPLACE the existing _monitor_active_trades method (around line 363-400)
# with this enhanced version that supports trailing SL and partial exits

def _monitor_active_trades(self):
    """Monitor and manage active trades with trailing SL and partial exits."""
    active_trades = self.tracker.get_active_trades()
    
    for trade in active_trades:
        symbol = trade['symbol']
        trading_symbol = trade['trading_symbol']
        trade_id = trade['trade_id']
        
        # Get LTP
        ltp = self.client.get_ltp(symbol)
        if ltp is None:
            continue
        
        # Get exit orders info (may not exist for old trades)
        exit_orders = trade.get('exit_orders', None)
        if not exit_orders:
            # Legacy trade without exit orders - use old logic
            self._monitor_legacy_trade(trade, ltp)
            continue
        
        # Modern trade with partial exits and trailing SL
        exit_mode = exit_orders['mode']
        trail_state = exit_orders['trail_state']
        current_sl = exit_orders['current_sl']
        alert_range = exit_orders['alert_range']
        targets = trade['targets']
        
        # Check SL hit (always check first)
        if ltp <= current_sl:
            self.logger.info(f"🔴 SL HIT for {trade_id} at ₹{ltp} (Trailed SL: ₹{current_sl})")
            self._close_entire_position(trade, ltp, 'SL')
            continue
        
        # Check target hits and handle trailing/partial exits
        if exit_mode == 'multi_lot':
            self._handle_multi_lot_exits(trade, ltp, exit_orders, targets, trail_state, alert_range)
        elif exit_mode == 'single_lot':
            self._handle_single_lot_exits(trade, ltp, exit_orders, targets, trail_state, alert_range)

def _monitor_legacy_trade(self, trade, ltp):
    """Monitor trades without exit_orders (legacy format)."""
    symbol = trade['symbol']
    trading_symbol = trade['trading_symbol']
    trade_id = trade['trade_id']
    
    exit_triggered = False
    reason = None
    
    # Check SL
    if ltp <= trade['sl']:
        reason = 'SL'
        exit_triggered = True
        self.logger.info(f"🔴 SL HIT for {trade_id} at ₹{ltp}")
    
    # Check Target
    elif ltp >= trade['targets'][1]:  # Using T2 as main target
        reason = 'TARGET'
        exit_triggered = True
        self.logger.info(f"🟢 TARGET HIT for {trade_id} at ₹{ltp}")
    
    if exit_triggered:
        self._close_entire_position(trade, ltp, reason)

def _handle_multi_lot_exits(self, trade, ltp, exit_orders, targets, trail_state, alert_range):
    """Handle multi-lot mode: partial exits + trailing SL."""
    trade_id = trade['trade_id']
    symbol = trade['symbol']
    trading_symbol = trade['trading_symbol']
    
    # Check TP1 hit (not yet trailed)
    if ltp >= targets[0] and trail_state == 0:
        self.logger.info(f"🎯 TP1 HIT for {trade_id} at ₹{ltp}")
        
        # Execute partial exit (1 lot)
        exit_order = exit_orders['orders'][0]
        qty = exit_order['quantity']
        
        self.logger.info(f"Exiting {qty} lots at TP1...")
        self.om.execute_partial_exit(symbol, trading_symbol, qty, "TP1")
        exit_order['status'] = 'executed'
        
        # Trail SL
        new_sl = exit_orders['current_sl'] + alert_range
        exit_orders['current_sl'] = new_sl
        exit_orders['trail_state'] = 1
        
        self.logger.info(f"✅ Partial Exit: {qty} lots | SL trailed to ₹{new_sl}")
    
    # Check TP2 hit
    elif ltp >= targets[1] and trail_state == 1:
        self.logger.info(f"🎯 TP2 HIT for {trade_id} at ₹{ltp}")
        
        # Execute partial exit (1 lot)
        exit_order = exit_orders['orders'][1]
        qty = exit_order['quantity']
        
        self.logger.info(f"Exiting {qty} lots at TP2...")
        self.om.execute_partial_exit(symbol, trading_symbol, qty, "TP2")
        exit_order['status'] = 'executed'
        
        # Trail SL
        new_sl = exit_orders['current_sl'] + alert_range
        exit_orders['current_sl'] = new_sl
        exit_orders['trail_state'] = 2
        
        self.logger.info(f"✅ Partial Exit: {qty} lots | SL trailed to ₹{new_sl}")
    
    # Check TP3 hit (final exit)
    elif ltp >= targets[2] and trail_state == 2:
        self.logger.info(f"🎯 TP3 HIT for {trade_id} at ₹{ltp}")
        
        # Close remaining position
        self._close_entire_position(trade, ltp, 'TP3')

def _handle_single_lot_exits(self, trade, ltp, exit_orders, targets, trail_state, alert_range):
    """Handle single-lot mode: trailing SL only, exit at TP3."""
    trade_id = trade['trade_id']
    
    # Check TP1 hit (trail SL, don't exit)
    if ltp >= targets[0] and trail_state == 0:
        self.logger.info(f"🎯 TP1 reached for {trade_id} at ₹{ltp}")
        
        # Trail SL (no exit)
        new_sl = exit_orders['current_sl'] + alert_range
        exit_orders['current_sl'] = new_sl
        exit_orders['trail_state'] = 1
        
        self.logger.info(f"✅ SL trailed to ₹{new_sl} (no exit)")
    
    # Check TP2 hit (trail SL, don't exit)
    elif ltp >= targets[1] and trail_state == 1:
        self.logger.info(f"🎯 TP2 reached for {trade_id} at ₹{ltp}")
        
        # Trail SL (no exit)
        new_sl = exit_orders['current_sl'] + alert_range
        exit_orders['current_sl'] = new_sl
        exit_orders['trail_state'] = 2
        
        self.logger.info(f"✅ SL trailed to ₹{new_sl} (no exit)")
    
    # Check TP3 hit (final exit)
    elif ltp >= targets[2] and trail_state == 2:
        self.logger.info(f"🎯 TP3 HIT for {trade_id} at ₹{ltp}")
        
        # Close entire position
        self._close_entire_position(trade, ltp, 'TP3')

def _close_entire_position(self, trade, ltp, reason):
    """Close entire position and update tracker."""
    symbol = trade['symbol']
    trading_symbol = trade['trading_symbol']
    trade_id = trade['trade_id']
    qty = trade['qty']
    
    # Place exit order
    self.om.place_exit_order(symbol, qty, trading_symbol, reason)
    
    # Calculate P&L
    pnl = (ltp - trade['entry_price']) * qty
    self.daily_pnl += pnl
    
    # Close trade in tracker
    self.tracker.close_trade(trade_id, ltp, reason, pnl)
    
    self.logger.info(f"Trade closed: {trade_id} | P&L: ₹{pnl:.2f} | Daily P&L: ₹{self.daily_pnl:.2f}")
