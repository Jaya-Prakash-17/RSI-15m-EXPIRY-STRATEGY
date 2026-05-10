# nifty_futures_rsi/strategy.py
"""
NIFTY Futures RSI-60 Breakout Strategy — Signal Generator

Signal Logic:
  - Timeframe: 15-minute candles on NIFTY Spot
  - Wait for RSI(14) to cross from below 60 to above 60
  - Alert candle must close above RSI-60 level
  - Entry: next candle must break alert candle's high
  - Stop Loss: alert_low - 1 point
  - Targets: T1 = high + 1×range, T2 = high + 2×range, T3 = high + 3×range
  - Trailing SL: after T1 → +1×range, after T2 → +1×range more
"""

import numpy as np
import logging
from datetime import datetime


class NiftyFuturesRSI60:
    def __init__(self, config):
        self.logger = logging.getLogger("NiftyFuturesRSI60")
        self.config = config

        rsi_cfg = config['strategy']['rsi']
        self.rsi_period = rsi_cfg['period']
        self.rsi_threshold = rsi_cfg.get('threshold', 60)
        self.warmup_periods = rsi_cfg.get('warmup_periods', self.rsi_period * 10)
        self.min_candles = rsi_cfg.get('min_candles_for_signal', self.rsi_period * 3)
        self.alert_validity = config['strategy'].get('alert_validity_candles', 1)

        self.signal_start = datetime.strptime(
            config['strategy'].get('signal_window_start', '09:45'), "%H:%M"
        ).time()
        self.signal_end = datetime.strptime(
            config['strategy'].get('signal_window_end', '14:45'), "%H:%M"
        ).time()

        self.rsi_debug = config['strategy'].get('rsi_debug', False)

        # State tracking
        self.alert = None       # The alert candle dict
        self.alert_age = 0      # Number of candles since alert
        self.alert_time = None  # Timestamp of alert candle
        self.last_processed = None

    def calculate_wilder_rsi(self, prices):
        """
        Wilder's RSI — vectorized via numpy.
        Returns array of RSI values (length = len(prices) - 1).
        RSI[i] uses close[0..i+1].
        """
        n = self.rsi_period
        close = np.asarray(prices, dtype=np.float64)

        if len(close) < n + 1:
            return None

        delta = np.diff(close)
        gains = np.where(delta > 0, delta, 0.0)
        losses = np.where(delta > 0, 0.0, -delta)

        # Seed with SMA of first N changes
        avg_gain = np.full(len(gains), np.nan)
        avg_loss = np.full(len(losses), np.nan)
        avg_gain[n - 1] = gains[:n].mean()
        avg_loss[n - 1] = losses[:n].mean()

        for i in range(n, len(gains)):
            avg_gain[i] = (avg_gain[i - 1] * (n - 1) + gains[i]) / n
            avg_loss[i] = (avg_loss[i - 1] * (n - 1) + losses[i]) / n

        with np.errstate(divide='ignore', invalid='ignore'):
            rs = np.where(avg_loss == 0, np.inf, avg_gain / avg_loss)
            rsi = np.where(avg_loss == 0, 100.0, 100.0 - 100.0 / (1.0 + rs))

        return rsi

    def check_alert(self, candle, curr_rsi, prev_rsi):
        """
        Check if the current candle qualifies as an RSI-60 crossover ALERT.

        Conditions:
          1. prev_rsi < threshold AND curr_rsi > threshold  (crossover)
          2. candle close > candle open (bullish close — implicit in RSI crossing up)
          3. Time is within signal window

        Returns alert dict or None.
        """
        candle_time = candle['datetime']
        t = candle_time.time() if hasattr(candle_time, 'time') else candle_time

        # Time filter
        if t < self.signal_start or t > self.signal_end:
            return None

        # RSI crossover: from below threshold to above
        if prev_rsi is None or np.isnan(prev_rsi):
            return None
        if curr_rsi is None or np.isnan(curr_rsi):
            return None

        threshold = self.rsi_threshold

        if prev_rsi < threshold and curr_rsi > threshold:
            # Alert candle must close above the open (bullish)
            if candle['close'] < candle['open']:
                self.logger.debug(
                    f"RSI crossed {threshold} but candle is bearish "
                    f"(O={candle['open']:.2f} C={candle['close']:.2f}). Skipping."
                )
                return None

            alert_high = candle['high']
            alert_low = candle['low']
            alert_range = alert_high - alert_low

            if alert_range <= 0:
                return None

            sl = alert_low - 1.0
            targets = [
                alert_high + 1 * alert_range,
                alert_high + 2 * alert_range,
                alert_high + 3 * alert_range,
            ]

            self.logger.info(
                f"[ALERT] RSI {prev_rsi:.1f} -> {curr_rsi:.1f} (crossed {threshold}) "
                f"| High={alert_high:.2f} Low={alert_low:.2f} Range={alert_range:.2f} "
                f"| SL={sl:.2f} | T1={targets[0]:.2f} T2={targets[1]:.2f} T3={targets[2]:.2f}"
            )

            return {
                'high': alert_high,
                'low': alert_low,
                'range': alert_range,
                'sl': sl,
                'targets': targets,
                'time': candle_time,
                'rsi': curr_rsi,
            }

        return None

    def check_entry(self, candle):
        """
        Check if the current candle triggers an ENTRY based on the active alert.

        Entry condition: candle high >= alert candle high (breakout).
        Entry price: alert candle high (SL-M trigger).

        Returns entry dict or None.
        """
        if self.alert is None:
            return None

        alert = self.alert

        # Entry: current candle must break alert high
        if candle['high'] >= alert['high']:
            entry_price = alert['high']

            self.logger.info(
                f"[ENTRY] Breakout above {entry_price:.2f} "
                f"(candle high={candle['high']:.2f}) "
                f"| SL={alert['sl']:.2f} | T1={alert['targets'][0]:.2f}"
            )

            return {
                'entry_price': entry_price,
                'sl': alert['sl'],
                'targets': alert['targets'],
                'alert_range': alert['range'],
                'alert_high': alert['high'],
                'alert_low': alert['low'],
            }

        return None

    def consume_alert(self):
        """Clear the alert after entry."""
        self.alert = None
        self.alert_age = 0
        self.alert_time = None

    def reset_for_day(self):
        """Reset state at the start of each trading day."""
        self.alert = None
        self.alert_age = 0
        self.alert_time = None
        self.last_processed = None
