# live/live_trader.py
import logging
import time
import sys
import math
import pandas as pd
from datetime import datetime, timedelta
from data.data_manager import DataManager
from execution.order_manager import OrderManager
from execution.trade_tracker import TradeTracker
from strategy.expiry_rsi_breakout import ExpiryRSIBreakout
from core.groww_client import GrowwClient
from utils.trade_logger import TradeLogger
from utils.telegram_notifier import TelegramNotifier

class LiveTrader:
    def __init__(self, config):
        self.logger = logging.getLogger("LiveTrader")
        self.config = config
        self.dm = DataManager(config)
        self.om = OrderManager(config)
        self.client = GrowwClient()
        self.strategy = ExpiryRSIBreakout(config)
        self.tracker = TradeTracker()  # Bot trade tracking
        self.trade_logger = TradeLogger(config)  # CSV trade audit log
        self.telegram = TelegramNotifier()  # Telegram alerts
        
        # Paper trading mode
        self.paper_trading = config['trading'].get('paper_trading', True)
        if self.paper_trading:
            self.logger.warning("=" * 60)
            self.logger.warning("⚠️  PAPER TRADING MODE - NO REAL ORDERS WILL BE PLACED")
            self.logger.warning("=" * 60)
        else:
            self.logger.warning("=" * 60)
            self.logger.warning("🔴 LIVE TRADING MODE - REAL MONEY AT RISK!")
            self.logger.warning("=" * 60)
        
        # State management
        self.tracked_options = {}
        self.spot_symbol = None
        self.expiry_date = None
        self.underlying = None
        
        self.last_candle_time = None
        self.last_processed_candle_time = {}
        
        # Pending entry orders (SL-M BUY orders waiting for fill)
        # Structure: {symbol: {'order_id': str, 'trigger_price': float, 'alert_candle': dict, 
        #                      'signal': dict, 'underlying': str, 'expiry_date': date, 'placed_at': datetime}}
        self.pending_entries = {}
        
        # Active trade orders (for tracking all orders related to a trade)
        # Structure: {trade_id: {'entry_order_id': str, 'sl_order_id': str, 
        #                        'target_order_ids': [str, str, str], 'status': str}}
        self.active_orders = {}
        
        # Daily P&L tracking
        self.daily_pnl = 0.0
        self.max_loss_per_day = config['risk']['max_loss_per_day']
        
        # Trading window
        self.start_time = datetime.strptime(config['trading']['window']['start'], "%H:%M").time()
        self.end_time = datetime.strptime(config['trading']['window']['end'], "%H:%M").time()
        self.sq_off_time = datetime.strptime(config['trading']['window']['auto_square_off'], "%H:%M").time()
        
        # Configuration
        self.trade_only_on_expiry = config['strategy'].get('trade_only_on_expiry', True)

    def _get_tradeable_indices(self):
        """Get all indices that should be traded today."""
        today_str = datetime.now().strftime("%Y-%m-%d")
        day_name = datetime.now().strftime("%A")
        
        tradeable = []
        
        # If trade_only_on_expiry is False, trade ALL configured indices
        if not self.trade_only_on_expiry:
            indices = list(self.config['indices'].keys())
            self.logger.info(f"trade_only_on_expiry=False, trading ALL indices: {indices}")
            return indices
        
        # Otherwise, only trade indices that have expiry today
        for idx, details in self.config['indices'].items():
            if details['expiry_day'] == day_name:
                try:
                    expiries = self.dm.get_expiries(idx)
                    if today_str in expiries:
                        self.logger.info(f"Confirmed API Expiry for {idx} today.")
                        tradeable.append(idx)
                    else:
                        self.logger.warning(f"Config says {idx} expiry today, but API expiries: {expiries}")
                except Exception as e:
                    self.logger.error(f"Error checking expiries for {idx}: {e}")
        
        return tradeable

    def _initialize_day(self):
        """Initialize trading for the day."""
        self.underlyings = self._get_tradeable_indices()
        if not self.underlyings:
            if self.trade_only_on_expiry:
                self.logger.info("No confirmed expiry today and trade_only_on_expiry=True. Exiting.")
            else:
                self.logger.info("No indices available for trading.")
            return False
        
        self.logger.info(f"="*60)
        self.logger.info(f"Trading today on: {', '.join(self.underlyings)}")
        self.logger.info(f"="*60)
        
        # Notify Telegram that bot has started
        mode = "PAPER" if self.paper_trading else "LIVE"
        self.telegram.bot_started(
            mode=mode,
            window_start=self.config['trading']['window']['start'],
            window_end=self.config['trading']['window']['end']
        )
        
        self.expiry_dates = {}
        self.spot_symbols = {}
        
        for underlying in self.underlyings:
            self.expiry_dates[underlying] = datetime.now().date()
            self.spot_symbols[underlying] = underlying
            self.tracked_options[underlying] = {}  # Nested dict: {underlying: {symbol: df}}
        
        # Reconcile positions on startup
        self._reconcile_positions()
        
        # Reset daily P&L
        self.daily_pnl = self.tracker.get_daily_pnl()
        self.logger.info(f"Daily P&L at startup: ₹{self.daily_pnl:.2f}")
        
        return True

    def _reconcile_positions(self):
        """Reconcile bot trades with broker positions on startup."""
        self.logger.info("Reconciling positions with broker...")
        
        try:
            # Get broker positions (implement this in GrowwClient if available)
            # For now, just verify our tracked trades
            active_trades = self.tracker.get_active_trades()
            
            if active_trades:
                self.logger.warning(f"Found {len(active_trades)} active trades from previous session:")
                for trade in active_trades:
                    self.logger.warning(f"  - {trade['symbol']} | Qty: {trade['qty']} | Entry: {trade['entry_price']}")
                self.logger.warning("⚠️  These positions will be managed by the bot")
            else:
                self.logger.info("No active bot trades found. Starting fresh.")
        
        except Exception as e:
            self.logger.error(f"Error during position reconciliation: {e}")

    def _get_latest_candle(self, df, t):
        """Get the latest candle at or before time t."""
        matches = df[df['datetime'] <= t]
        if matches.empty: return None
        return matches.iloc[-1]

    def _get_warmup_start_time(self):
        """Calculate start time for RSI warmup period."""
        # Get warmup period from strategy (in number of candles)
        warmup_candles = self.strategy.rsi_warmup
        
        # Each candle is 15 minutes
        warmup_minutes = warmup_candles * 15
        
        # Start from market open today
        now = datetime.now()
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        
        # Go back by warmup period (usually will be previous day)
        warmup_start = market_open - timedelta(minutes=warmup_minutes)
        
        self.logger.info(f"RSI warmup requires {warmup_candles} candles ({warmup_minutes} min), fetching from {warmup_start}")
        
        return warmup_start

    def _update_option_universe(self):
        """Update tracked option universe based on current spot price for ALL indices."""
        now = datetime.now()
        warmup_start = self._get_warmup_start_time()
        
        for underlying in self.underlyings:
            spot_symbol = self.spot_symbols.get(underlying, underlying)
            expiry_date = self.expiry_dates.get(underlying, datetime.now().date())
            
            try:
                # Fetch spot data with warmup
                spot_df = self.dm.get_spot_candles(spot_symbol, warmup_start, now, refresh=True)
            except Exception as e:
                self.logger.error(f"Failed to fetch spot data for {underlying}: {e}")
                continue
            
            # Validate spot_df
            if spot_df is None or spot_df.empty:
                self.logger.warning(f"Spot data empty for {underlying}. Skipping.")
                continue
            
            if 'datetime' not in spot_df.columns:
                self.logger.warning(f"Spot data for {underlying} missing 'datetime' column. Skipping.")
                continue

            current_spot_row = self._get_latest_candle(spot_df, now)
            if current_spot_row is None:
                self.logger.warning(f"No spot candle found for {underlying} at current time.")
                continue

            current_spot = current_spot_row['close']
            
            strike_gap = 50 if underlying == 'NIFTY' else 100
            if underlying == 'SENSEX': strike_gap = 100
            
            center_strike = round(current_spot / strike_gap) * strike_gap
            strikes = [
                center_strike - 2*strike_gap,
                center_strike - strike_gap,
                center_strike,
                center_strike + strike_gap,
                center_strike + 2*strike_gap
            ]
            
            for strike in strikes:
                for opt_type in ['CE', 'PE']:
                    symbol = self.dm.build_option_symbol(underlying, expiry_date, strike, opt_type)
                    
                    # Ensure nested dict structure
                    if underlying not in self.tracked_options:
                        self.tracked_options[underlying] = {}
                    
                    if symbol not in self.tracked_options[underlying]:
                        self.logger.info(f"Adding {symbol} to tracking for {underlying}.")
                        self.tracked_options[underlying][symbol] = pd.DataFrame()

    def _poll_candle_close(self):
        """Check if a new candle has closed (uses first underlying for timing)."""
        now = datetime.now()
        warmup_start = self._get_warmup_start_time()
        
        # Use first underlying for candle timing (all indices have same candle timing)
        first_underlying = self.underlyings[0] if self.underlyings else None
        if not first_underlying:
            return False
        
        spot_symbol = self.spot_symbols.get(first_underlying, first_underlying)
        
        try:
            spot_df = self.dm.get_spot_candles(spot_symbol, warmup_start, now, refresh=True)
            latest_candle = self._get_latest_candle(spot_df, now)
            if latest_candle is None: return False
            latest_candle_time = latest_candle['datetime']
            
            if self.last_candle_time is None:
                self.last_candle_time = latest_candle_time
                return False
            
            if latest_candle_time > self.last_candle_time:
                self.logger.info(f"New Candle Closed: {latest_candle_time}")
                self.last_candle_time = latest_candle_time
                return True
        except Exception as e:
            self.logger.error(f"Error polling candle: {e}")
        return False

    def _round_to_tick(self, price, underlying=None):
        """Round price to tick size for given underlying."""
        if underlying is None:
            underlying = self.underlyings[0] if self.underlyings else 'NIFTY'
        tick_size = self.config['indices'].get(underlying, {}).get('tick_size', 0.05)
        return round(price / tick_size) * tick_size

    def _check_daily_loss_limit(self):
        """Check if daily loss limit is breached."""
        if self.daily_pnl <= -self.max_loss_per_day:
            self.logger.critical(f"🛑 DAILY LOSS LIMIT BREACHED: ₹{self.daily_pnl:.2f} / ₹{-self.max_loss_per_day:.2f}")
            return True
        return False

    def _process_strategy_logic(self):
        """Process strategy logic for all tracked options across ALL indices.
        
        Handles:
        - ALERT: Places pending SL-M BUY order
        - NEGATED/EXPIRED: Cancels pending entry order
        - ENTRY: For backward compatibility (breakout already happened)
        """
        if self._check_daily_loss_limit():
            self.logger.warning("Daily loss limit reached. Skipping new signals.")
            return
        
        self.logger.info("Processing Strategy Logic...")
        now = datetime.now()
        warmup_start = self._get_warmup_start_time()
        
        alert_candidates = []  # New alerts to place pending orders
        is_tradable = self.start_time <= now.time() <= self.end_time
        
        # Process each underlying index
        for underlying in self.underlyings:
            spot_symbol = self.spot_symbols.get(underlying, underlying)
            expiry_date = self.expiry_dates.get(underlying, datetime.now().date())
            
            # Get spot price for this underlying
            spot_price = 0
            try:
                spot_df = self.dm.get_spot_candles(spot_symbol, warmup_start, now, refresh=False)
                current_spot_row = self._get_latest_candle(spot_df, now)
                if current_spot_row is not None:
                    spot_price = current_spot_row['close']
            except:
                pass
            
            # Get tracked options for this underlying
            if underlying not in self.tracked_options:
                continue
            
            for symbol in list(self.tracked_options[underlying].keys()):
                try:
                    year = now.year
                    df = self.dm.get_derivative_candles(
                        underlying, symbol, year, warmup_start, now, refresh=True
                    )
                    last_row = self._get_latest_candle(df, now)
                    if last_row is None: continue
                    
                    self.tracked_options[underlying][symbol] = df
                    
                    # Prevent duplicate processing
                    last_processed = self.last_processed_candle_time.get(symbol)
                    current_candle_time = last_row['datetime']
                    
                    if last_processed and current_candle_time <= last_processed:
                        continue
                    
                    self.last_processed_candle_time[symbol] = current_candle_time
                    
                    # Get price history with warmup
                    history_closes = df[df['datetime'] <= current_candle_time]['close']
                    
                    signal = self.strategy.check_signal(symbol, last_row, history_closes, is_tradable=is_tradable)
                    
                    if signal:
                        action = signal.get('action')
                        
                        # Handle NEGATED or EXPIRED - cancel pending entry order
                        if action in ['NEGATED', 'EXPIRED']:
                            self._cancel_pending_entry(symbol, action)
                            continue
                        
                        # Handle ALERT - place pending SL-M BUY order
                        if action == 'ALERT':
                            parts = symbol.split('-')
                            strike = float(parts[3])
                            dist = abs(strike - spot_price)
                            alert_candidates.append({
                                'symbol': symbol,
                                'signal': signal,
                                'dist': dist,
                                'volume': last_row['volume'],
                                'strike': strike,
                                'opt_type': parts[4],
                                'underlying': underlying,
                                'expiry_date': expiry_date
                            })
                        
                        # Handle ENTRY - This should only happen if we have a pending order
                        # If ENTRY comes without pending order, something went wrong
                        elif action == 'ENTRY':
                            if symbol in self.pending_entries:
                                # Pending order should have filled on breakout - check status
                                self.logger.info(f"ENTRY signal for {symbol} - checking pending order status")
                                # This is handled in _monitor_pending_entries
                            else:
                                # ENTRY without pending order - shouldn't happen anymore
                                # Alert should have been consumed if pending order failed
                                self.logger.warning(f"ENTRY signal for {symbol} but no pending order - ignoring")

                except Exception as e:
                    self.logger.error(f"Error processing {symbol}: {e}")
        
        # Place pending entry order for best alert candidate
        if alert_candidates and is_tradable:
            # Check if we already have a pending entry or active trade
            if self.pending_entries:
                self.logger.info(f"Already have {len(self.pending_entries)} pending entry order(s). Skipping new alerts.")
                return
            
            active_trades = self.tracker.get_active_trades()
            if active_trades:
                self.logger.info(f"Already have {len(active_trades)} active trade(s). Skipping new alerts.")
                return
            
            alert_candidates.sort(key=lambda x: (x['dist'], -x['volume']))
            best = alert_candidates[0]
            self.logger.info(f"Best ALERT from {best['underlying']}: {best['symbol']}")
            
            # Send Telegram alert for ALL candidates (ranked), not just the best
            # This lets you manually pick a different strike/CE/PE if you prefer
            for rank, candidate in enumerate(alert_candidates, 1):
                signal = candidate['signal']
                targets = signal.get('targets', [])
                # Add ranking prefix: ⭐ for #1 (auto-selected), numbers for others
                rank_label = f"⭐ #{rank} (AUTO)" if rank == 1 else f"#{rank}"
                self.telegram.alert_setup(
                    symbol=f"{rank_label} {candidate['symbol']}" if rank > 1 else candidate['symbol'],
                    underlying=candidate['underlying'],
                    strike=candidate['strike'],
                    opt_type=candidate['opt_type'],
                    alert_high=signal['price'],
                    alert_low=signal.get('alert_low', signal['sl'] + 1),
                    sl=signal['sl'],
                    t1=targets[0] if len(targets) > 0 else 0,
                    t2=targets[1] if len(targets) > 1 else 0,
                    t3=targets[2] if len(targets) > 2 else 0,
                    rsi=signal.get('rsi', 0),
                    expiry_date=candidate.get('expiry_date'),
                    alert_validity_candles=self.config['strategy'].get('alert_validity', 1)
                )
            
            if len(alert_candidates) > 1:
                self.logger.info(f"📱 Sent {len(alert_candidates)} alert candidates to Telegram")
            
            self._place_pending_entry(best)
    
    def _cancel_pending_entry(self, symbol, reason):
        """Cancel a pending entry order when alert is negated or expired."""
        if symbol not in self.pending_entries:
            return
        
        pending = self.pending_entries[symbol]
        order_id = pending.get('order_id')
        
        if order_id:
            self.logger.info(f"🚫 Canceling pending entry order {order_id} for {symbol} - {reason}")
            try:
                result = self.om.cancel_order(order_id)
                if result:
                    self.logger.info(f"✓ Pending order {order_id} cancelled successfully")
                else:
                    self.logger.warning(f"⚠️ Failed to cancel pending order {order_id}")
            except Exception as e:
                self.logger.error(f"Error canceling pending order: {e}")
        
        # Remove from tracking
        del self.pending_entries[symbol]
        
        # Telegram: notify that setup expired/was negated
        if reason == 'EXPIRED':
            parts = symbol.split('-')
            underlying = parts[1] if len(parts) > 1 else ''
            strike = float(parts[3]) if len(parts) > 3 else 0
            opt_type = parts[4] if len(parts) > 4 else ''
            self.telegram.alert_expired(symbol, underlying, strike, opt_type, pending.get('trigger_price', 0))
    
    def _place_pending_entry(self, candidate):
        """Place a pending SL-M BUY order when an alert is generated."""
        symbol = candidate['symbol']
        signal = candidate['signal']
        underlying = candidate.get('underlying', self.underlyings[0] if self.underlyings else 'NIFTY')
        expiry_date = candidate.get('expiry_date', datetime.now().date())
        
        # Check daily loss limit
        if self._check_daily_loss_limit():
            self.logger.warning("Daily loss limit reached. Pending entry aborted.")
            return
        
        # Get trading symbol from API
        trading_symbol = self.dm.get_trading_symbol(
            underlying, expiry_date, candidate['strike'], candidate['opt_type']
        )
        if not trading_symbol:
            self.logger.error(f"Could not resolve Trading Symbol for {symbol}. Pending entry aborted.")
            # Consume the alert so we don't get orphan ENTRY signals later
            self.strategy.consume_alert(symbol)
            return

        lot_size = self.config['indices'][underlying]['lot_size']
        lots_per_trade = self.config['strategy'].get('lots_per_trade', 1)
        qty = lot_size * lots_per_trade
        trigger_price = self._round_to_tick(signal['price'], underlying)
        cost = trigger_price * qty
        
        # Check available balance
        balance = self.client.get_balance()
        if balance is None or balance < cost:
            self.logger.warning(f"Insufficient Capital: ₹{balance} < ₹{cost}")
            return
        
        self.logger.info(f"📌 PLACING PENDING ENTRY ORDER for {symbol} ({underlying}) at ₹{trigger_price}")
        
        # Place SL-M BUY order (pending until price hits trigger)
        resp = self.om.place_entry_order(symbol, qty, trigger_price, trading_symbol, order_type="SL-M")
        
        if resp and "groww_order_id" in resp:
            order_id = resp["groww_order_id"]
            self.logger.info(f"✅ Pending Entry Order Placed: {order_id} @ ₹{trigger_price}")
            
            # Store pending entry details
            self.pending_entries[symbol] = {
                'order_id': order_id,
                'trigger_price': trigger_price,
                'qty': qty,
                'trading_symbol': trading_symbol,
                'signal': signal,
                'alert_candle': signal.get('alert_candle'),
                'underlying': underlying,
                'expiry_date': expiry_date,
                'strike': candidate['strike'],
                'opt_type': candidate['opt_type'],
                'placed_at': datetime.now()
            }
        else:
            self.logger.error(f"Failed to place pending entry order for {symbol}")
            # Consume the alert so we don't get orphan ENTRY signals later
            self.strategy.consume_alert(symbol)
            self.logger.info(f"Alert consumed for {symbol} due to order failure")

    def _execute_entry(self, candidate):
        """Execute entry order for a candidate signal."""
        symbol = candidate['symbol']
        signal = candidate['signal']
        underlying = candidate.get('underlying', self.underlyings[0] if self.underlyings else 'NIFTY')
        expiry_date = candidate.get('expiry_date', datetime.now().date())
        
        # Check if already have active trade
        active_trades = self.tracker.get_active_trades()
        if active_trades:
            self.logger.info(f"Signal ignored for {symbol}. Already have {len(active_trades)} active trade(s).")
            return
        
        # Check daily loss limit
        if self._check_daily_loss_limit():
            self.logger.warning("Daily loss limit reached. Entry aborted.")
            return
        
        # Get trading symbol from API
        trading_symbol = self.dm.get_trading_symbol(
            underlying, expiry_date, candidate['strike'], candidate['opt_type']
        )
        if not trading_symbol:
            self.logger.error(f"Could not resolve Trading Symbol for {symbol}. Entry Aborted.")
            return

        lot_size = self.config['indices'][underlying]['lot_size']
        lots_per_trade = self.config['strategy'].get('lots_per_trade', 1)
        qty = lot_size * lots_per_trade
        trigger_price = self._round_to_tick(signal['price'], underlying)
        cost = trigger_price * qty
        
        # Check available balance
        balance = self.client.get_balance()
        if balance is None or balance < cost:
            self.logger.warning(f"Insufficient Capital: ₹{balance} < ₹{cost}")
            return
        
        self.logger.info(f"PLACING STOP ORDER for {symbol} ({underlying}) (TS:{trading_symbol}) at ₹{trigger_price}")
        
        # Place order
        resp = self.om.place_entry_order(symbol, qty, trigger_price, trading_symbol, order_type="SL-M")
        
        if resp and "groww_order_id" in resp:
            order_id = resp["groww_order_id"]
            self.logger.info(f"Order {order_id} placed. Polling for fill...")
            
            # Wait for fill confirmation
            fill_price = self.om.check_order_fill(order_id)
            
            if fill_price:
                # ONLY consume alert after successful fill
                self.strategy.consume_alert(symbol)
                
                sl_price = self._round_to_tick(signal['sl'], underlying)
                
                # Place broker-side SL order (persists even if bot crashes)
                sl_order = self.om.place_sl_order(symbol, qty, sl_price, trading_symbol)
                sl_order_id = sl_order['groww_order_id'] if sl_order else None
                
                if sl_order_id:
                    self.logger.info(f"🛡️ Broker SL Order Placed: {sl_order_id} @ ₹{sl_price}")
                else:
                    self.logger.warning(f"⚠️ Failed to place broker SL order - using software SL as fallback")
                
                # Create trade record
                trade_record = {
                    'symbol': symbol,
                    'trading_symbol': trading_symbol,
                    'underlying': underlying,  # Store underlying for later reference
                    'qty': qty,
                    'remaining_qty': qty,
                    'entry_price': fill_price,
                    'entry_time': datetime.now().isoformat(),
                    'sl': sl_price,
                    'sl_order_id': sl_order_id,  # Track broker SL order
                    'targets': [self._round_to_tick(t, underlying) for t in signal['targets']],
                    'order_id': order_id
                }
                
                # Add to tracker
                trade_id = self.tracker.add_active_trade(trade_record)
                trade_record['trade_id'] = trade_id
                
                # Log to CSV for audit
                self.trade_logger.log_entry(trade_record, self.daily_pnl, 0)
                
                # Set up exit orders tracking (for trailing SL and partial exits)
                exit_orders = self.om.place_partial_exits(symbol, trading_symbol, signal, fill_price)
                trade_record['exit_orders'] = exit_orders
                trade_record['alert_range'] = signal.get('alert_range', 0)
                
                # Update tracker with exit orders
                self.tracker.update_trade(trade_id, {
                    'exit_orders': exit_orders,
                    'alert_range': signal.get('alert_range', 0)
                })
                
                self.logger.info(f"✅ Trade Activated: {trade_id} | {underlying} | Fill: ₹{fill_price} | SL Order: {sl_order_id} | Mode: {exit_orders['mode']}")
                
                # Telegram: entry confirmed
                self.telegram.entry_confirmed(
                    symbol=symbol,
                    entry_price=fill_price,
                    sl=sl_price,
                    t1=signal['targets'][0] if len(signal['targets']) > 0 else 0,
                    t2=signal['targets'][1] if len(signal['targets']) > 1 else 0,
                    t3=signal['targets'][2] if len(signal['targets']) > 2 else 0,
                    qty=qty,
                    mode=exit_orders['mode']
                )
            else:
                # Order failed/rejected - DO NOT consume alert
                self.logger.warning(f"Order {order_id} not filled (Rejected/Cancelled). Alert remains active.")
    
    def _activate_trade_from_pending(self, pending, fill_price):
        """Activate a trade after pending entry order is filled.
        
        This handles all the post-fill logic:
        1. Consume the alert
        2. Place SL order
        3. Place Target orders
        4. Create trade record
        5. Log everything
        """
        symbol = pending['trading_symbol'].replace('-', '_') if 'trading_symbol' in pending else pending.get('order_id', '').split('_')[1] if 'order_id' in pending else 'UNKNOWN'
        # Actually use the symbol from pending entries key - we need to pass it
        # Let's extract from order_id for paper trades: PAPER_{symbol}_{timestamp}
        order_id = pending['order_id']
        underlying = pending['underlying']
        signal = pending['signal']
        qty = pending['qty']
        trading_symbol = pending['trading_symbol']
        
        # Consume the alert
        self.strategy.consume_alert(trading_symbol.replace('-', '_'))
        
        # Place SL order — CRITICAL: retry up to 3 times, emergency exit if all fail
        sl_price = self._round_to_tick(signal['sl'], underlying)
        sl_order_id = None
        
        for attempt in range(1, 4):
            sl_order = self.om.place_sl_order(trading_symbol, qty, sl_price, trading_symbol)
            sl_order_id = sl_order.get('groww_order_id') if sl_order else None
            if sl_order_id:
                self.logger.info(f"🛡️ SL Order Placed: {sl_order_id} @ ₹{sl_price}")
                break
            self.logger.warning(f"⚠️ SL order attempt {attempt}/3 failed for {trading_symbol}")
            if attempt < 3:
                import time as _time
                _time.sleep(1)
        
        # CRITICAL: Never hold an unprotected position
        if not sl_order_id and not self.paper_trading:
            self.logger.critical(f"🚨 SL PLACEMENT FAILED after 3 attempts for {trading_symbol}. EMERGENCY EXIT.")
            # Place immediate market exit
            try:
                self.om.place_exit_order(trading_symbol, qty, trading_symbol, "SL_PLACEMENT_FAILED")
                self.logger.critical(f"🚨 Emergency market exit placed for {trading_symbol} ({qty} qty)")
            except Exception as e:
                self.logger.critical(f"🚨 EMERGENCY EXIT ALSO FAILED: {e} — MANUAL INTERVENTION REQUIRED")
            self.telegram.square_off(trading_symbol, fill_price, fill_price, qty, 'SL_PLACEMENT_FAILED')
            return
        
        # Place TARGET orders (limit sell orders at each target)
        target_order_ids = []
        targets = signal.get('targets', [])
        lots_per_trade = self.config['strategy'].get('lots_per_trade', 3)
        exit_mode = self.config['strategy'].get('exit_mode', 'multi_lot')
        
        # For multi-lot mode, calculate qty per target
        if exit_mode == 'multi_lot' and lots_per_trade >= 3:
            lots_for_tp1 = 1
            lots_for_tp2 = 1
            lots_for_tp3 = lots_per_trade - 2
            lot_size = self.config['indices'][underlying]['lot_size']
            qty_per_target = [lots_for_tp1 * lot_size, lots_for_tp2 * lot_size, lots_for_tp3 * lot_size]
        else:
            # Single lot mode - all qty exits at TP2 (not TP3)
            qty_per_target = [0, qty, 0]  # Only TP2 has quantity
        
        for i, target in enumerate(targets):
            target_qty = qty_per_target[i] if i < len(qty_per_target) else 0
            if target_qty > 0:
                target_price = self._round_to_tick(target, underlying)
                target_order = self.om.place_target_order(trading_symbol, target_qty, target_price, trading_symbol)
                if target_order and 'groww_order_id' in target_order:
                    target_order_ids.append(target_order['groww_order_id'])
                    self.logger.info(f"🎯 Target {i+1} Order Placed: {target_order['groww_order_id']} @ ₹{target_price} (qty: {target_qty})")
                else:
                    target_order_ids.append(None)
                    self.logger.warning(f"⚠️ Failed to place Target {i+1} order")
            else:
                target_order_ids.append(None)
        
        # Create trade record
        trade_record = {
            'symbol': trading_symbol,
            'trading_symbol': trading_symbol,
            'underlying': underlying,
            'qty': qty,
            'remaining_qty': qty,
            'entry_price': fill_price,
            'entry_time': datetime.now().isoformat(),
            'sl': sl_price,
            'targets': [self._round_to_tick(t, underlying) for t in targets],
            # Order IDs for tracking
            'entry_order_id': order_id,
            'sl_order_id': sl_order_id,
            'target_order_ids': target_order_ids,
        }
        
        # Add to tracker
        trade_id = self.tracker.add_active_trade(trade_record)
        trade_record['trade_id'] = trade_id
        
        # Log to CSV for audit
        self.trade_logger.log_entry(trade_record, self.daily_pnl, 0)
        
        # Store in active orders for tracking
        self.active_orders[trade_id] = {
            'entry_order_id': order_id,
            'sl_order_id': sl_order_id,
            'target_order_ids': target_order_ids,
            'status': 'ACTIVE'
        }
        
        # Set up exit orders tracking (for trailing SL)
        exit_orders = {
            'mode': exit_mode,
            'current_sl': sl_price,
            'original_sl': sl_price,
            'trail_state': 0,  # 0=no trail, 1=TP1 hit, 2=TP2 hit
            'tp1_price': targets[0] if len(targets) > 0 else fill_price,
            'tp2_price': targets[1] if len(targets) > 1 else fill_price,
            'tp3_price': targets[2] if len(targets) > 2 else fill_price,
        }
        self.tracker.update_trade(trade_id, {
            'exit_orders': exit_orders,
            'alert_range': signal.get('alert_range', 0)
        })
        
        self.logger.info(f"✅ Trade Created: {trade_id} | {underlying} | Entry: ₹{fill_price} | SL: ₹{sl_price} | Targets: {targets}")
        
        # Telegram: entry confirmed
        self.telegram.entry_confirmed(
            symbol=trading_symbol,
            entry_price=fill_price,
            sl=sl_price,
            t1=targets[0] if len(targets) > 0 else 0,
            t2=targets[1] if len(targets) > 1 else 0,
            t3=targets[2] if len(targets) > 2 else 0,
            qty=qty,
            mode=exit_mode
        )
    
    def _monitor_pending_entries(self):
        """Monitor pending entry orders for fills.
        
        When an SL-M BUY order is filled:
        1. Place SL SELL order at alert_low
        2. Place TARGET SELL orders at TP1, TP2, TP3
        3. Create active trade record with all order IDs
        """
        if not self.pending_entries:
            return
        
        for symbol in list(self.pending_entries.keys()):
            pending = self.pending_entries[symbol]
            order_id = pending['order_id']
            
            try:
                # PAPER TRADING: Simulate fill based on LTP
                if self.paper_trading and order_id.startswith('PAPER_'):
                    # Get current LTP for this option
                    ltp = self.client.get_ltp(symbol)
                    trigger_price = pending['trigger_price']
                    
                    if ltp is None:
                        continue
                    
                    # SL-M BUY triggers when price >= trigger
                    if ltp >= trigger_price:
                        self.logger.info(f"🎯 [PAPER] PENDING ENTRY FILLED: {symbol} @ ₹{ltp} (trigger: {trigger_price})")
                        self._activate_trade_from_pending(pending, fill_price=ltp)
                        del self.pending_entries[symbol]
                    continue
                
                # LIVE TRADING: Check actual broker order status
                order_status = self.client.get_order_status(order_id)
                
                if order_status is None:
                    continue
                
                status = order_status.get('status', '').upper()
                
                if status == 'COMPLETE' or status == 'FILLED':
                    # ORDER FILLED - Create active trade
                    fill_price = order_status.get('average_price') or order_status.get('price') or pending['trigger_price']
                    
                    self.logger.info(f"🎯 PENDING ENTRY FILLED: {symbol} @ ₹{fill_price}")
                    self._activate_trade_from_pending(pending, fill_price=fill_price)
                    del self.pending_entries[symbol]
                    
                elif status in ['CANCELLED', 'REJECTED', 'EXPIRED']:
                    self.logger.warning(f"Pending entry order {order_id} {status} for {symbol}")
                    del self.pending_entries[symbol]
                    
            except Exception as e:
                self.logger.error(f"Error monitoring pending entry for {symbol}: {e}")
    
    def _monitor_active_trades(self):
        """Monitor active trades by checking broker order statuses (or LTP for paper trading)."""
        active_trades = self.tracker.get_active_trades()
        
        for trade in active_trades:
            trade_id = trade['trade_id']
            symbol = trade['symbol']
            
            # Skip if we don't have order IDs (legacy/manual trades)
            if 'sl_order_id' not in trade or 'target_order_ids' not in trade:
                continue
            
            sl_order_id = trade.get('sl_order_id')
            target_ids = trade.get('target_order_ids', [])
            exit_orders = trade.get('exit_orders', {})
            trail_state = exit_orders.get('trail_state', 0)
            
            # PAPER TRADING: Use LTP-based simulation
            if self.paper_trading and sl_order_id and sl_order_id.startswith('PAPER_'):
                ltp = self.client.get_ltp(symbol)
                if ltp is None:
                    continue
                
                current_sl = exit_orders.get('current_sl', trade['sl'])
                targets = trade.get('targets', [])
                exit_mode = exit_orders.get('mode', 'single_lot')
                
                # Check SL condition (strategy-defined: alert candle low - 1)
                sl_triggered = ltp <= current_sl
                
                if sl_triggered:
                    exit_price = current_sl
                    exit_reason = "SL_HIT"
                    self.logger.info(f"🔴 [PAPER] SL HIT for {symbol} @ ₹{exit_price}")
                    
                    pnl = (exit_price - float(trade['entry_price'])) * float(trade['remaining_qty'])
                    self.daily_pnl += pnl
                    self.tracker.close_trade(trade_id, exit_price, exit_reason, pnl)
                    self.trade_logger.log_exit(trade, exit_price, exit_reason, self.daily_pnl)
                    continue
                
                # Check TP1 (multi-lot only - trail SL)
                if exit_mode == 'multi_lot' and len(targets) > 0 and trail_state < 1 and ltp >= targets[0]:
                    self.logger.info(f"🎯 [PAPER] TP1 HIT for {symbol} @ ₹{ltp}")
                    self._handle_paper_tp_hit(trade, 1, ltp)
                
                # Check TP2 
                if len(targets) > 1 and ltp >= targets[1]:
                    if exit_mode == 'single_lot':
                        # Single lot mode: TP2 is final exit
                        self.logger.info(f"🎯 [PAPER] TP2 HIT (FINAL) for {symbol} @ ₹{ltp} - Closing Trade")
                        pnl = (ltp - float(trade['entry_price'])) * float(trade['remaining_qty'])
                        self.daily_pnl += pnl
                        self.tracker.close_trade(trade_id, ltp, "TP2_HIT", pnl)
                        self.trade_logger.log_exit(trade, ltp, "TP2_HIT", self.daily_pnl)
                        continue
                    elif trail_state < 2:
                        # Multi-lot mode: TP2 is partial exit + trail
                        self.logger.info(f"🎯 [PAPER] TP2 HIT for {symbol} @ ₹{ltp}")
                        self._handle_paper_tp_hit(trade, 2, ltp)
                
                # Check TP3 (multi-lot only - final exit)
                if exit_mode == 'multi_lot' and len(targets) > 2 and ltp >= targets[2]:
                    self.logger.info(f"🚀 [PAPER] TP3 HIT for {symbol} @ ₹{ltp} - Closing Trade")
                    pnl = (ltp - float(trade['entry_price'])) * float(trade['remaining_qty'])
                    self.daily_pnl += pnl
                    self.tracker.close_trade(trade_id, ltp, "TP3_HIT", pnl)
                    self.trade_logger.log_exit(trade, ltp, "TP3_HIT", self.daily_pnl)
                
                continue
            
            # LIVE TRADING: Check actual broker order statuses
            # 1. Check SL Order Status
            if sl_order_id:
                sl_status = self.client.get_order_status(sl_order_id)
                if sl_status and sl_status.get('status') in ['FILLED', 'COMPLETE']:
                    self.logger.info(f"🔴 SL HIT for {symbol} (Order {sl_order_id})")
                    fill_price = sl_status.get('average_price') or sl_status.get('price')
                    
                    # Cancel all pending target orders
                    for tid in target_ids:
                        if tid:
                            self.om.cancel_order(tid)
                    
                    # Close trade
                    pnl = (float(fill_price) - float(trade['entry_price'])) * float(trade['remaining_qty'])
                    self.daily_pnl += pnl 
                    self.tracker.close_trade(trade_id, fill_price, "SL_HIT", pnl)
                    self.trade_logger.log_exit(trade, fill_price, "SL_HIT", self.daily_pnl)
                    continue

            # 2. Check Target Order Statuses
            exit_mode = exit_orders.get('mode', 'single_lot')
            
            # Check TP1 (multi-lot only)
            if exit_mode == 'multi_lot' and len(target_ids) > 0 and target_ids[0] and trail_state < 1:
                tp1_status = self.client.get_order_status(target_ids[0])
                if tp1_status and tp1_status.get('status') in ['FILLED', 'COMPLETE']:
                    self.logger.info(f"🎯 TP1 HIT for {symbol}")
                    self._handle_tp_hit(trade, 1, tp1_status)

            # Check TP2
            if len(target_ids) > 1 and target_ids[1]:
                tp2_status = self.client.get_order_status(target_ids[1])
                if tp2_status and tp2_status.get('status') in ['FILLED', 'COMPLETE']:
                    if exit_mode == 'single_lot':
                        # Single lot mode: TP2 is final - cancel SL and close trade
                        self.logger.info(f"🎯 TP2 HIT (FINAL) for {symbol} - Closing Trade")
                        fill_price = tp2_status.get('average_price') or tp2_status.get('price')
                        
                        # Cancel SL Order
                        if sl_order_id:
                            self.om.cancel_order(sl_order_id)
                            self.logger.info(f"🛡️ SL Order Cancelled: {sl_order_id}")
                        
                        # Calculate PnL and close trade
                        pnl = (float(fill_price) - float(trade['entry_price'])) * float(trade['remaining_qty'])
                        self.daily_pnl += pnl
                        self.tracker.close_trade(trade_id, fill_price, "TP2_HIT", pnl)
                        self.trade_logger.log_exit(trade, fill_price, "TP2_HIT", self.daily_pnl)
                        continue
                    elif trail_state < 2:
                        # Multi-lot mode: TP2 is partial exit
                        self.logger.info(f"🎯 TP2 HIT for {symbol}")
                        self._handle_tp_hit(trade, 2, tp2_status)

            # Check TP3 (multi-lot only - Final)
            if exit_mode == 'multi_lot' and len(target_ids) > 2 and target_ids[2]:
                tp3_status = self.client.get_order_status(target_ids[2])
                if tp3_status and tp3_status.get('status') in ['FILLED', 'COMPLETE']:
                    self.logger.info(f"🚀 TP3 HIT for {symbol} - Closing Trade")
                    fill_price = tp3_status.get('average_price') or tp3_status.get('price')
                    
                    # Cancel SL Order
                    if sl_order_id:
                        self.om.cancel_order(sl_order_id)
                        self.logger.info(f"🛡️ SL Order Cancelled: {sl_order_id}")
                    
                    # Calculate PnL and close trade
                    pnl = (float(fill_price) - float(trade['entry_price'])) * float(trade['remaining_qty'])
                    self.daily_pnl += pnl
                    self.tracker.close_trade(trade_id, fill_price, "TP3_HIT", pnl) 
                    self.trade_logger.log_exit(trade, fill_price, "TP3_HIT", self.daily_pnl)
                    continue
    
    def _handle_paper_tp_hit(self, trade, tp_level, ltp):
        """Handle paper trading TP hit with LTP-based simulation."""
        trade_id = trade['trade_id']
        exit_orders = trade.get('exit_orders', {})
        targets = trade.get('targets', [])
        underlying = trade.get('underlying', 'NIFTY')
        
        # Update trail state
        exit_orders['trail_state'] = tp_level
        
        # Trail SL — same rule as _handle_tp_hit and _handle_multi_lot_exits
        new_sl = 0
        if tp_level == 1:
            new_sl = trade['entry_price']  # Move to cost
        elif tp_level == 2 and len(targets) > 0:
            new_sl = targets[0]  # Move to TP1
        
        if new_sl > 0:
            new_sl = self._round_to_tick(new_sl, underlying)
            exit_orders['current_sl'] = new_sl
            self.logger.info(f"📈 [PAPER] Trailing SL to ₹{new_sl}")
        
        # CRITICAL FIX: Calculate partial P&L for paper trades too
        lot_size = self.config['indices'][underlying]['lot_size']
        partial_qty = lot_size  # 1 lot per partial exit
        partial_profit = (ltp - float(trade['entry_price'])) * partial_qty
        self.daily_pnl += partial_profit
        trade['partial_pnl'] = trade.get('partial_pnl', 0) + partial_profit
        
        # Update remaining qty
        remaining = trade.get('remaining_qty', trade['qty']) - partial_qty
        trade['remaining_qty'] = remaining
        
        self.tracker.update_trade(trade_id, {
            'exit_orders': exit_orders,
            'remaining_qty': remaining,
            'partial_pnl': trade['partial_pnl']
        })
        
        self.logger.info(f"✅ [PAPER] Partial Exit TP{tp_level}: {partial_qty} units | P&L: ₹{partial_profit:.2f}")
        
        # Telegram: notify
        self.telegram.target_hit(trade['symbol'], tp_level, ltp, float(trade['entry_price']), partial_qty, new_sl if new_sl > 0 else None)

    def _handle_tp_hit(self, trade, tp_level, order_status):
        """Handle logic when a Target is hit (Partial Exit + Trail SL)."""
        trade_id = trade['trade_id']
        exit_orders = trade['exit_orders']
        sl_order_id = trade['sl_order_id']
        
        fill_price = float(order_status.get('average_price') or order_status.get('price'))
        qty_filled = int(order_status.get('quantity') or 0)
        
        # Update trade record
        current_remaining = trade['remaining_qty']
        new_remaining = current_remaining - qty_filled
        self.tracker.update_trade(trade_id, {'remaining_qty': new_remaining})
        
        # CRITICAL FIX: Calculate and add partial profit to daily P&L
        # Without this, daily loss limit check uses stale numbers all day
        partial_profit = (fill_price - float(trade['entry_price'])) * qty_filled
        self.daily_pnl += partial_profit
        trade['partial_pnl'] = trade.get('partial_pnl', 0) + partial_profit
        self.tracker.update_trade(trade_id, {
            'partial_pnl': trade['partial_pnl']
        })
        
        self.logger.info(f"Partial Exit TP{tp_level}: Exited {qty_filled} @ ₹{fill_price} | Partial P&L: ₹{partial_profit:.2f} | Remaining {new_remaining}")
        
        # Log partial exit
        self.trade_logger.log_partial_exit(trade, fill_price, qty_filled, f"TP{tp_level}", self.daily_pnl)
        
        # TRAIL SL — use cost-to-cost (entry_price) at TP1, TP1 price at TP2
        # This matches the conservative trailing approach
        new_sl_price = 0
        if tp_level == 1:
            # Move SL to Cost (entry price)
            new_sl_price = trade['entry_price']
            exit_orders['trail_state'] = 1
        elif tp_level == 2:
            # Move SL to TP1
            exit_orders['trail_state'] = 2
            targets = trade.get('targets', [])
            if len(targets) > 0:
                new_sl_price = targets[0]
        
        if new_sl_price > 0 and sl_order_id:
             # round to tick
             new_sl_price = self._round_to_tick(new_sl_price, trade.get('underlying', 'NIFTY'))
             
             # Modify Broker SL Order
             self.logger.info(f"Trailing SL to {new_sl_price} with Qty {new_remaining}")
             self.om.modify_sl_order(sl_order_id, new_sl_price, new_qty=new_remaining)
             
             # Update internal state
             exit_orders['current_sl'] = new_sl_price
             self.tracker.update_trade(trade_id, {'exit_orders': exit_orders})
        
        # Telegram: notify target hit
        self.telegram.target_hit(
            symbol=trade['symbol'],
            tp_num=tp_level,
            price=fill_price,
            entry_price=float(trade['entry_price']),
            qty_exited=qty_filled,
            new_sl=new_sl_price if new_sl_price > 0 else None
        )

    def _monitor_legacy_trade(self, trade, ltp):
        """Monitor trades without exit_orders (legacy format)."""
        symbol = trade['symbol']
        trading_symbol = trade['trading_symbol']
        trade_id = trade['trade_id']
        
        exit_triggered = False
        reason = None
        exit_price = ltp
        
        # Check SL condition (strategy-defined: alert candle low - 1)
        sl_triggered = ltp <= trade['sl']
        
        if sl_triggered:
            reason = 'SL'
            exit_price = trade['sl']
            exit_triggered = True
            self.logger.info(f"🔴 SL HIT for {trade_id} at ₹{exit_price}")
        
        # Check Target (only if no exit triggered)
        if not exit_triggered and ltp >= trade['targets'][1]:  # Using T2 as main target
            reason = 'TARGET'
            exit_price = ltp
            exit_triggered = True
            self.logger.info(f"🟢 TARGET HIT for {trade_id} at ₹{ltp}")
        
        if exit_triggered:
            self._close_entire_position(trade, exit_price, reason)

    def _handle_multi_lot_exits(self, trade, ltp, exit_orders, targets, trail_state, alert_range):
        """Handle multi-lot mode: partial exits + trailing SL.
        
        Trailing SL rule (matches _handle_tp_hit for live mode):
        - TP1: Trail SL to entry_price (cost-to-cost)
        - TP2: Trail SL to targets[0] (TP1 price)
        """
        trade_id = trade['trade_id']
        symbol = trade['symbol']
        trading_symbol = trade['trading_symbol']
        sl_order_id = trade.get('sl_order_id')
        entry_price = float(trade['entry_price'])
        
        # Check TP1 hit (not yet trailed)
        if ltp >= targets[0] and trail_state == 0:
            self.logger.info(f"🎯 TP1 HIT for {trade_id} at ₹{ltp}")
            
            # Execute partial exit (1 lot)
            exit_order = exit_orders['orders'][0]
            qty = exit_order['quantity']
            
            self.logger.info(f"Exiting {qty} lots at TP1...")
            self.om.execute_partial_exit(symbol, trading_symbol, qty, "TP1")
            exit_order['status'] = 'executed'
            
            # CRITICAL FIX: Trail SL to entry_price (cost-to-cost) — matches _handle_tp_hit
            new_sl = self._round_to_tick(entry_price, trade.get('underlying', 'NIFTY'))
            exit_orders['current_sl'] = new_sl
            exit_orders['trail_state'] = 1
            
            # Calculate remaining qty and partial P&L
            remaining_qty = trade.get('remaining_qty', trade['qty']) - qty
            trade['remaining_qty'] = remaining_qty
            partial_profit = (ltp - entry_price) * qty
            self.daily_pnl += partial_profit
            trade['partial_pnl'] = trade.get('partial_pnl', 0) + partial_profit
            
            # Modify broker SL order with new trigger and qty
            if sl_order_id:
                self.om.modify_sl_order(sl_order_id, new_sl, remaining_qty)
                self.logger.info(f"🛡️ Broker SL Modified: {sl_order_id} → ₹{new_sl} | Qty: {remaining_qty}")
            
            self.logger.info(f"✅ Partial Exit TP1: {qty} units | P&L: ₹{partial_profit:.2f} | SL trailed to ₹{new_sl}")
            
            # Telegram: notify
            self.telegram.target_hit(symbol, 1, ltp, entry_price, qty, new_sl)
        
        # Check TP2 hit
        elif ltp >= targets[1] and trail_state == 1:
            self.logger.info(f"🎯 TP2 HIT for {trade_id} at ₹{ltp}")
            
            # Execute partial exit (1 lot)
            exit_order = exit_orders['orders'][1]
            qty = exit_order['quantity']
            
            self.logger.info(f"Exiting {qty} lots at TP2...")
            self.om.execute_partial_exit(symbol, trading_symbol, qty, "TP2")
            exit_order['status'] = 'executed'
            
            # CRITICAL FIX: Trail SL to TP1 price — matches _handle_tp_hit
            new_sl = self._round_to_tick(targets[0], trade.get('underlying', 'NIFTY'))
            exit_orders['current_sl'] = new_sl
            exit_orders['trail_state'] = 2
            
            # Calculate remaining qty and partial P&L
            remaining_qty = trade.get('remaining_qty', trade['qty']) - qty
            trade['remaining_qty'] = remaining_qty
            partial_profit = (ltp - entry_price) * qty
            self.daily_pnl += partial_profit
            trade['partial_pnl'] = trade.get('partial_pnl', 0) + partial_profit
            
            # Modify broker SL order with new trigger and qty
            if sl_order_id:
                self.om.modify_sl_order(sl_order_id, new_sl, remaining_qty)
                self.logger.info(f"🛡️ Broker SL Modified: {sl_order_id} → ₹{new_sl} | Qty: {remaining_qty}")
            
            self.logger.info(f"✅ Partial Exit TP2: {qty} units | P&L: ₹{partial_profit:.2f} | SL trailed to ₹{new_sl}")
            
            # Telegram: notify
            self.telegram.target_hit(symbol, 2, ltp, entry_price, qty, new_sl)
        
        # Check TP3 hit (final exit)
        elif ltp >= targets[2] and trail_state == 2:
            self.logger.info(f"🎯 TP3 HIT for {trade_id} at ₹{ltp}")
            
            # Close remaining position
            self._close_entire_position(trade, ltp, 'TP3')

    def _handle_single_lot_exits(self, trade, ltp, exit_orders, targets, trail_state, alert_range):
        """Handle single-lot mode: exit fully at configured target (default: TP2, matching backtest)."""
        trade_id = trade['trade_id']
        sl_order_id = trade.get('sl_order_id')
        
        # BUG-003 FIX: Config-driven single-lot exit target (default: T2)
        target_idx = self.config['strategy'].get('single_lot_exit_target', 2) - 1
        
        # Check TP1 hit (trail SL, don't exit)
        if ltp >= targets[0] and trail_state == 0:
            self.logger.info(f"🎯 TP1 reached for {trade_id} at ₹{ltp}")
            
            # Trail SL (no exit)
            new_sl = exit_orders['current_sl'] + alert_range
            exit_orders['current_sl'] = new_sl
            exit_orders['trail_state'] = 1
            
            # Modify broker SL order with new trigger
            if sl_order_id:
                self.om.modify_sl_order(sl_order_id, new_sl)
                self.logger.info(f"🛡️ Broker SL Modified: {sl_order_id} → ₹{new_sl}")
            
            self.logger.info(f"✅ SL trailed to ₹{new_sl} (no exit)")
        
        # Check configured target hit (FINAL EXIT for single-lot mode)
        elif ltp >= targets[target_idx] and trail_state >= 1:
            self.logger.info(f"🎯 TP{target_idx+1} HIT (FINAL) for {trade_id} at ₹{ltp}")
            
            # Close entire position
            self._close_entire_position(trade, ltp, f'TP{target_idx+1}')

    def _close_entire_position(self, trade, ltp, reason):
        """Close entire position and update tracker."""
        symbol = trade['symbol']
        trading_symbol = trade['trading_symbol']
        trade_id = trade['trade_id']
        remaining_qty = trade.get('remaining_qty', trade['qty'])
        sl_order_id = trade.get('sl_order_id')
        
        # Cancel broker SL order (no longer needed, we're exiting)
        if sl_order_id:
            self.om.cancel_sl_order(sl_order_id)
            self.logger.info(f"🛡️ Broker SL Cancelled: {sl_order_id} (position closing)")
            
        # Cancel pending target orders
        target_ids = trade.get('target_order_ids', [])
        for tid in target_ids:
            if tid:
                self.om.cancel_order(tid)
                self.logger.info(f"🚫 Target Order Cancelled: {tid}")
        
        # Place exit order for remaining quantity
        self.om.place_exit_order(symbol, remaining_qty, trading_symbol, reason)
        
        # Calculate P&L (using remaining qty + any partial pnl already booked)
        partial_pnl = trade.get('partial_pnl', 0)
        final_pnl = (ltp - trade['entry_price']) * remaining_qty
        total_pnl = final_pnl + partial_pnl
        self.daily_pnl += final_pnl  # Only add final exit pnl, partials already added
        
        # Update trade record with exit info
        trade['exit_price'] = ltp
        trade['exit_time'] = datetime.now().isoformat()
        trade['reason'] = reason
        trade['pnl'] = total_pnl
        
        # Log to CSV for audit
        self.trade_logger.log_exit(trade, self.daily_pnl, 0)
        
        # Close trade in tracker
        self.tracker.close_trade(trade_id, ltp, reason, total_pnl)
        
        self.logger.info(f"Trade closed: {trade_id} | P&L: ₹{total_pnl:.2f} | Daily P&L: ₹{self.daily_pnl:.2f}")
        
        # Telegram: notify based on exit reason
        entry_price = float(trade['entry_price'])
        if 'SL' in reason:
            self.telegram.sl_hit(symbol, ltp, entry_price, remaining_qty, self.daily_pnl)
        elif 'TP' in reason:
            tp_num = int(reason.replace('TP', '').replace('_HIT', '')) if reason.replace('TP', '').replace('_HIT', '').isdigit() else 0
            new_sl = exit_orders.get('current_sl') if 'exit_orders' in trade else None
            self.telegram.target_hit(symbol, tp_num, ltp, entry_price, remaining_qty, new_sl)
        elif 'SQ_OFF' in reason or 'DAILY_LOSS' in reason:
            self.telegram.square_off(symbol, ltp, entry_price, remaining_qty, reason)

    def run(self):
        """Main trading loop."""
        self.logger.info("=" * 60)
        self.logger.info(" STARTING LIVE TRADER")
        self.logger.info("=" * 60)
        
        # Initialize day
        if not self._initialize_day():
            return
        
        # Initial option universe update
        self._update_option_universe()
        
        # Heartbeat counter
        last_heartbeat = datetime.now()
        heartbeat_interval = 60  # Show status every 60 seconds
        
        # Main loop
        while True:
            try:
                now = datetime.now()
                
                # Heartbeat - show status periodically so user knows bot is alive
                if (now - last_heartbeat).total_seconds() >= heartbeat_interval:
                    active_count = len(self.tracker.get_active_trades())
                    mode = "PAPER" if self.paper_trading else "LIVE"
                    indices_str = ", ".join(self.underlyings) if self.underlyings else "None"
                    next_candle = (now.minute // 15 + 1) * 15
                    next_candle_time = now.replace(minute=next_candle % 60, second=0, microsecond=0)
                    if next_candle >= 60:
                        next_candle_time = next_candle_time.replace(hour=now.hour + 1, minute=0)
                    
                    self.logger.info(
                        f"[HEARTBEAT] {mode} | Indices: {indices_str} | Time: {now.strftime('%H:%M:%S')} | "
                        f"Daily P&L: Rs.{self.daily_pnl:.2f} | Active Trades: {active_count} | "
                        f"Next Candle: {next_candle_time.strftime('%H:%M')}"
                    )
                    last_heartbeat = now
                
                # Auto square-off time
                if now.time() >= self.sq_off_time:
                    self.logger.info("=" * 60)
                    self.logger.info("🔔 AUTO SQUARE OFF TIME REACHED")
                    self.logger.info("=" * 60)
                    
                    # Cancel any pending entry orders first
                    if self.pending_entries:
                        self.logger.info(f"Canceling {len(self.pending_entries)} pending entry orders...")
                        for symbol, pending in list(self.pending_entries.items()):
                            order_id = pending.get('order_id')
                            if order_id:
                                self.om.cancel_order(order_id)
                                self.logger.info(f"Cancelled pending entry: {symbol}")
                        self.pending_entries.clear()
                    
                    # Square off active trades
                    active_trades = self.tracker.get_active_trades()
                    for trade in active_trades:
                        self.logger.info(f"Squaring off: {trade['trade_id']}")
                        
                        # Cancel broker SL order first
                        sl_order_id = trade.get('sl_order_id')
                        if sl_order_id:
                            self.om.cancel_order(sl_order_id)
                            self.logger.info(f"Cancelled SL order: {sl_order_id}")
                        
                        # Cancel any target orders
                        for tid in trade.get('target_order_ids', []):
                            if tid:
                                self.om.cancel_order(tid)
                        
                        # Place exit order
                        self.om.place_exit_order(
                            trade['symbol'],
                            trade.get('remaining_qty', trade['qty']),
                            trade['trading_symbol'],
                            "SQ_OFF"
                        )
                        
                        # Get LTP for final P&L
                        ltp = self.client.get_ltp(trade['symbol']) or trade['entry_price']
                        pnl = (ltp - trade['entry_price']) * trade.get('remaining_qty', trade['qty'])
                        pnl += trade.get('partial_pnl', 0)  # Add any partial profits
                        self.daily_pnl += pnl
                        self.tracker.close_trade(trade['trade_id'], ltp, "SQ_OFF", pnl)
                        self.trade_logger.log_exit(trade, ltp, "SQ_OFF", self.daily_pnl)
                    
                    self.logger.info(f"✅ End of day. Daily P&L: ₹{self.daily_pnl:.2f}")
                    break
                
                # Check daily loss limit
                if self._check_daily_loss_limit():
                    self.logger.critical("Daily loss limit reached. Stopping trading.")
                    self.telegram.daily_loss_limit_hit(self.daily_pnl, self.max_loss_per_day)
                    # Square off remaining positions
                    active_trades = self.tracker.get_active_trades()
                    for trade in active_trades:
                        self.om.place_exit_order(
                            trade['symbol'],
                            trade['qty'],
                            trade['trading_symbol'],
                            "DAILY_LOSS_LIMIT"
                        )
                        ltp = self.client.get_ltp(trade['symbol']) or trade['entry_price']
                        pnl = (ltp - trade['entry_price']) * trade['qty']
                        self.daily_pnl += pnl
                        self.tracker.close_trade(trade['trade_id'], ltp, "DAILY_LOSS_LIMIT", pnl)
                    break
                
                # Wait for market open
                if now.time() < self.start_time:
                    if (now - last_heartbeat).total_seconds() >= heartbeat_interval:
                        self.logger.info(f"[WAITING] Market not yet open. Trading starts at {self.start_time}")
                        last_heartbeat = now
                    time.sleep(60)
                    continue
                
                # Process on candle close
                if self._poll_candle_close():
                    self._update_option_universe()
                    self._process_strategy_logic()
                
                # Monitor pending entries for fills
                self._monitor_pending_entries()
                
                # Monitor active trades
                self._monitor_active_trades()
                
                # Sleep briefly
                time.sleep(1)
            
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}", exc_info=True)
                time.sleep(5)  # Brief pause before retrying
        
        self.logger.info("=" * 60)
        self.logger.info(f" TRADING SESSION ENDED | Daily P&L: ₹{self.daily_pnl:.2f}")
        self.logger.info("=" * 60)
        
        # Telegram: daily summary
        closed_trades = self.tracker.get_closed_trades_today() if hasattr(self.tracker, 'get_closed_trades_today') else []
        total = len(closed_trades)
        wins = sum(1 for t in closed_trades if float(t.get('pnl', 0)) > 0)
        losses = total - wins
        best = max((float(t.get('pnl', 0)) for t in closed_trades), default=None) if closed_trades else None
        worst = min((float(t.get('pnl', 0)) for t in closed_trades), default=None) if closed_trades else None
        self.telegram.daily_summary(total, wins, losses, self.daily_pnl, best, worst)
