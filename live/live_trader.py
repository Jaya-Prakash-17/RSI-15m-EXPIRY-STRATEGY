# live/live_trader.py
import logging
import time
import sys
import math
import pandas as pd
from datetime import datetime, timedelta, time as datetime_time
import pytz
from data.data_manager import DataManager
from execution.order_manager import OrderManager, is_order_filled
from execution.trade_tracker import TradeTracker
from strategy.expiry_rsi_breakout import ExpiryRSIBreakout
from core.groww_client import GrowwClient
from utils.trade_logger import TradeLogger, BacktestTradeLogger
from utils.telegram_notifier import TelegramNotifier
from utils.expiry_calendar import get_expiry_for_date

IST = pytz.timezone('Asia/Kolkata')
MARKET_OPEN_IST = datetime_time(9, 15)    # 9:15 AM IST
MARKET_CLOSE_IST = datetime_time(15, 30)  # 3:30 PM IST

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
        self.max_loss_limit = config['risk'].get('max_loss_per_day', 5000)
        
        # Strategy filters
        self.enable_direction_filter = config['strategy'].get('direction_filter_enabled', False)
        self.trade_only_on_expiry = config['strategy'].get('trade_only_on_expiry', False)
        self.max_loss_per_day = config['risk']['max_loss_per_day']
        
        # Trading window
        self.start_time = datetime.strptime(config['trading']['window']['start'], "%H:%M").time()
        self.end_time = datetime.strptime(config['trading']['window']['end'], "%H:%M").time()
        self.sq_off_time = datetime.strptime(config['trading']['window']['auto_square_off'], "%H:%M").time()
        
        # Configuration
        self.trade_only_on_expiry = config['strategy'].get('trade_only_on_expiry', True)

    def _get_tradeable_indices(self):
        """
        Get all indices that should be traded today.
        Uses expiry_calendar for accurate expiry detection — handles
        all historical day changes for NIFTY, BANKNIFTY, SENSEX.
        """
        from utils.expiry_calendar import is_expiry_day
        from datetime import datetime

        today = datetime.now().date()
        today_str = today.strftime("%Y-%m-%d")

        tradeable = []

        if not self.trade_only_on_expiry:
            indices = list(self.config['indices'].keys())
            self.logger.info(f"trade_only_on_expiry=False, trading ALL indices: {indices}")
            return indices

        for idx in self.config['indices'].keys():
            # Fast local check first (no API call)
            if not is_expiry_day(idx, today):
                self.logger.debug(f"{idx}: not an expiry day today ({today})")
                continue

            # Confirm with Groww API (verifies holiday adjustments and
            # catches any future rule changes we haven't coded yet)
            try:
                expiries = self.dm.get_expiries(idx)
                if today_str in expiries:
                    self.logger.info(f"✅ Confirmed API expiry for {idx} today ({today})")
                    tradeable.append(idx)
                else:
                    self.logger.warning(
                        f"⚠️  expiry_calendar says {idx} expires today "
                        f"but API disagrees. API expiries: {expiries[:5]}. "
                        f"Skipping {idx} to be safe."
                    )
            except Exception as e:
                # API failure: trust local calendar (don't skip trading day)
                self.logger.warning(
                    f"API expiry check failed for {idx}: {e}. "
                    f"Trusting local expiry_calendar."
                )
                tradeable.append(idx)

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
        
        today = datetime.now().date()
        for underlying in self.underlyings:
            try:
                expiry = get_expiry_for_date(underlying, today)
                self.expiry_dates[underlying] = expiry
                self.logger.info(
                    f"Expiry for {underlying}: {expiry} "
                    f"({'TODAY' if expiry == today else f'ADJUSTED from {today}'})"
                )
            except Exception as e:
                self.logger.warning(f"Failed to get expiry for {underlying}: {e}. Falling back to today.")
                self.expiry_dates[underlying] = today
                
            # Cross-check calendar expiry with Groww API (advisory)
            if self.trade_only_on_expiry:
                try:
                    from data.groww_data_manager import GrowwDataManager
                    dm = GrowwDataManager() # or use self.dm if it has get_expiries
                    api_expiries = self.client.get_expiries(underlying) if hasattr(self.client, 'get_expiries') else []
                    today_str = datetime.now().strftime("%Y-%m-%d")
                    if api_expiries and today_str not in api_expiries:
                        self.logger.warning(
                            f"\u26a0\ufe0f CALENDAR CHECK: {underlying} calendar says expiry today, "
                            f"but Groww API disagrees. API expiries: {api_expiries[:3]}"
                        )
                        self.telegram._send(
                            f"\u26a0\ufe0f <b>Expiry Calendar Mismatch</b>\n"
                            f"{underlying}: Calendar expects expiry today, but Groww API disagrees.\n"
                            f"Verify before trading. Check: utils/expiry_calendar.py"
                        )
                    else:
                        self.logger.info(f"\u2705 Calendar verified with Groww API for {underlying}")
                except Exception as e:
                    self.logger.warning(f"Could not verify {underlying} expiry with API: {e}")

            self.spot_symbols[underlying] = underlying
            self.tracked_options[underlying] = {}  # Nested dict: {underlying: {symbol: df}}
        
        # Reconcile positions on startup
        self._reconcile_positions()
        
        # Reset daily P&L
        self.daily_pnl = self.tracker.get_daily_pnl()
        self.logger.info(f"Daily P&L at startup: ₹{self.daily_pnl:.2f}")
        
        return True

    def _reconcile_positions(self):
        """Reconcile bot trades with broker positions on startup.
        Also recovers any pending entries that were in-flight during a crash.
        """
        self.logger.info("Reconciling positions with broker...")
        
        try:
            # Verify tracked active trades
            active_trades = self.tracker.get_active_trades()
            
            if active_trades:
                self.logger.warning(f"Found {len(active_trades)} active trades from previous session:")
                for trade in active_trades:
                    self.logger.warning(f"  - {trade['symbol']} | Qty: {trade.get('remaining_qty', trade['qty'])} | Entry: {trade['entry_price']}")
                self.logger.warning("⚠️  These positions will be managed by the bot")
            else:
                self.logger.info("No active bot trades found. Starting fresh.")
            
            # MEDIUM FIX #3: Recover pending entries from crash
            saved_pending = self.tracker.load_pending_entries()
            if saved_pending:
                self.logger.warning(f"Found {len(saved_pending)} pending entries from previous session")
                for symbol, pending in saved_pending.items():
                    order_id = pending.get('order_id', '')
                    
                    # Paper trades: just cancel (can't check status)
                    if order_id.startswith('PAPER_'):
                        self.logger.info(f"Discarding stale paper pending entry: {symbol}")
                        continue
                    
                    try:
                        status = self.client.get_order_status(order_id)
                        if not status:
                            self.logger.warning(f"Could not check order {order_id} for {symbol}")
                            continue
                        
                        s = status.get('status', '').upper()
                        
                        if is_order_filled(s):
                            # Order filled while bot was offline — activate trade
                            fill_price = status.get('fill_price') or pending.get('trigger_price')
                            self.logger.critical(
                                f"🚨 [RECONCILE] {symbol} order {order_id} filled while bot was "
                                f"offline @ \u20b9{fill_price}. Activating trade now."
                            )
                            self._activate_trade_from_pending(pending, fill_price=float(fill_price))
                        
                        elif s in ('OPEN', 'PENDING', 'TRIGGER_PENDING', 'NOT_FILLED'):
                            # Order still live at broker — resume monitoring (do NOT cancel)
                            self.logger.info(
                                f"[RECONCILE] {symbol} order {order_id} still {s} at broker. "
                                f"Resuming monitoring."
                            )
                            self.pending_entries[symbol] = pending  # add back to live monitoring
                        
                        elif s in ('CANCELLED', 'REJECTED', 'EXPIRED'):
                            self.logger.warning(
                                f"[RECONCILE] {symbol} order {order_id} was {s}. "
                                f"Removing from pending \u2014 no position opened."
                            )
                        
                        else:
                            self.logger.warning(f"[RECONCILE] {symbol} unknown status: {s}. Skipping.")
                    
                    except Exception as e:
                        self.logger.error(f"Error reconciling pending entry {order_id} for {symbol}: {e}")
            
            # Clear pending entries file after reconciliation is complete
            self.tracker.clear_pending_entries()
        
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

    def _get_unrealized_pnl(self) -> float:
        """
        Calculates the total unrealized P&L of all currently open trades.
        Uses current LTP from broker. Returns 0.0 if no open trades or LTP unavailable.
        """
        total_unrealized = 0.0
        active_trades = self.tracker.get_active_trades()
        for trade in active_trades:
            ltp = self.client.get_ltp(trade.get('symbol', ''))
            if ltp and ltp > 0:
                remaining_qty = trade.get('remaining_qty', trade.get('qty', 0))
                entry_price = float(trade.get('entry_price', 0))
                unrealized = (ltp - entry_price) * remaining_qty
                total_unrealized += unrealized
        return total_unrealized

    def _check_daily_loss_limit(self):
        """
        Check if daily loss limit is breached.
        Checks both realized P&L AND unrealized (mark-to-market) P&L.
        """
        realized = self.daily_pnl
        unrealized = self._get_unrealized_pnl()
        total_exposure = realized + unrealized
        
        if total_exposure <= -self.max_loss_per_day:
            self.logger.critical(
                f"🛑 DAILY LOSS LIMIT HIT: "
                f"Realized=\u20b9{realized:.0f} + Unrealized=\u20b9{unrealized:.0f} = "
                f"\u20b9{total_exposure:.0f} (limit: -\u20b9{self.max_loss_per_day})"
            )
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
                    
                    # MEDIUM FIX: Verify option candle has advanced past spot candle detection
                    # Option candles from API can lag spot by 1-3 minutes.
                    # If option candle time < spot candle time, we'd run RSI on stale data.
                    if self.last_candle_time and current_candle_time < self.last_candle_time:
                        self.logger.debug(f"Skipping {symbol}: option candle ({current_candle_time}) behind spot ({self.last_candle_time})")
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
                            # --- Direction Confirmation ---
                            if self.enable_direction_filter:
                                try:
                                    if len(spot_df) >= 2:
                                        prev_spot = spot_df.iloc[-2]['close']
                                        curr_spot = spot_df.iloc[-1]['close']
                                        opt_type = symbol.split('-')[4]
                                        
                                        if opt_type == 'CE' and curr_spot < prev_spot:
                                            self.logger.info(f"[{symbol}] IGNORED: CE alert on BEARISH spot ({curr_spot} < {prev_spot})")
                                            continue
                                        if opt_type == 'PE' and curr_spot > prev_spot:
                                            self.logger.info(f"[{symbol}] IGNORED: PE alert on BULLISH spot ({curr_spot} > {prev_spot})")
                                            continue
                                except Exception as e:
                                    self.logger.warning(f"Direction filter error for {symbol}: {e}")

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
        
        # Place pending entry order for best alert candidate(s)
        if alert_candidates and is_tradable:
            # Group candidates by underlying
            by_index = {}
            for candidate in alert_candidates:
                idx = candidate['underlying']
                if idx not in by_index:
                    by_index[idx] = []
                by_index[idx].append(candidate)
            
            for index_name, candidates in by_index.items():
                existing_active = self.tracker.get_active_trades_for_index(index_name)
                existing_pending = self.tracker.get_pending_for_index(self.pending_entries, index_name)
                
                if existing_active:
                    self.logger.info(f"[{index_name}] Signal ignored for {candidates[0]['symbol']}. Already have trade for this index.")
                    continue
                if existing_pending:
                    self.logger.info(f"[{index_name}] Already have pending entry. Skipping new alerts.")
                    continue
                
                # Select best candidate for this index
                candidates.sort(key=lambda x: (x['dist'], -x['volume']))
                best = candidates[0]
                self.logger.info(f"[{index_name}] Best ALERT: {best['symbol']}")
                
                # Send Telegram alert for this index's best candidate
                signal = best['signal']
                targets = signal.get('targets', [])
                self.telegram.alert_setup(
                    symbol=best['symbol'],
                    underlying=best['underlying'],
                    strike=best['strike'],
                    opt_type=best['opt_type'],
                    alert_high=signal['price'],
                    alert_low=signal.get('alert_low', signal['sl'] + 1),
                    sl=signal['sl'],
                    t1=targets[0] if len(targets) > 0 else 0,
                    t2=targets[1] if len(targets) > 1 else 0,
                    t3=targets[2] if len(targets) > 2 else 0,
                    rsi=signal.get('rsi', 0),
                    expiry_date=best.get('expiry_date'),
                    alert_validity_candles=self.config['strategy'].get('alert_validity', 1)
                )
                
                # Log other candidates for this index (if any)
                if len(candidates) > 1:
                    others = [c['symbol'] for c in candidates[1:]]
                    self.logger.info(f"[{index_name}] Other candidates for index (not selected): {others}")
                
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
                'original_symbol': symbol,
                'signal': signal,
                'alert_candle': signal.get('alert_candle'),
                'underlying': underlying,
                'expiry_date': expiry_date,
                'strike': candidate['strike'],
                'opt_type': candidate['opt_type'],
                'placed_at': datetime.now()
            }
            # Persist to disk for crash recovery
            self.tracker.save_pending_entries(self.pending_entries)
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
        
        # Check if already have active trade for this index
        active_trades_for_index = self.tracker.get_active_trades_for_index(underlying)
        if active_trades_for_index:
            self.logger.info(f"[{underlying}] Signal ignored for {symbol}. Already have trade for this index.")
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
        
        Includes a GAP-FILL guard to protect against excessive slippage on open.
        """
        order_id = pending['order_id']
        underlying = pending['underlying']
        signal = pending['signal']
        qty = pending['qty']
        trading_symbol = pending['trading_symbol']
        original_symbol = pending.get('original_symbol', trading_symbol)
        trigger_price = float(pending['trigger_price'])
        fill_price = float(fill_price)
        
        # ─── GAP-FILL GUARD ────────────────────────────────────────────────
        gap_pct = (fill_price - trigger_price) / trigger_price if trigger_price > 0 else 0
        ABORT_THRESHOLD = self.config['strategy'].get('gap_abort_pct', 0.04)
        RECALC_THRESHOLD = self.config['strategy'].get('gap_recalc_pct', 0.02)
        
        if gap_pct > ABORT_THRESHOLD:
            # Gap too large — R:R is completely broken, exit immediately
            self.logger.warning(
                f"🚫 GAP-FILL ABORT: {original_symbol} | "
                f"Trigger=\u20b9{trigger_price} Fill=\u20b9{fill_price} Gap={gap_pct*100:.1f}% "
                f"(>{ABORT_THRESHOLD*100:.0f}% threshold). Exiting immediately."
            )
            self.om.place_exit_order(trading_symbol, qty, trading_symbol, "GAP_FILL_ABORT")
            self.strategy.consume_alert(original_symbol)
            self.telegram._send(
                f"🚫 <b>Gap Fill Abort</b>\n"
                f"Symbol: <code>{original_symbol}</code>\n"
                f"Trigger: \u20b9{trigger_price} | Fill: \u20b9{fill_price} | Gap: {gap_pct*100:.1f}%\n"
                f"R:R too degraded — position closed immediately."
            )
            return  # Do NOT create any trade record
        
        elif gap_pct > RECALC_THRESHOLD:
            # Moderate gap — recalculate SL and targets from actual fill price
            alert_range = signal.get('alert_range', fill_price - float(signal.get('sl', fill_price - 15)))
            new_sl = round(fill_price - alert_range, 2)
            new_targets = [
                round(fill_price + alert_range, 2),
                round(fill_price + 2 * alert_range, 2),
                round(fill_price + 3 * alert_range, 2),
            ]
            # Create a modified copy of signal — do NOT mutate the original
            signal = {
                **signal,
                'sl': new_sl,
                'targets': new_targets,
            }
            self.logger.warning(
                f"⚠️ GAP-FILL RECALC: {original_symbol} | "
                f"Trigger=\u20b9{trigger_price} Fill=\u20b9{fill_price} Gap={gap_pct*100:.1f}%. "
                f"New SL=\u20b9{new_sl}, T1=\u20b9{new_targets[0]}"
            )
            self.telegram._send(
                f"⚠️ <b>Gap Fill — SL/Targets Recalculated</b>\n"
                f"Symbol: <code>{original_symbol}</code>\n"
                f"Fill: \u20b9{fill_price} (trigger \u20b9{trigger_price})\n"
                f"New SL: \u20b9{new_sl} | T1: \u20b9{new_targets[0]}"
            )
        # ─── END GAP-FILL GUARD ────────────────────────────────────────────
        
        targets = [self._round_to_tick(t, underlying) for t in signal.get('targets', [])]
        
        # Consume the alert
        self.strategy.consume_alert(original_symbol)
        
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
        # We delegate this entirely to om.place_partial_exits to avoid duplication
        # and ensure percentage/lot rules from config are strictly followed.
        exit_orders = self.om.place_partial_exits(original_symbol, trading_symbol, signal, fill_price)
        
        target_order_ids = [None, None, None]
        for order in exit_orders['orders']:
            # map order ids to their respective index (0 for TP1, 1 for TP2, 2 for TP3)
            idx = int(order['target_level']) - 1
            if 0 <= idx < 3:
                target_order_ids[idx] = order.get('order_id')
        
        # Create trade record
        trade_record = {
            'symbol': original_symbol,
            'trading_symbol': trading_symbol,
            'underlying': underlying,
            'qty': qty,
            'remaining_qty': qty,
            'entry_price': fill_price,
            'entry_time': datetime.now().isoformat(),
            'sl': sl_price,
            'targets': targets,
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
        
        # Update tracker with exit orders from om.place_partial_exits
        trade_record['exit_orders'] = exit_orders
        trade_record['alert_range'] = signal.get('alert_range', 0)
        exit_mode = exit_orders.get('mode', signal.get('exit_mode', 'single_lot'))
        
        self.tracker.update_trade(trade_id, {
            'exit_orders': exit_orders,
            'alert_range': signal.get('alert_range', 0)
        })
        
        self.logger.info(f"✅ Trade Created: {trade_id} | {underlying} | Entry: ₹{fill_price} | SL: ₹{sl_price} | Targets: {targets}")
        
        # Telegram: entry confirmed
        self.telegram.entry_confirmed(
            symbol=original_symbol,
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
                        gap_threshold = 0.02  # 2% gap-up threshold
                        
                        if ltp > trigger_price * (1 + gap_threshold):
                            # Large gap — simulate realistic slippage
                            simulated_fill = round((trigger_price + ltp) / 2, 2)
                            self.logger.info(
                                f"[PAPER] Gap-fill simulated: trigger=₹{trigger_price}, "
                                f"ltp=₹{ltp}, fill=₹{simulated_fill}"
                            )
                        else:
                            # Normal fill — at trigger price
                            simulated_fill = trigger_price
                            
                        self.logger.info(
                            f"🎯 [PAPER] PENDING ENTRY FILLED: {symbol} @ ₹{simulated_fill} "
                            f"(trigger: ₹{trigger_price})"
                        )
                        self._activate_trade_from_pending(pending, fill_price=simulated_fill)
                        del self.pending_entries[symbol]
                        self.tracker.save_pending_entries(self.pending_entries)
                    continue
                
                # LIVE TRADING: Check actual broker order status
                order_status = self.client.get_order_status(order_id)
                
                if order_status is None:
                    continue
                
                status = order_status.get('status', '').upper()
                
                if is_order_filled(status):
                    # ORDER FILLED - Create active trade
                    fill_price = order_status.get('fill_price') or pending['trigger_price']
                    self.logger.info(f"Fill price extracted: ₹{fill_price} (trigger was: ₹{pending['trigger_price']})")
                    
                    self.logger.info(f"🎯 PENDING ENTRY FILLED: {symbol} @ ₹{fill_price}")
                    self._activate_trade_from_pending(pending, fill_price=fill_price)
                    del self.pending_entries[symbol]
                    self.tracker.save_pending_entries(self.pending_entries)
                    
                elif status in ('CANCELLED', 'REJECTED', 'EXPIRED'):
                    self.logger.warning(
                        f"⚠️ Pending entry {order_id} was {status} for {symbol}. "
                        f"No position opened."
                    )
                    # Notify trader
                    self.telegram._send(
                        f"⚠️ <b>Entry Order {status}</b>\n"
                        f"Symbol: <code>{symbol}</code>\n"
                        f"Order: {order_id}\n"
                        f"No position was opened. Reason: {status}\n"
                        f"Check margin/limits on Groww app."
                    )
                    # Consume the strategy alert so no orphan ENTRY signals fire
                    original_symbol = pending.get('original_symbol', symbol)
                    self.strategy.consume_alert(original_symbol)
                    self.logger.info(f"Strategy alert consumed for {original_symbol} after rejection")
                    
                    del self.pending_entries[symbol]
                    self.tracker.save_pending_entries(self.pending_entries)
                    
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
                    
                    final_pnl = (exit_price - float(trade['entry_price'])) * float(trade['remaining_qty'])
                    total_pnl = final_pnl + float(trade.get('partial_pnl', 0))
                    self.daily_pnl += final_pnl
                    self.tracker.close_trade(trade_id, exit_price, exit_reason, total_pnl)
                    self.trade_logger.log_exit(trade, exit_price, exit_reason, self.daily_pnl)
                    continue
                
                # Check single lot final target first
                if exit_mode == 'single_lot':
                    target_idx = self.config.get('strategy', {}).get('single_lot_exit_target', 2) - 1
                    target_price = targets[target_idx] if target_idx < len(targets) else targets[-1]
                    if ltp >= target_price:
                        # Single lot mode: Target is final exit
                        self.logger.info(f"🎯 [PAPER] TARGET HIT (FINAL) for {symbol} @ ₹{ltp} - Closing Trade")
                        final_pnl = (ltp - float(trade['entry_price'])) * float(trade['remaining_qty'])
                        total_pnl = final_pnl + float(trade.get('partial_pnl', 0))
                        self.daily_pnl += final_pnl
                        self.tracker.close_trade(trade_id, ltp, f"TP{target_idx+1}_HIT", total_pnl)
                        self.trade_logger.log_exit(trade, ltp, f"TP{target_idx+1}_HIT", self.daily_pnl)
                    continue
                
                # Check TP1 (multi-lot only - trail SL)
                if exit_mode == 'multi_lot' and len(targets) > 0 and trail_state < 1 and ltp >= targets[0]:
                    self.logger.info(f"🎯 [PAPER] TP1 HIT for {symbol} @ ₹{ltp}")
                    self._handle_paper_tp_hit(trade, 1, ltp)
                    trail_state = trade.get('exit_orders', {}).get('trail_state', 0)  # Re-read
                
                # Check TP2 
                if exit_mode == 'multi_lot' and len(targets) > 1 and trail_state == 1 and ltp >= targets[1]:
                    self.logger.info(f"🎯 [PAPER] TP2 HIT for {symbol} @ ₹{ltp}")
                    self._handle_paper_tp_hit(trade, 2, ltp)
                    trail_state = trade.get('exit_orders', {}).get('trail_state', 0)  # Re-read
                
                # Check TP3 (multi-lot only - final exit)
                if exit_mode == 'multi_lot' and len(targets) > 2 and trail_state == 2 and ltp >= targets[2]:
                    self.logger.info(f"🚀 [PAPER] TP3 HIT for {symbol} @ ₹{ltp} - Closing Trade")
                    final_pnl = (ltp - float(trade['entry_price'])) * float(trade['remaining_qty'])
                    total_pnl = final_pnl + float(trade.get('partial_pnl', 0))
                    self.daily_pnl += final_pnl
                    self.tracker.close_trade(trade_id, ltp, "TP3_HIT", total_pnl)
                    self.trade_logger.log_exit(trade, ltp, "TP3_HIT", self.daily_pnl)
                
                continue
            
            # LIVE TRADING: Check actual broker order statuses
            # 1. Check SL Order Status
            if sl_order_id:
                sl_status = self.client.get_order_status(sl_order_id)
                if sl_status:
                    sl_state = sl_status.get('status', '').upper()
                    
                    if is_order_filled(sl_state):
                        self.logger.info(f"🔴 SL HIT for {symbol} (Order {sl_order_id})")
                        fill_price = sl_status.get('fill_price') or float(trade['sl'])
                        self.logger.info(f"SL Fill price extracted: \u20b9{fill_price} (reference was: \u20b9{trade['sl']})")
                        
                        # Cancel all pending target orders
                        for tid in target_ids:
                            if tid:
                                self.om.cancel_order(tid)
                        
                        # Close trade
                        final_pnl = (float(fill_price) - float(trade['entry_price'])) * float(trade['remaining_qty'])
                        total_pnl = final_pnl + float(trade.get('partial_pnl', 0))
                        self.daily_pnl += final_pnl 
                        self.tracker.close_trade(trade_id, fill_price, "SL_HIT", total_pnl)
                        self.trade_logger.log_exit(trade, fill_price, "SL_HIT", self.daily_pnl)
                        continue
                    
                    elif sl_state in ('CANCELLED', 'REJECTED', 'EXPIRED'):
                        # Exchange cancelled our SL — CRITICAL: re-place immediately
                        self.logger.critical(
                            f"🚨 SL order {sl_order_id} was {sl_state} by exchange/broker! "
                            f"Re-placing SL immediately for {symbol}..."
                        )
                        self.telegram._send(
                            f"🚨 <b>SL ORDER CANCELLED BY EXCHANGE</b>\n"
                            f"Symbol: <code>{symbol}</code>\n"
                            f"Order: {sl_order_id} → {sl_state}\n"
                            f"Re-placing SL now..."
                        )
                        current_sl = trade.get('exit_orders', {}).get('current_sl', trade['sl'])
                        remaining_qty = trade.get('remaining_qty', trade['qty'])
                        underlying = trade.get('underlying', 'NIFTY')
                        trading_symbol = trade.get('trading_symbol', symbol)
                        
                        # Use place_sl_order from order_manager
                        new_sl_order = self.om.place_sl_order(
                            symbol, remaining_qty, current_sl, trading_symbol
                        )
                        
                        if new_sl_order and new_sl_order.get('groww_order_id'):
                            new_sl_id = new_sl_order['groww_order_id']
                            self.tracker.update_trade(trade_id, {'sl_order_id': new_sl_id})
                            trade['sl_order_id'] = new_sl_id
                            self.logger.critical(f"✅ SL re-placed: {new_sl_id} @ \u20b9{current_sl}")
                            self.telegram._send(
                                f"✅ <b>SL Re-placed</b>\n"
                                f"Symbol: <code>{symbol}</code>\n"
                                f"New SL: \u20b9{current_sl} | Order: {new_sl_id}"
                            )
                        else:
                            self.logger.critical(
                                f"🚨🚨 SL RE-PLACEMENT FAILED for {symbol}! "
                                f"EMERGENCY EXIT to protect capital."
                            )
                            ltp = self.client.get_ltp(symbol) or current_sl
                            # Use _close_entire_position or similar logic locally if not existent
                            # For now, let's assume we place an exit order immediately
                            self.om.place_exit_order(symbol, remaining_qty, trading_symbol, "EMERGENCY_NO_SL")
                            self.tracker.close_trade(trade_id, ltp, "EMERGENCY_NO_SL", trade.get('partial_pnl', 0))
                            continue

            # 2. Check Target Order Statuses
            exit_mode = exit_orders.get('mode', 'single_lot')
            
            # Check Targets Iteratively
            for i, tid in enumerate(target_ids):
                tp_level = i + 1
                if not tid: continue
                
                # Only check if this target level hasn't been hit yet 
                # (For multi-lot, trail_state keeps track. For single-lot, it's just one hit then exit)
                if exit_mode == 'multi_lot' and tp_level <= trail_state:
                    continue
                    
                t_status = self.client.get_order_status(tid)
                if t_status and is_order_filled(t_status.get('status')):
                    fill_price = t_status.get('fill_price') or float(trade['entry_price'])
                    self.logger.info(f"Target Fill price extracted: ₹{fill_price} (reference was: ₹{trade['entry_price']})")
                    
                    if exit_mode == 'single_lot' or (exit_mode == 'multi_lot' and tp_level == 3):
                        # Final Exit (Single Lot OR Multi-lot TP3)
                        self.logger.info(f"🚀 TP{tp_level} HIT (FINAL) for {symbol} - Closing Trade")
                        
                        if sl_order_id:
                            self.om.cancel_order(sl_order_id)
                            self.logger.info(f"🛡️ SL Order Cancelled: {sl_order_id}")
                        
                        # Calculate PnL and close trade
                        final_pnl = (float(fill_price) - float(trade['entry_price'])) * float(trade['remaining_qty'])
                        total_pnl = final_pnl + float(trade.get('partial_pnl', 0))
                        self.daily_pnl += final_pnl
                        self.tracker.close_trade(trade_id, fill_price, f"TP{tp_level}_HIT", total_pnl)
                        self.trade_logger.log_exit(trade, fill_price, f"TP{tp_level}_HIT", self.daily_pnl)
                        break  # Trade is closed
                    
                    elif exit_mode == 'multi_lot':
                        # Partial Exit (TP1 or TP2)
                        self.logger.info(f"🎯 TP{tp_level} HIT for {symbol}")
                        self._handle_tp_hit(trade, tp_level, t_status)
                        trail_state = trade.get('exit_orders', {}).get('trail_state', 0)
    
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
        lots = self.config['strategy'].get('lots_per_trade', 3)
        lots_per_tp = lots // 3
        remainder = lots - (2 * lots_per_tp)
        
        if tp_level == 1 or tp_level == 2:
            partial_qty = lots_per_tp * lot_size
        else:
            partial_qty = remainder * lot_size
            
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
        
        fill_price = float(order_status.get('fill_price') or order_status.get('price') or trade['entry_price'])
        self.logger.info(f"Target Hit: Fill price extracted: ₹{fill_price} (reference was: {trade['entry_price']})")
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
        self.trade_logger.log_partial_exit(trade, qty_filled, fill_price, f"TP{tp_level}", partial_profit, self.daily_pnl)
        
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
        
        # Trail on TP1 hit (to BE)
        if target_idx >= 1 and ltp >= targets[0] and trail_state == 0:
            self.logger.info(f"🎯 TP1 reached for {trade_id} at ₹{ltp}")
            
            # Trail SL (no exit) - Move from alert_low-1 to alert_high-1 (Entry)
            new_sl = exit_orders['current_sl'] + alert_range
            exit_orders['current_sl'] = new_sl
            exit_orders['trail_state'] = 1
            
            # Modify broker SL order with new trigger
            if sl_order_id:
                self.om.modify_sl_order(sl_order_id, new_sl)
                self.logger.info(f"🛡️ Broker SL Modified: {sl_order_id} → ₹{new_sl} (BE)")
            
            self.logger.info(f"✅ SL trailed to ₹{new_sl} (no exit)")
            # Update trail_state local variable for the next check
            trail_state = 1

        # Trail on TP2 hit (to TP1 level)
        if target_idx >= 2 and ltp >= targets[1] and trail_state == 1:
            self.logger.info(f"🎯 TP2 reached for {trade_id} at ₹{ltp}")
            
            # Trail SL (no exit) - Move from alert_high-1 to TP1-1
            new_sl = exit_orders['current_sl'] + alert_range
            exit_orders['current_sl'] = new_sl
            exit_orders['trail_state'] = 2
            
        # Check configured target hit (FINAL EXIT for single-lot mode)
        # Using IF instead of ELIF to allow trail + exit in same poll cycle
        if ltp >= targets[target_idx]:
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
        exit_orders = trade.get('exit_orders', {})
        
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
        
        # Outage detection variables
        consecutive_poll_failures = 0
        MAX_CONSECUTIVE_FAILURES = 10  # ~10 seconds at 1s polling = network outage signal
        last_outage_alert_time = None   # prevent repeated Telegram spam
        
        # Main loop
        while True:
            try:
                now = datetime.now()
                
                # HEARTBEAT
                if (now - last_heartbeat).total_seconds() >= heartbeat_interval:
                    self.logger.info(f"Heartbeat - Bot is running. Active trades: {len(self.tracker.get_active_trades())}")
                    last_heartbeat = now
                
                # Trading Hours Guard
                now_ist = datetime.now(IST)
                current_time_ist = now_ist.time().replace(tzinfo=None)
                
                if current_time_ist < MARKET_OPEN_IST:
                    if (now - last_heartbeat).total_seconds() >= heartbeat_interval:
                        self.logger.info(
                            f"[WAITING] Market opens at 09:15 IST. "
                            f"Current time: {current_time_ist.strftime('%H:%M:%S')} IST"
                        )
                        last_heartbeat = now
                    time.sleep(60)
                    continue
                
                if current_time_ist > MARKET_CLOSE_IST:
                    self.logger.info("Market closed (past 15:30 IST). Bot idle.")
                    time.sleep(300)  # check again in 5 minutes
                    continue

                # Auto square-off (MIS)
                current_time = now.strftime('%H:%M')
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
                                try:
                                    self.om.cancel_order(order_id)
                                    self.logger.info(f"Cancelled pending entry: {symbol}")
                                except: pass
                        self.pending_entries.clear()
                    
                    # Square off active trades
                    active_trades = self.tracker.get_active_trades()
                    for trade in active_trades:
                        self.logger.info(f"Squaring off: {trade['trade_id']}")
                        
                        # Cancel SL and target orders
                        sl_id = trade.get('sl_order_id')
                        if sl_id:
                            try: self.om.cancel_order(sl_id)
                            except: pass
                        for tid in trade.get('target_order_ids', []):
                            if tid:
                                try: self.om.cancel_order(tid)
                                except: pass
                        
                        remaining_qty = trade.get('remaining_qty', trade['qty'])
                        
                        # Place exit order
                        exit_resp = self.om.place_exit_order(
                            trade['symbol'], remaining_qty, trade['trading_symbol'], "SQ_OFF"
                        )
                        
                        # Actual fill Detection (PROMPT 16 - Tiered approach)
                        actual_fill = None
                        if exit_resp and exit_resp.get('groww_order_id'):
                            exit_order_id = exit_resp['groww_order_id']
                            time.sleep(3)  # Allow time to fill
                            try:
                                exit_status = self.client.get_order_status(exit_order_id)
                                if exit_status and is_order_filled(exit_status.get('status', '')):
                                    actual_fill = exit_status.get('fill_price')
                                    self.logger.info(f"SQ_OFF filled at \u20b9{actual_fill} via our order")
                            except: pass
                        
                        # Tier 2: Check for MIS auto-square fill
                        if not actual_fill:
                            self.logger.info("Checking for MIS auto-square fills in order book...")
                            try:
                                day_orders = self.client.client.get_order_list(segment='FNO')
                                for order in reversed(day_orders.get('orders', [])):
                                    if (order.get('trading_symbol') == trade.get('trading_symbol')
                                        and order.get('transaction_type', '').upper() == 'SELL'
                                        and is_order_filled(order.get('order_status', ''))):
                                        actual_fill = float(order.get('average_fill_price') or 0)
                                        if actual_fill > 0:
                                            self.logger.info(f"Found auto-square fill: \u20b9{actual_fill}")
                                            break
                            except: pass
                        
                        # Tier 3: Fallback to LTP
                        if not actual_fill:
                            actual_fill = self.client.get_ltp(trade['symbol']) or float(trade['entry_price'])
                            self.logger.warning(f"Using LTP fallback for SQ_OFF P&L: \u20b9{actual_fill}")
                            
                        # Close trade
                        partial_pnl = trade.get('partial_pnl', 0)
                        final_pnl = (float(actual_fill) - float(trade['entry_price'])) * remaining_qty
                        total_pnl = final_pnl + partial_pnl
                        self.daily_pnl += final_pnl
                        
                        self.tracker.close_trade(trade['trade_id'], actual_fill, "SQ_OFF", total_pnl)
                        self.trade_logger.log_exit(trade, actual_fill, "SQ_OFF", self.daily_pnl)
                        self.telegram.square_off(trade['symbol'], actual_fill, float(trade['entry_price']), remaining_qty, "SQ_OFF")
                        
                    self.logger.info(f"✅ End of session. Daily P&L: ₹{self.daily_pnl:.2f}")
                    break

                # Check Daily Loss Limit
                if self._check_daily_loss_limit():
                    self.logger.critical("Daily loss limit reached. Emergency shutdown.")
                    self.telegram.daily_loss_limit_hit(self.daily_pnl, self.max_loss_per_day)
                    # Square off remaining positions
                    active_trades = self.tracker.get_active_trades()
                    for trade in active_trades:
                        # CRITICAL FIX #6: Use remaining_qty, not original qty
                        remaining_qty = trade.get('remaining_qty', trade['qty'])
                        self.om.place_exit_order(
                            trade['symbol'],
                            remaining_qty,
                            trade['trading_symbol'],
                            "DAILY_LOSS_LIMIT"
                        )
                        ltp = self.client.get_ltp(trade['symbol']) or trade['entry_price']
                        # Only calculate P&L on remaining qty; partials already in daily_pnl
                        final_pnl = (ltp - trade['entry_price']) * remaining_qty
                        partial_pnl = trade.get('partial_pnl', 0)
                        total_pnl = final_pnl + partial_pnl
                        self.daily_pnl += final_pnl
                        self.tracker.close_trade(trade['trade_id'], ltp, "DAILY_LOSS_LIMIT", total_pnl)
                    break

                # Process Candle Logic
                if self._poll_candle_close():
                    self._update_option_universe()
                    self._process_strategy_logic()
                
                # Monitor active positions and pending entries
                self._monitor_pending_entries()
                self._monitor_active_trades()
                
                consecutive_poll_failures = 0
                time.sleep(1)

            except Exception as e:
                consecutive_poll_failures += 1
                self.logger.error(f"Main loop error [{consecutive_poll_failures}/10]: {e}", exc_info=True)
                
                if consecutive_poll_failures >= 10:
                    now = datetime.now()
                    if last_outage_alert_time is None or (now - last_outage_alert_time).total_seconds() > 300:
                        self.telegram._send("🚨 <b>NET OUTAGE</b> detected.")
                        last_outage_alert_time = now
                
                time.sleep(5)
                continue
        
        self.logger.info(f"TRADING SESSION ENDED | Daily P&L: ₹{self.daily_pnl:.2f}")
        
        # Telegram: daily summary
        closed_trades = self.tracker.get_closed_trades_today() if hasattr(self.tracker, 'get_closed_trades_today') else []
        total = len(closed_trades)
        wins = sum(1 for t in closed_trades if float(t.get('pnl', 0)) > 0)
        losses = total - wins
        best = max((float(t.get('pnl', 0)) for t in closed_trades), default=None) if closed_trades else None
        worst = min((float(t.get('pnl', 0)) for t in closed_trades), default=None) if closed_trades else None
        self.telegram.daily_summary(total, wins, losses, self.daily_pnl, best, worst)
