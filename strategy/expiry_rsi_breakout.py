# strategy/expiry_rsi_breakout.py
import pandas as pd
import numpy as np
import logging
from datetime import time
from core.exceptions import InsufficientDataError

class ExpiryRSIBreakout:
    def __init__(self, config):
        self.logger = logging.getLogger("Strategy")
        self.config = config  # Store full config for exit mode access
        self.rsi_period = config['strategy']['rsi']['period']
        self.rsi_threshold = config['strategy']['rsi']['threshold']
        self.alert_validity_candles = config['strategy']['alert_validity_candles']

        self.alert_negation = config['strategy'].get('alert_negation', True)  # Default to True
        self.rsi_warmup = config['strategy']['rsi'].get('warmup_periods', 100)
        self.min_candles_for_signal = config['strategy']['rsi'].get(
            'min_candles_for_signal', self.rsi_period * 3
        )

        self.logger.info(
            f"RSI({self.rsi_period}) warmup: {self.rsi_warmup} candles "
            f"({self.rsi_warmup * 15} minutes ~ {self.rsi_warmup * 15 / 375:.1f} trading days) | "
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

        # V16-P-01: Minimum alert range guard (data quality)
        self.min_alert_range = config['strategy'].get('min_alert_range_points', 0.5)
        if self.min_alert_range <= 0:
            self.logger.warning(f"min_alert_range_points={self.min_alert_range} is invalid. Enforcing 0.5 minimum.")
            self.min_alert_range = 0.5

        # Risk management: SAFE_SL Mode
        self.safe_sl_mode = config['strategy'].get('safe_sl_mode', False)
        self.safe_sl_max_loss = config['strategy'].get('safe_sl_max_loss', 5000)

        if self.safe_sl_mode:
            self.logger.info(f"SAFE_SL Mode Enabled | Max Loss Floor: Rs.{self.safe_sl_max_loss}")

    def export_state(self) -> dict:
        """Export strategy state for persistence."""
        return {
            symbol: {
                k: v.isoformat() if hasattr(v, 'isoformat') else v
                for k, v in state.items()
            }
            for symbol, state in self.state.items()
            if state.get('alert') is not None           # Active alert: persist for recovery guard
            or state.get('last_processed_time') is not None  # Recently processed: persist for audit trail
        }

    def import_state(self, state_dict: dict):
        """Restore strategy state from persistence."""
        from datetime import datetime
        for symbol, state in state_dict.items():
            restored = dict(state)
            # Restore datetime objects
            if 'alert_time' in restored and isinstance(restored['alert_time'], str):
                try:
                    restored['alert_time'] = datetime.fromisoformat(restored['alert_time'])
                except (ValueError, TypeError):
                    restored['alert_time'] = None
            if 'last_processed_time' in restored and isinstance(restored['last_processed_time'], str):
                try:
                    # Support multiple formats for robustness
                    if 'T' in restored['last_processed_time']:
                         restored['last_processed_time'] = datetime.fromisoformat(restored['last_processed_time'])
                    else:
                         restored['last_processed_time'] = datetime.strptime(restored['last_processed_time'], "%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    restored['last_processed_time'] = None

            # Case 1: alert is not None → bot crashed before entry; same-bar guard REQUIRED
            # Case 2: alert is None → bot crashed after consume_alert(); guard NOT needed, trade is active
            if restored.get('alert') is None:
                restored['_recovered_from_crash'] = False  # Alert consumed; same-bar guard not needed
            else:
                restored['_recovered_from_crash'] = True   # Alert still active; guard needed

            self.state[symbol] = restored
            self.logger.info(f"Restored strategy state for {symbol}: alert_age={state.get('age', 0)}")


    def calculate_wilder_rsi(self, prices, return_components=False):
        """
        Wilder's RSI — vectorized via numpy for live trading performance.
        Numerically identical to the previous loop-based implementation.

        Seeding: SMA of first N price changes (indices 1 to N+1).
        Smoothing: avg[i] = (avg[i-1] * (N-1) + value[i]) / N (Wilder's formula).
        """
        n = self.rsi_period

        if len(prices) < n + 1:
            if return_components:
                return None, None, None, None, None
            return None

        # Performance optimization: if already a numpy array, use directly
        close = np.asarray(prices, dtype=np.float64)
        delta = np.diff(close)

        gains = np.where(delta > 0, delta, 0.0)
        losses = np.where(delta < 0, -delta, 0.0)

        # Seed at position n-1
        seed_gain = gains[:n].mean()
        seed_loss = losses[:n].mean()

        avg_gains = np.full(gains.shape, np.nan)
        avg_losses = np.full(losses.shape, np.nan)

        avg_gains[n-1] = seed_gain
        avg_losses[n-1] = seed_loss

        # Iterative Wilder's Smoothing: avg[i] = (avg[i-1] * (n-1) + val[i]) / n
        for i in range(n, len(gains)):
            avg_gains[i] = (avg_gains[i-1] * (n - 1) + gains[i]) / n
            avg_losses[i] = (avg_losses[i-1] * (n - 1) + losses[i]) / n

        with np.errstate(divide='ignore', invalid='ignore'):
            rs = np.where(avg_losses == 0, np.inf, avg_gains / avg_losses)
            rsi_values = np.where(avg_losses == 0, 100.0, 100.0 - 100.0 / (1.0 + rs))

        # Convert back to Series only if needed or keep as array for internal speed
        if isinstance(prices, pd.Series):
            rsi_series = pd.Series(index=prices.index, dtype=float)
            rsi_series.iloc[n:] = rsi_values[n-1:]
            result = rsi_series
        else:
            result = rsi_values

        if return_components:
            return result, gains, losses, list(avg_gains), list(avg_losses)
        return result

    def calculate_latest_rsi(self, prices, return_prev=False):
        """
        Calculates the LATEST RSI value from a series of prices.
        If return_prev is True, returns (latest_rsi, prev_rsi).
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
        rsi_arr = np.asarray(rsi_series)
        valid_idx = np.where(~np.isnan(rsi_arr))[0]
        if len(valid_idx) == 0:
            return (None, None) if return_prev else None

        latest_rsi = float(rsi_arr[valid_idx[-1]])

        # Debug logging for validation
        if self.rsi_debug and not pd.isna(latest_rsi):
            latest_time = prices.index[-1] if hasattr(prices, 'index') else len(prices)-1
            latest_price = prices.iloc[-1] if hasattr(prices, 'iloc') else prices[-1]
            candle_count = len(prices)
            self.logger.debug(f"RSI Debug | Time: {latest_time} | Close: {latest_price:.2f} | RSI: {latest_rsi:.2f} | Candles: {candle_count}")
        # Get the previous non-NaN RSI value if requested
        if return_prev:
            prev_rsi = float(rsi_arr[valid_idx[-2]]) if len(valid_idx) > 1 else np.nan
            return (
                latest_rsi if not pd.isna(latest_rsi) else None,
                prev_rsi if not pd.isna(prev_rsi) else None
            )

        return latest_rsi if not pd.isna(latest_rsi) else None

    def calculate_rsi(self, prices):
        """
        Legacy method - redirects to Wilder's RSI for consistency.
        Use calculate_latest_rsi() in strategy logic.
        """
        return self.calculate_wilder_rsi(prices)

    def batch_calculate_rsi(self, symbols_closes: dict) -> dict:
        """
        Vectorized Live Pulse: Compute (current_rsi, prev_rsi) for ALL symbols
        in a single batch call.

        Args:
            symbols_closes: {symbol: np.ndarray of close prices} or {symbol: pd.Series}

        Returns:
            {symbol: (current_rsi, prev_rsi)} — values are float or None.
            Symbols with insufficient data are returned as (None, None).

        Performance:
            - Avoids per-symbol Python function-call overhead
            - Uses raw numpy arrays internally (no Pandas Series conversion)
            - Pre-computes shared constants (alpha, inv_n) once
        """
        n = self.rsi_period
        min_len = n + 1
        results = {}
        for symbol, prices in symbols_closes.items():
            # BUG-004: Direct reuse of calculate_wilder_rsi for parity
            rsi_data = self.calculate_wilder_rsi(prices)

            if rsi_data is not None and len(rsi_data) > 0:
                 # Convert to array for safe position indexing (Series[-1] fails on numeric index)
                 rsi_arr = np.asarray(rsi_data)
                 valid_idx = np.where(~np.isnan(rsi_arr))[0]

                 if len(valid_idx) == 0:
                     results[symbol] = (None, None)
                     continue

                 curr_val = float(rsi_arr[valid_idx[-1]])
                 prev_val = float(rsi_arr[valid_idx[-2]]) if len(valid_idx) > 1 else None

                 results[symbol] = (
                      curr_val if not np.isnan(curr_val) else None,
                      prev_val if (prev_val is not None and not np.isnan(prev_val)) else None
                 )
            else:
                 results[symbol] = (None, None)

        return results


    def _calculate_effective_sl(self, symbol, entry_price, alert_low):
        """
        Calculates SL based on Alert Range, SL Floor, and SAFE_SL mode.

        Application order (critical for correctness):
          1. Raw distance: entry_price - alert_low + 1.0
          2. SL Floor (min_sl_pct): ensures SL has minimum breathing room
          3. SAFE_SL cap: hard ceiling on loss — ALWAYS wins over floor

        Returns: (effective_sl, is_safe_applied, raw_sl)
        """
        # 1. Base distance (High - Low + Rs.1 buffer)
        raw_dist = entry_price - alert_low + 1.0
        raw_sl = round(entry_price - raw_dist, 2)

        is_safe_applied = False

        # 2. Apply SL Floor FIRST (minimum distance for breathing room)
        min_sl_dist = entry_price * self.min_sl_pct
        effective_dist = max(raw_dist, min_sl_dist)

        if effective_dist > raw_dist:
            self.logger.debug(
                f"[{symbol}] SL floor applied: raw_dist={raw_dist:.2f} "
                f"-> floor={effective_dist:.2f} (min_sl_pct={self.min_sl_pct})"
            )

        # 3. Apply SAFE_SL cap LAST — this is the hard ceiling, always wins
        if self.safe_sl_mode:
            from datetime import datetime
            from utils.historical_lot_sizes import get_historical_lot_size

            qty = 1  # Fallback pre-initialization
            try:
                parts = symbol.split('-')
                underlying = parts[1] if len(parts) > 1 else 'NIFTY'

                lots = self.config['strategy'].get('lots_per_trade', 1)
                # Use today's date for lot size — the SL is calculated at entry time, not expiry
                trade_date = datetime.now().date()
                try:
                    lot_size = get_historical_lot_size(underlying, trade_date)
                except (ValueError, Exception):
                    lot_size = self.config['indices'].get(underlying, {}).get('lot_size', 50)
                    self.logger.warning(f"Lot size fallback for {underlying} on {trade_date}: {lot_size}")

                qty = lots * lot_size

                self.logger.debug(
                    f"[SAFE_SL CALC] {symbol}: entry={entry_price}, "
                    f"alert_low={alert_low}, raw_dist={raw_dist:.2f}, "
                    f"lots={lots}, lot_size={lot_size}, qty={qty}, "
                    f"max_allowed_dist={self.safe_sl_max_loss/qty:.2f}"
                )

                if qty > 0:
                    max_allowed_dist = self.safe_sl_max_loss / qty
                    if effective_dist > max_allowed_dist:
                        self.logger.info(
                            f"[SAFE_SL APPLIED] {symbol}: dist={effective_dist:.2f} "
                            f"capped to {max_allowed_dist:.2f} "
                            f"(safe_sl_max_loss=Rs.{self.safe_sl_max_loss}/qty={qty}). "
                            f"SL: {entry_price - effective_dist:.2f} -> "
                            f"{entry_price - max_allowed_dist:.2f}"
                        )
                        effective_dist = max_allowed_dist
                        is_safe_applied = True
            except Exception as e:
                self.logger.error(f"Error in SAFE_SL calculation for {symbol}: {e}")

        effective_sl = round(entry_price - effective_dist, 2)

        # 4. Post-calculation assertion: verify max loss doesn't exceed limit
        if self.safe_sl_mode:
            try:
                max_loss_check = (entry_price - effective_sl) * qty
                if max_loss_check > self.safe_sl_max_loss * 1.01:  # 1% tolerance for rounding
                    self.logger.error(
                        f"[SAFE_SL ASSERTION FAILED] {symbol}: "
                        f"effective_sl={effective_sl:.2f} gives max_loss=Rs.{max_loss_check:.1f} "
                        f"which exceeds safe_sl_max_loss=Rs.{self.safe_sl_max_loss}. "
                        f"Force-correcting."
                    )
                    corrected_dist = self.safe_sl_max_loss / qty
                    effective_sl = round(entry_price - corrected_dist, 2)
                    is_safe_applied = True
            except Exception as e:
                self.logger.error(
                    f"[SAFE_SL POST-ASSERT] Could not verify SL cap for {symbol}: {e}. "
                    f"effective_sl={effective_sl:.2f}. Proceeding with caution."
                )

        return effective_sl, is_safe_applied, raw_sl

    def consume_alert(self, symbol):
        """Manually consumes the alert for a symbol (e.g. after entry)."""
        if symbol in self.state:
            self.state[symbol]['alert'] = None
            self.state[symbol]['age'] = 0
            self.state[symbol]['alert_time'] = None

    def check_signal(self, symbol, current_candle, price_history=None, is_tradable=True, rsi_values=None, history_len=None):
        """
        Checks for signals based on candle and RSI.
        STRICTLY separates Alert and Entry.
        Entry cannot happen on the same candle as Alert.

        Args:
            symbol: Symbol identifier
            current_candle: The current candle row
            price_history: Pandas Series of closing prices ending with current_candle
            is_tradable: Boolean flag if we are inside trading window
            rsi_values: (current_rsi, prev_rsi) tuple - if provided, avoids re-calculation
            history_len: Integer length of history, avoids len(price_history) call if provided
        """
        if symbol not in self.state:
             self.state[symbol] = {
                 'alert': None,
                 'age': 0,
                 'alert_time': None,
                 'last_processed_time': None
             }

        state = self.state[symbol]
        signal = None

        current_time = current_candle['datetime']

        # Calculate RSI (gets both current and previous candle's RSI directly from array)
        if rsi_values is not None:
            current_rsi, prev_rsi = rsi_values
        else:
            # Fallback to slow calculation if no cached value provided
            rsi_result = self.calculate_latest_rsi(price_history, return_prev=True)
            # Skip if insufficient data
            if rsi_result is None or (isinstance(rsi_result, tuple) and rsi_result[0] is None):
                return None
            current_rsi, prev_rsi = rsi_result

        # Age Increment Logic
        # Increment on every NEW candle strictly after the alert — regardless of
        # trading window. This prevents alerts from freezing overnight and surviving
        # into the next session (AUDIT-015).
        expired_symbol = None  # Track if alert expired this cycle
        if state['alert'] is not None:
             if state['last_processed_time'] is not None and current_time > state['last_processed_time']:
                 # Check if we are strictly after alert_time
                 if current_time > state['alert_time']:
                     state['age'] += 1   # Always increment — do NOT gate on is_tradable
                     # Age 0: Alert Candle.
                     # Age 1: Candle T+1 (Valid).
                     # Age 2: Candle T+2 (Valid).
                     # Age 3: Candle T+3 (Expired, if alert_validity=2).
                     if state['age'] > self.alert_validity_candles:
                         self.logger.info(f"Alert expired for {symbol} at {current_time} (Age: {state['age']})")
                         expired_symbol = symbol
                         state['alert'] = None
                         state['age'] = 0
                         state['alert_time'] = None

        # Return EXPIRED signal if alert just expired
        if expired_symbol:
            return {'action': 'EXPIRED', 'symbol': expired_symbol}

        # Update processed time
        state['last_processed_time'] = current_time

        # 1. Check for Alert Negation & Entry
        if state['alert'] is not None:
            alert_candle = state['alert']

            # STEP 1: Negation check (price close below alert low)
            if self.alert_negation and current_time > state['alert_time'] and current_candle['close'] < alert_candle['low']:
                self.logger.info(
                    f"[{symbol}] Alert NEGATED: close={current_candle['close']:.2f} "
                    f"< alert_low={alert_candle['low']:.2f}"
                )
                state['alert'] = None
                state['age'] = 0
                state['alert_time'] = None
                return {'action': 'NEGATED', 'symbol': symbol}

            # STEP 2: Entry check (only if NOT negated)
            if current_time > state['alert_time'] and current_candle['high'] > alert_candle['high']:

                if state.get('_recovered_from_crash'):
                    alert_candle_dt = state['alert'].get('datetime')
                    if alert_candle_dt is not None:
                        if isinstance(alert_candle_dt, str):
                            from datetime import datetime
                            try:
                                alert_candle_dt = datetime.fromisoformat(alert_candle_dt)
                            except ValueError:
                                self.logger.error(
                                    f"[{symbol}] SAME-BAR GUARD: Failed to parse alert_candle_dt "
                                    f"'{alert_candle_dt}'. Blocking entry for safety."
                                )
                                state['_recovered_from_crash'] = False
                                return None   # fail-closed: do NOT allow entry

                        # Compare by candle bar (truncate to 15-min boundary)
                        def _bar(dt): return dt.replace(second=0, microsecond=0, minute=(dt.minute // 15) * 15)
                        if _bar(current_time) == _bar(alert_candle_dt):
                            self.logger.warning(f"[{symbol}] Blocking same-bar entry post crash-recovery")
                            return None
                    state['_recovered_from_crash'] = False  # clear after first safe check

                # ... breakout logic ...
                alert_range = alert_candle['high'] - alert_candle['low']

                # V16-P-01: Redundant guard for corrupt state
                if alert_range < self.min_alert_range:
                    self.logger.warning(f"[{symbol}] Entry rejected: corrupt alert_range ({alert_range:.2f})")
                    return None

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
            if history_len is None and price_history is not None:
                history_len = len(price_history)

            if history_len is not None:
                strict_min = max(self.min_candles_for_signal, self.rsi_period * 3)
                if history_len < strict_min:
                    if self.rsi_debug:
                        self.logger.debug(
                            f"[{symbol}] Insufficient history: {history_len} < {strict_min}"
                        )
                    return None

                # Log actual bars available per accepted symbol
                if self.rsi_debug:
                    self.logger.debug(f"[{symbol}] Admitted with {history_len} bars (min_req={strict_min})")

                # Warning for "Warmup Zone" (below 100 candles)
                if history_len < 100:
                    self.logger.debug(
                        f"[{symbol}] Low history ({history_len} candles). "
                        f"RSI may deviate from broker. Signal quality: CAUTION."
                    )

            is_green_candle = current_candle['close'] > current_candle['open']

            # DIAGNOSTIC: Log proximity to threshold if rsi_debug is on
            if self.rsi_debug and current_rsi is not None:
                if (self.rsi_threshold - 5) <= current_rsi < self.rsi_threshold:
                    self.logger.info(f"[{symbol}] RSI Proximity: {current_rsi:.2f} (Target: {self.rsi_threshold})")

            if is_green_candle and prev_rsi is not None and prev_rsi < self.rsi_threshold and current_rsi >= self.rsi_threshold:
                alert_candle = {
                    'high': current_candle['high'],
                    'low': current_candle['low'],
                    'datetime': current_candle['datetime']
                }

                # V16-P-01: Reject corrupt or flat candles (negative/tiny range)
                alert_range = alert_candle['high'] - alert_candle['low']
                if alert_range < self.min_alert_range:
                    self.logger.warning(
                        f"[{symbol}] Skipping alert: corrupt or flat candle "
                        f"(range={alert_range:.2f}, high={alert_candle['high']}, "
                        f"low={alert_candle['low']})"
                    )
                    return None

                # Calculate Effective SL (Base, Base + SAFE_SL, and Floor)
                effective_sl, is_safe_applied, raw_sl = self._calculate_effective_sl(symbol, alert_candle['high'], alert_candle['low'])

                state['alert'] = alert_candle
                state['age'] = 0
                state['alert_time'] = current_time
                self.logger.info(f"ALERT: RSI Breakout for {symbol} at {current_time} (RSI: {current_rsi:.2f})")

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
