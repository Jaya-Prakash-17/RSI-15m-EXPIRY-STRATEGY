# backtest/intraday_engine.py
import pandas as pd
import logging
import numpy as np
from datetime import datetime, time, timedelta
from utils.nse_calendar import is_trading_day

class IntradayEngine:
    def __init__(self, data_manager, config):
        self.logger = logging.getLogger("BacktestEngine")
        self.dm = data_manager
        self.config = config
        
        from strategy.expiry_rsi_breakout import ExpiryRSIBreakout
        self.strategy_cls = ExpiryRSIBreakout 
        
        # Issue 4: Capital Isolation
        self.capital = config['capital']['initial'] 
        self.trades = []
        
        self.start_time = datetime.strptime(config['trading']['window']['start'], "%H:%M").time()
        self.end_time = datetime.strptime(config['trading']['window']['end'], "%H:%M").time()
        self.sq_off_time = datetime.strptime(config['trading']['window']['auto_square_off'], "%H:%M").time()
        
        self.max_loss_per_day = config['risk']['max_loss_per_day']
        self.last_processed_candle_time = {} 

    def _get_latest_candle(self, df, t):
        matches = df[df['datetime'] <= t]
        if matches.empty:
            return None
        return matches.iloc[-1]

    def _round_to_tick(self, price, underlying):
        tick_size = self.config['indices'][underlying]['tick_size']
        return round(price / tick_size) * tick_size

    def _is_expiry_day(self, underlying, date):
        """
        Calculate if a given date is an expiry day for the underlying.
        Works for historical backtesting by calculating based on NSE rules.
        
        NIFTY: Weekly expiry
            - Jan 2025 – Aug 2025: Thursday
            - From Sep 2, 2025: Tuesday
        
        SENSEX: Weekly expiry
            - Jan 2025 – Aug 2025: Tuesday
            - From Sep 1, 2025: Thursday
        
        BANKNIFTY: Monthly expiry (Last week of month)
            - Jan 2025 – Aug 2025: Last Thursday of month
            - From Sep 1, 2025: Last Tuesday of month
        """
        import calendar
        from datetime import date as date_type
        from utils.nse_calendar import is_trading_day
        
        if isinstance(date, datetime):
            check_date = date.date()
        elif isinstance(date, pd.Timestamp):
            check_date = date.date()
        else:
            check_date = date
        
        weekday = check_date.weekday()  # 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
        
        # Date thresholds for rule changes
        nifty_change_date = date_type(2025, 9, 2)    # NIFTY: Sep 2, 2025
        sensex_change_date = date_type(2025, 9, 1)   # SENSEX: Sep 1, 2025
        banknifty_change_date = date_type(2025, 9, 1) # BANKNIFTY: Sep 1, 2025
        
        if underlying == 'NIFTY':
            # NIFTY: Weekly expiry
            if check_date < nifty_change_date:
                target_weekday = 3  # Thursday (before Sep 2, 2025)
            else:
                target_weekday = 1  # Tuesday (from Sep 2, 2025)
            
            # Check if this is the target weekday
            if weekday != target_weekday:
                return False
            
            # Check if it's a trading day (not holiday)
            if not is_trading_day(check_date):
                return False
            
            return True
        
        elif underlying == 'SENSEX':
            # SENSEX: Weekly expiry
            if check_date < sensex_change_date:
                target_weekday = 1  # Tuesday (before Sep 1, 2025)
            else:
                target_weekday = 3  # Thursday (from Sep 1, 2025)
            
            # Check if this is the target weekday
            if weekday != target_weekday:
                return False
            
            # Check if it's a trading day (not holiday)
            if not is_trading_day(check_date):
                return False
            
            return True
        
        elif underlying == 'BANKNIFTY':
            # BANKNIFTY: Monthly expiry (LAST occurrence of expiry day in month)
            if check_date < banknifty_change_date:
                target_weekday = 3  # Last Thursday (before Sep 1, 2025)
            else:
                target_weekday = 1  # Last Tuesday (from Sep 1, 2025)
            
            # Check if this is the target weekday
            if weekday != target_weekday:
                return False
            
            # Check if this is the LAST occurrence of this weekday in the month
            year = check_date.year
            month = check_date.month
            last_day = calendar.monthrange(year, month)[1]
            last_date = date_type(year, month, last_day)
            
            # Find last occurrence of target weekday
            while last_date.weekday() != target_weekday:
                last_date = last_date - pd.Timedelta(days=1)
            
            # If holiday, adjust to previous trading day
            original_last_date = last_date
            if not is_trading_day(last_date):
                while not is_trading_day(last_date):
                    last_date = last_date - pd.Timedelta(days=1)
            
            # Match if this is the calculated last expiry
            return check_date == last_date or check_date == original_last_date
        
        else:
            # Other indices: Use config expiry_day for weekly
            exp_day_name = self.config['indices'][underlying].get('expiry_day', 'Thursday')
            day_map = {'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3, 'Friday': 4}
            target_weekday = day_map.get(exp_day_name, 3)
            
            return weekday == target_weekday and is_trading_day(check_date)

    def run(self, start_date, end_date):
        self.logger.info(f"Starting backtest from {start_date} to {end_date}")
        self.capital = self.config['capital']['initial']
        self.trades = []
        
        trade_only_on_expiry = self.config['strategy'].get('trade_only_on_expiry', True)
        
        current_date = start_date
        while current_date <= end_date:
            self.last_processed_candle_time = {}
            
            should_trade = False
            indices_to_trade = []
            
            # Valid trading days (exclude Saturday/Sunday which are used to disable indices)
            valid_days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
            current_day_name = current_date.strftime("%A")
            
            # Check if this is a trading day (handles special days like Budget Day on weekends)
            if not is_trading_day(current_date):
                day_name = current_date.strftime("%A")
                self.logger.info(f"Skipping {current_date.date()} ({day_name}) - Not a trading day")
                current_date += pd.Timedelta(days=1)
                continue
            
            if trade_only_on_expiry:
                # For backtesting: Calculate if current date is an expiry day
                # API only returns future expiries, so we need to calculate historical ones
                for idx, details in self.config['indices'].items():
                    # Skip if index is disabled (Saturday/Sunday expiry)
                    if details['expiry_day'] not in valid_days:
                        continue
                    
                    # Calculate if this date is an expiry for this index
                    is_expiry = self._is_expiry_day(idx, current_date)
                    
                    if is_expiry:
                        self.logger.info(f"EXPIRY DAY: {current_date.date()} is expiry for {idx}")
                        indices_to_trade.append(idx)
                        should_trade = True
            else:
                # Trade all days - but only include indices with valid expiry days configured
                for idx, details in self.config['indices'].items():
                    if details['expiry_day'] in valid_days:
                        indices_to_trade.append(idx)
                should_trade = len(indices_to_trade) > 0
            
            if should_trade and indices_to_trade:
                self.logger.info(f"Processing {current_date.date()} - Trading {indices_to_trade}")
                for idx in indices_to_trade:
                    self.process_expiry_day(idx, current_date)
            else:
                self.logger.info(f"Skipping {current_date.date()} - No indices to trade")

            
            self.dm.clear_cache()
            current_date += pd.Timedelta(days=1)
        
        return self.generate_report()

    def process_expiry_day(self, underlying, date):
        # Calculate RSI warmup period
        strategy = self.strategy_cls(self.config)
        warmup_candles = strategy.rsi_warmup
        
        # For stable RSI, fetch at least 100 candles (minimum 10 trading days)
        # This ensures RSI values are more stable and closer to broker values
        warmup_candles = max(warmup_candles, 100)
        
        warmup_minutes = warmup_candles * 15  # 15-min candles
        
        # Start fetching from previous day to ensure warmup data
        from datetime import timedelta
        # Add extra days to account for weekends/holidays
        warmup_days = (warmup_minutes // (60 * 24)) + 10  # At least 10 days back
        warmup_start = date.replace(hour=0, minute=0) - timedelta(days=warmup_days)
        
        self.logger.info(f"Fetching data with {warmup_candles} candle warmup from {warmup_start}")
        
        spot_df = self.dm.get_spot_candles(underlying, warmup_start, date.replace(hour=23, minute=59))
        if spot_df.empty:
            self.logger.warning(f"No spot data for {underlying} on {date.date()}")
            return
        
        spot_df = spot_df.sort_values('datetime').reset_index(drop=True)

        start_datetime = datetime.combine(date.date(), self.start_time)
        start_row = self._get_latest_candle(spot_df, start_datetime)
        
        if start_row is None:
            self.logger.warning(f"No spot data available at start time {start_datetime} for {underlying}")
            return
            
        universe_ref_price = start_row['open'] 
        
        strike_step = 50 if underlying == 'NIFTY' else 100
        if underlying == 'SENSEX': strike_step = 100
        
        center_strike = round(universe_ref_price / strike_step) * strike_step
        min_strike = center_strike - (2 * strike_step)
        max_strike = center_strike + (2 * strike_step)
        strikes = range(int(min_strike), int(max_strike) + strike_step, strike_step)
        
        option_data = {}
        for strike in strikes:
            for opt_type in ['CE', 'PE']:
                symbol = self.dm.build_option_symbol(underlying, date, strike, opt_type, use_historical=True)  # Use historical expiry for backtests
                try:
                    # Fetch with warmup period
                    df = self.dm.get_derivative_candles(
                        underlying, symbol, date.year, warmup_start, date.replace(hour=23, minute=59)
                    )
                    if not df.empty:
                        df = df.sort_values('datetime').reset_index(drop=True)
                        option_data[symbol] = df
                except Exception as e:
                    # Silently skip missing options (some strikes may not exist)
                    pass
        
        if not option_data:
            self.logger.warning("No option data loaded.")
            return

        strategy = self.strategy_cls(self.config)
        timestamps = sorted(spot_df['datetime'].unique())
        # CRITICAL FIX: Only process candles from the actual backtest date, not warmup period
        # This prevents signals from warmup days appearing in backtest results
        backtest_date = date.date()
        timestamps = [t for t in timestamps if t.date() == backtest_date and self.start_time <= t.time()] 
        
        active_trade = None 
        has_traded_today = False
        daily_pnl = 0
        
        # Debug counter
        debug_count = 0
        max_debug = 3
        self.logger.info(f"DEBUG: Found {len(timestamps)} timestamps to process for {backtest_date}")
        
        for t in timestamps:
            if t.time() >= self.sq_off_time:
                if active_trade:
                    pnl = self._close_trade(active_trade, t, "SQ_OFF", option_data)
                    daily_pnl += pnl
                    self.trades.append(active_trade)
                    active_trade = None
                break 

            current_spot_row = self._get_latest_candle(spot_df, t)
            if current_spot_row is None: continue
            current_spot_price = current_spot_row['close']

            if active_trade:
                trade_pnl_realized = self._manage_active_trade(active_trade, t, option_data)
                if active_trade['status'] == 'CLOSED':
                    self.trades.append(active_trade)
                    daily_pnl += trade_pnl_realized
                    active_trade = None
                continue 

            if has_traded_today: continue 
            if daily_pnl <= -self.max_loss_per_day: break
            if t.time() > self.end_time: continue

            candidates = []
            
            for symbol, df in option_data.items():
                row = self._get_latest_candle(df, t)
                if row is None: continue
                
                # Issue 5: Duplicate Candle Check
                last_time = self.last_processed_candle_time.get(symbol)
                current_candle_time = row['datetime']
                
                if last_time and current_candle_time <= last_time:
                    continue
                
                self.last_processed_candle_time[symbol] = current_candle_time
                
                # Issue 6: RSI History Integrity
                history_closes = df[df['datetime'] <= current_candle_time]['close']
                
                # Debug logging
                if debug_count < max_debug:
                    self.logger.info(f"DEBUG: {symbol} at {t} - history_closes: {len(history_closes)} rows")
                
                signal = strategy.check_signal(symbol, row, history_closes)
                
                # Debug signal result
                if debug_count < max_debug and signal:
                    self.logger.info(f"DEBUG: {symbol} signal: {signal.get('action', 'None')}")
                
                if signal and signal['action'] == 'ENTRY':
                    parts = symbol.split('-')
                    try:
                        strike = float(parts[3])
                        dist = abs(strike - current_spot_price)
                        candidates.append({
                            'symbol': symbol,
                            'signal': signal,
                            'dist': dist,
                            'volume': row['volume']
                        })
                    except (ValueError, IndexError) as e:
                        self.logger.warning(f"Symbol parse failed: {symbol} — {e}")
            
            if candidates:
                candidates.sort(key=lambda x: (x['dist'], -x['volume']))
                best = candidates[0]
                active_trade = self._enter_trade(best, t)
                if active_trade:
                    has_traded_today = True
                    strategy.consume_alert(active_trade['symbol'])

    def _enter_trade(self, candidate, time):
        symbol = candidate['symbol']
        signal = candidate['signal']
        # Issue 8: Rounding
        underlying = 'NIFTY'
        if 'BANKNIFTY' in symbol: underlying = 'BANKNIFTY'
        if 'SENSEX' in symbol: underlying = 'SENSEX'
        
        price = self._round_to_tick(signal['price'], underlying)
        sl = self._round_to_tick(signal['sl'], underlying)
        targets = [self._round_to_tick(tgt, underlying) for tgt in signal['targets']]
        
        # BUG-004 FIX: Use config for lot size instead of hardcoded values
        # Historical lot sizes (NIFTY 75→65, BANKNIFTY 35→30 in Sep 2025)
        # are documented in git history. Config always has current values.
        lot_size = self.config['indices'][underlying]['lot_size']
        
        # Get lots_per_trade from config (for multi-lot mode)
        lots_per_trade = self.config['strategy'].get('lots_per_trade', 1)
        total_qty = lot_size * lots_per_trade
        cost = price * total_qty
        
        if self.capital < cost:
            self.logger.info(f"Skipping trade {symbol}: Insufficient capital ({self.capital} < {cost})")
            return None
            
        self.capital -= cost
        
        trade = {
            'symbol': symbol,
            'entry_time': time,
            'entry_price': price,
            'sl': sl,
            'targets': targets,
            'qty': total_qty,  # Fixed: Now uses lots_per_trade multiplier
            'status': 'OPEN',
            'pnl': 0,
            'cost': cost,
            'underlying': underlying
        }
        self.logger.info(f"ENTRY: {symbol} at {price} | Qty: {total_qty} ({lots_per_trade} lots) | Cost: {cost} | Cap: {self.capital}")
        return trade

    def _manage_active_trade(self, trade, time, option_data):
        """
        Manage active trade with multi-lot partial exits:
        - TP1: Exit 33% (1 lot out of 3), trail SL
        - TP2: Exit 33% (1 lot out of 3), trail SL
        - TP3: Exit remaining 34% (1 lot out of 3)
        - SL: Exit all remaining quantity
        """
        symbol = trade['symbol']
        if symbol not in option_data: return 0
        
        df = option_data[symbol]
        row = self._get_latest_candle(df, time)
        if row is None: return 0
        
        realized_pnl = 0
        
        # Initialize partial exit tracking if not present
        if 'remaining_qty' not in trade:
            trade['remaining_qty'] = trade['qty']
            trade['tp_hits'] = 0  # Track how many TPs have been hit
            trade['partial_pnl'] = 0  # Track realized PnL from partial exits
            trade['original_sl'] = trade['sl']
            trade['alert_range'] = trade['targets'][0] - trade['entry_price']  # Range for trailing
        
        # Get exit mode from config
        exit_mode = self.config['strategy'].get('exit_mode', 'multi_lot')
        lots_per_trade = self.config['strategy'].get('lots_per_trade', 3)
        
        # Check SL condition (strategy-defined: alert candle low - 1)
        sl_triggered = row['low'] <= trade['sl']
        
        if sl_triggered:
            exit_price = trade['sl']
            pnl = (exit_price - trade['entry_price']) * trade['remaining_qty']
            realized_pnl = pnl + trade['partial_pnl']
            
            credit = exit_price * trade['remaining_qty']
            self.capital += credit
            
            trade['exit_time'] = time
            trade['exit_price'] = exit_price
            trade['reason'] = 'SL'
            trade['status'] = 'CLOSED'
            trade['pnl'] = realized_pnl
            self.logger.info(f"EXIT SL: {symbol} at {exit_price} | Remaining Qty: {trade['remaining_qty']} | PnL: {realized_pnl}")
            return realized_pnl
        
        # Multi-lot mode: Check each target in order
        if exit_mode == 'multi_lot' and lots_per_trade >= 3:
            # Get lot size for this underlying
            underlying = trade.get('underlying', 'NIFTY')
            # BUG-004 FIX: Use config for lot size instead of hardcoded values
            lot_size = self.config['indices'][underlying]['lot_size']
            
            # Check TP1 (exit 1 lot)
            if trade['tp_hits'] == 0 and row['high'] >= trade['targets'][0]:
                exit_qty = lot_size  # Exit exactly 1 lot
                exit_price = trade['targets'][0]
                pnl = (exit_price - trade['entry_price']) * exit_qty
                
                trade['remaining_qty'] -= exit_qty
                trade['partial_pnl'] += pnl
                trade['tp_hits'] = 1
                
                # Trail SL by alert_range
                new_sl = trade['sl'] + trade['alert_range']
                trade['sl'] = new_sl
                
                # Credit this portion
                self.capital += exit_price * exit_qty
                
                self.logger.info(f"PARTIAL EXIT TP1: {symbol} | Qty: {exit_qty} (1 lot) | Price: {exit_price} | PnL: {pnl} | New SL: {new_sl}")
            
            # Check TP2 (exit 1 lot)
            elif trade['tp_hits'] == 1 and row['high'] >= trade['targets'][1]:
                exit_qty = lot_size  # Exit exactly 1 lot
                exit_price = trade['targets'][1]
                pnl = (exit_price - trade['entry_price']) * exit_qty
                
                trade['remaining_qty'] -= exit_qty
                trade['partial_pnl'] += pnl
                trade['tp_hits'] = 2
                
                # Trail SL by another alert_range
                new_sl = trade['sl'] + trade['alert_range']
                trade['sl'] = new_sl
                
                self.capital += exit_price * exit_qty
                
                self.logger.info(f"PARTIAL EXIT TP2: {symbol} | Qty: {exit_qty} (1 lot) | Price: {exit_price} | PnL: {pnl} | New SL: {new_sl}")
            
            # Check TP3 (exit remaining - should be 1 lot)
            elif trade['tp_hits'] == 2 and row['high'] >= trade['targets'][2]:
                exit_qty = trade['remaining_qty']  # All remaining (should be 1 lot)
                exit_price = trade['targets'][2]
                pnl = (exit_price - trade['entry_price']) * exit_qty
                
                realized_pnl = pnl + trade['partial_pnl']
                
                self.capital += exit_price * exit_qty
                
                trade['exit_time'] = time
                trade['exit_price'] = exit_price
                trade['reason'] = 'TARGET'
                trade['status'] = 'CLOSED'
                trade['pnl'] = realized_pnl
                trade['remaining_qty'] = 0
                
                self.logger.info(f"FINAL EXIT TP3: {symbol} | Qty: {exit_qty} (1 lot) | Price: {exit_price} | Total PnL: {realized_pnl}")
                return realized_pnl
        
        else:
            # Single lot mode: Exit fully at configured target (default: T2)
            target_idx = self.config['strategy'].get('single_lot_exit_target', 2) - 1
            if row['high'] >= trade['targets'][target_idx]:
                exit_price = trade['targets'][target_idx]
                pnl = (exit_price - trade['entry_price']) * trade['qty']
                
                self.capital += exit_price * trade['qty']
                
                trade['exit_time'] = time
                trade['exit_price'] = exit_price
                trade['reason'] = f'TP{target_idx+1}'
                trade['status'] = 'CLOSED'
                trade['pnl'] = pnl
                
                self.logger.info(f"EXIT TP{target_idx+1}: {symbol} at {exit_price} | PnL: {pnl}")
                return pnl
        
        return 0

    def _close_trade(self, trade, time, reason, option_data, price_override=None):
        symbol = trade['symbol']
        if price_override:
            exit_price = price_override
        else:
            df = option_data[symbol]
            row = self._get_latest_candle(df, time)
            if row is not None:
                exit_price = row['close']
            else:
                exit_price = trade['entry_price']
        
        # BUG-001 FIX: Use remaining_qty (not original qty) to avoid
        # inflated P&L after partial exits at TP1/TP2
        remaining = trade.get('remaining_qty', trade['qty'])
        partial_pnl = trade.get('partial_pnl', 0)
        credit = exit_price * remaining
        self.capital += credit
        pnl = (exit_price - trade['entry_price']) * remaining + partial_pnl
        
        trade['exit_time'] = time
        trade['exit_price'] = exit_price
        trade['reason'] = reason
        trade['status'] = 'CLOSED'
        trade['pnl'] = pnl
        trade['qty'] = remaining  # Record actual exit quantity
        
        self.logger.info(f"EXIT: {symbol} at {exit_price} | Remaining Qty: {remaining} | PnL: {pnl} | Reason: {reason}")
        return pnl

    def generate_report(self):
        return pd.DataFrame(self.trades)
