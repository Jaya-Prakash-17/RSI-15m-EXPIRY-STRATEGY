# strategy/expiry_rsi_breakout.py
import pandas as pd
import logging
from datetime import time

class ExpiryRSIBreakout:
    def __init__(self, config):
        self.logger = logging.getLogger("Strategy")
        self.config = config  # Store full config for exit mode access
        self.rsi_period = config['strategy']['rsi']['period']
        self.rsi_threshold = config['strategy']['rsi']['threshold']
        self.alert_validity = config['strategy']['alert_validity']
        self.alert_negation = config['strategy'].get('alert_negation', True)  # Default to True
        self.rsi_warmup = config['strategy']['rsi'].get('warmup_periods', 100)
        self.min_candles_for_signal = config['strategy']['rsi'].get(
            'min_candles_for_signal', self.rsi_period * 3
        )
        
        self.logger.info(
            f"RSI({self.rsi_period}) warmup: {self.rsi_warmup} candles "
            f"({self.rsi_warmup * 15} minutes ≈ {self.rsi_warmup * 15 / 375:.1f} trading days) | "
            f"Min signal candles: {self.min_candles_for_signal}"
        )
        
        # Key: symbol, Value: {alert_candle: dict, age: int, alert_time: datetime, last_processed_time: datetime}
        self.state = {}
        
        # Risk management: SL Floor
        self.min_sl_pct = config['strategy'].get('min_sl_pct', 0.08)
        
        # Time-of-day filters
        from datetime import datetime
        self.signal_start_time = datetime.strptime(
            config['strategy'].get('signal_window_start', '09:30'), "%H:%M"
        ).time()
        self.signal_end_time = datetime.strptime(
            config['strategy'].get('signal_window_end', '15:00'), "%H:%M"
        ).time()
        
        # Debug logging for RSI validation
        self.rsi_debug = config['strategy'].get('rsi_debug', False)
        
        # Risk management: SAFE_SL Mode
        self.safe_sl_mode = config['strategy'].get('safe_sl_mode', False)
        self.safe_sl_max_loss = config['strategy'].get('safe_sl_max_loss', 5000)
        
        if self.safe_sl_mode:
            self.logger.info(f"🛡️ SAFE_SL Mode Enabled | Max Loss Floor: ₹{self.safe_sl_max_loss}")

    def calculate_wilder_rsi(self, prices, return_components=False):
        """
        Broker-grade Wilder's RSI calculation matching Groww's RSI.
        
        Implementation:
        1. Calculate price changes (close[i] - close[i-1])
        2. Separate into gains and losses
        3. First average: SMA of first N gains/losses (CRITICAL for seeding)
        4. Subsequent averages: Wilder's smoothing (prior_avg * (N-1) + current_value) / N
        5. RS = avg_gain / avg_loss
        6. RSI = 100 - (100 / (1 + RS))
        
        Args:
            prices: Pandas Series of close prices
            return_components: If True, returns (rsi_series, gains, losses, avg_gains, avg_losses)
        
        Returns:
            RSI series if return_components=False, else tuple with debug info
        """
        if len(prices) < self.rsi_period + 1:
            # Need at least period + 1 candles for first RSI value
            if return_components:
                return None, None, None, None, None
            return None
        
        # Step 1: Calculate price changes
        delta = prices.diff()  # price[i] - price[i-1]
        
        # Step 2: Separate gains and losses
        gains = delta.copy()
        losses = delta.copy()
        
        gains[gains < 0] = 0  # Gains = positive changes only
        losses[losses > 0] = 0  # Losses = negative changes only
        losses = abs(losses)  # Make losses positive for calculation
        
        # Step 3 & 4: Wilder's smoothing with SMA seeding
        avg_gains = []
        avg_losses = []
        
        # Calculate first average using SMA of first N periods
        # Start from index 1 (skip NaN from diff) to index N+1
        first_avg_gain = gains.iloc[1:self.rsi_period+1].mean()
        first_avg_loss = losses.iloc[1:self.rsi_period+1].mean()
        
        avg_gains.append(first_avg_gain)
        avg_losses.append(first_avg_loss)
        
        # Calculate subsequent averages using Wilder's smoothing
        # Formula: avg[i] = (avg[i-1] * (N-1) + value[i]) / N
        for i in range(self.rsi_period + 1, len(gains)):
            current_gain = gains.iloc[i]
            current_loss = losses.iloc[i]
            
            new_avg_gain = (avg_gains[-1] * (self.rsi_period - 1) + current_gain) / self.rsi_period
            new_avg_loss = (avg_losses[-1] * (self.rsi_period - 1) + current_loss) / self.rsi_period
            
            avg_gains.append(new_avg_gain)
            avg_losses.append(new_avg_loss)
        
        # Step 5 & 6: Calculate RSI
        rsi_values = []
        for avg_gain, avg_loss in zip(avg_gains, avg_losses):
            if avg_loss == 0:
                # No losses = RSI 100
                rsi_values.append(100.0)
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
                rsi_values.append(rsi)
        
        # Create RSI series aligned with prices
        # RSI starts at index rsi_period (first N candles have no RSI)
        rsi_series = pd.Series(index=prices.index, dtype=float)
        rsi_series.iloc[self.rsi_period:] = rsi_values
        
        if return_components:
            return rsi_series, gains, losses, avg_gains, avg_losses
        
        return rsi_series

    def calculate_latest_rsi(self, prices):
        """
        Calculates the LATEST RSI value from a series of prices.
        Returns None if insufficient data for stable RSI calculation.
        
        This is the main method used by the strategy.
        """
        # Absolute minimum: period + 1 candles (15 for period=14)
        absolute_min = self.rsi_period + 1
        
        if len(prices) < absolute_min:
            # Only block if truly impossible to calculate
            self.logger.error(f"CRITICAL: Only {len(prices)} candles, need minimum {absolute_min} for RSI calculation")
            return None
        
        # Warn if less than ideal, but CONTINUE calculating
        recommended_min = max(self.rsi_warmup, 100)
        if len(prices) < recommended_min:
            self.logger.warning(
                f"RSI with only {len(prices)} candles (recommended: {recommended_min}+) - "
                f"may deviate 1-3 points from broker. Trading continues."
            )
        
        # Calculate full RSI series
        rsi_series = self.calculate_wilder_rsi(prices)
        
        if rsi_series is None:
            return None
        
        # Get the latest non-NaN RSI value
        latest_rsi = rsi_series.iloc[-1]
        
        # Debug logging for validation
        if self.rsi_debug and not pd.isna(latest_rsi):
            latest_time = prices.index[-1] if hasattr(prices, 'index') else len(prices)-1
            latest_price = prices.iloc[-1]
            candle_count = len(prices)
            self.logger.debug(f"RSI Debug | Time: {latest_time} | Close: {latest_price:.2f} | RSI: {latest_rsi:.2f} | Candles: {candle_count}")
        
        return latest_rsi if not pd.isna(latest_rsi) else None

    def calculate_rsi(self, prices):
        """
        Legacy method - redirects to Wilder's RSI for consistency.
        Use calculate_latest_rsi() in strategy logic.
        """
        return self.calculate_wilder_rsi(prices)


    def _calculate_effective_sl(self, symbol, entry_price, alert_low):
        """
        Calculates SL based on Alert Range, SL Floor, and SAFE_SL mode.
        Returns: (effective_sl, is_safe_applied, raw_sl)
        """
        # 1. Base distance (High - Low + ₹1 buffer)
        raw_dist = entry_price - alert_low + 1.0
        raw_sl = round(entry_price - raw_dist, 2)
        
        is_safe_applied = False
        dist_after_safe = raw_dist
        
        # 2. Apply SAFE_SL cap if enabled
        if self.safe_sl_mode:
            try:
                parts = symbol.split('-')
                underlying = parts[1] if len(parts) > 1 else 'NIFTY'
                
                lots = self.config['strategy'].get('lots_per_trade', 3)
                lot_size = self.config['indices'].get(underlying, {}).get('lot_size', 50)
                qty = lots * lot_size
                
                if qty > 0:
                    max_allowed_dist = self.safe_sl_max_loss / qty
                    if dist_after_safe > max_allowed_dist:
                        self.logger.info(f"🛡️ [{symbol}] SAFE_SL applied: cap dist {dist_after_safe:.2f} -> {max_allowed_dist:.2f}")
                        dist_after_safe = max_allowed_dist
                        is_safe_applied = True
            except Exception as e:
                self.logger.error(f"Error in SAFE_SL calculation for {symbol}: {e}")

        # 3. Apply SL Floor (minimum distance)
        min_sl_dist = entry_price * self.min_sl_pct
        effective_dist = max(dist_after_safe, min_sl_dist)
        
        if effective_dist > dist_after_safe:
            self.logger.debug(f"[{symbol}] SL floor applied: {dist_after_safe:.2f} -> {effective_dist:.2f}")
            
        effective_sl = round(entry_price - effective_dist, 2)
        return effective_sl, is_safe_applied, raw_sl

    def consume_alert(self, symbol):
        """Manually consumes the alert for a symbol (e.g. after entry)."""
        if symbol in self.state:
            self.state[symbol]['alert'] = None
            self.state[symbol]['age'] = 0
            self.state[symbol]['alert_time'] = None

    def check_signal(self, symbol, current_candle, price_history, is_tradable=True):
        """
        Checks for signals based on candle and RSI.
        STRICTLY separates Alert and Entry.
        Entry cannot happen on the same candle as Alert.
        
        Args:
            symbol: Symbol identifier
            current_candle: The current candle row
            price_history: Pandas Series of closing prices ending with current_candle
            is_tradable: Boolean flag if we are inside trading window
        """
        if symbol not in self.state:
             self.state[symbol] = {
                 'alert': None, 
                 'age': 0, 
                 'alert_time': None, 
                 'last_processed_time': None,
                 'prev_rsi': None,
                 'current_rsi': None
             }
        
        state = self.state[symbol]
        signal = None
        
        current_time = current_candle['datetime']
        
        # Calculate RSI
        current_rsi = self.calculate_latest_rsi(price_history)
        
        # Skip if insufficient data
        if current_rsi is None:
            return None
        
        # MEDIUM FIX #5: Optimized RSI calculation
        # Cache the previous RSI value instead of calculating Wilder's RSI twice per candle.
        # Only update prev_rsi when moving to a strictly new candle.
        if state['last_processed_time'] is not None and current_time > state['last_processed_time']:
            state['prev_rsi'] = state.get('current_rsi')
            
        state['current_rsi'] = current_rsi
        prev_rsi = state['prev_rsi']

        # Age Increment Logic
        # Increment only if we have moved to a NEW candle strictly after the alert
        # And we haven't processed this time yet
        expired_symbol = None  # Track if alert expired this cycle
        if state['alert'] is not None:
             if state['last_processed_time'] is not None and current_time > state['last_processed_time']:
                 # Check if we are strictly after alert_time
                 if current_time > state['alert_time']:
                     # Check if allowed to age (tradable window)
                     if is_tradable:
                        state['age'] += 1
                        # CHANGED: Allow age to reach validity (inclusive) or check strictly > if needed
                        # If alert_validity is 2 candles.
                        # Age 0: Alert Candle.
                        # Age 1: Candle T+1 (Valid).
                        # Age 2: Candle T+2 (Valid).
                        # Age 3: Candle T+3 (Expired).
                        # So expiry check should be: if age > validity
                        if state['age'] > self.alert_validity:
                            self.logger.info(f"Alert expired for {symbol} at {current_time} (Age: {state['age']})")
                            expired_symbol = symbol
                            state['alert'] = None
                            state['age'] = 0
                            state['alert_time'] = None
                     # Else: freeze age (do nothing)
        
        # Return EXPIRED signal if alert just expired
        if expired_symbol:
            return {'action': 'EXPIRED', 'symbol': expired_symbol}
        
        # Update processed time
        state['last_processed_time'] = current_time

        # 1. Check for Entry (existing code)
        if state['alert'] is not None:
            alert_candle = state['alert']
            
            # Entry condition: Price breaks high of alert candle
            if current_time > state['alert_time'] and current_candle['high'] > alert_candle['high']:
                # ... breakout logic ...
                alert_range = alert_candle['high'] - alert_candle['low']
                
                # Calculate Effective SL (Base, Base + SAFE_SL, and Floor)
                effective_sl, is_safe_applied, raw_sl = self._calculate_effective_sl(symbol, alert_candle['high'], alert_candle['low'])

                return {
                    'action': 'ENTRY',
                    'price': alert_candle['high'],
                    'sl': effective_sl,
                    'targets': [
                        alert_candle['high'] + alert_range,
                        alert_candle['high'] + 2 * alert_range,
                        alert_candle['high'] + 3 * alert_range
                    ],
                    'alert_candle': alert_candle,
                    'alert_time': state['alert_time'],
                    'alert_range': alert_range,
                    'rsi': current_rsi if current_rsi is not None else 0.0,
                    'is_safe_sl_applied': is_safe_applied,
                    'raw_sl': raw_sl,
                    'exit_mode': self.config['strategy'].get('exit_mode', 'multi_lot'),
                    'lots_per_trade': self.config['strategy'].get('lots_per_trade', 3)
                }

        # 1b. Check for Alert Negation by Price
        if state['alert'] is not None and self.alert_negation:
            alert_candle = state['alert']
            if current_candle['close'] < alert_candle['low']:
                self.logger.info(
                    f"[{symbol}] Alert NEGATED: close=\u20b9{current_candle['close']:.2f} "
                    f"< alert_low=\u20b9{alert_candle['low']:.2f}"
                )
                state['alert'] = None
                state['age'] = 0
                state['alert_time'] = None
                return {'action': 'NEGATED', 'symbol': symbol}

        # 2. Check for new Alert
        # Time-of-day filter (new alerts only)
        if state['alert'] is None:
            candle_time = current_time.time() if hasattr(current_time, 'time') else current_time
            if candle_time < self.signal_start_time:
                self.logger.debug(f"[{symbol}] Pre-signal window ({candle_time} < {self.signal_start_time}). Skip.")
                return None
            if candle_time > self.signal_end_time:
                self.logger.debug(f"[{symbol}] Post-signal window ({candle_time} > {self.signal_end_time}). Skip.")
                return None

        # Only if we don't have an active alert.
        if state['alert'] is None and is_tradable:
            # Minimum candle quality guard
            if len(price_history) < self.min_candles_for_signal:
                self.logger.debug(
                    f"[{symbol}] Insufficient history: {len(price_history)} < {self.min_candles_for_signal}"
                )
                return None
                
            is_green_candle = current_candle['close'] > current_candle['open']
            if is_green_candle and prev_rsi is not None and prev_rsi < self.rsi_threshold and current_rsi >= self.rsi_threshold:
                alert_candle = {
                    'high': current_candle['high'],
                    'low': current_candle['low'],
                    'datetime': current_candle['datetime']
                }
                
                # Calculate Effective SL (Base, Base + SAFE_SL, and Floor)
                effective_sl, is_safe_applied, raw_sl = self._calculate_effective_sl(symbol, alert_candle['high'], alert_candle['low'])

                state['alert'] = alert_candle
                state['age'] = 0
                state['alert_time'] = current_time
                self.logger.info(f"ALERT: RSI Breakout for {symbol} at {current_time} (RSI: {current_rsi:.2f})")
                
                alert_range = alert_candle['high'] - alert_candle['low']
                return {
                    'action': 'ALERT',
                    'price': alert_candle['high'],
                    'sl': effective_sl,
                    'targets': [
                        alert_candle['high'] + alert_range,
                        alert_candle['high'] + 2 * alert_range,
                        alert_candle['high'] + 3 * alert_range
                    ],
                    'alert_candle': alert_candle,
                    'alert_time': state['alert_time'],
                    'alert_range': alert_range,
                    'rsi': current_rsi if current_rsi is not None else 0.0,
                    'is_safe_sl_applied': is_safe_applied,
                    'raw_sl': raw_sl,
                    'exit_mode': self.config['strategy'].get('exit_mode', 'multi_lot'),
                    'lots_per_trade': self.config['strategy'].get('lots_per_trade', 3)
                }
        
        return signal
