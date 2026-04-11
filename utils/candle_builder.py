import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import deque
import logging

class CandleBuilder:
    def __init__(self, interval_minutes=15, max_bars=150):
        self.logger = logging.getLogger("CandleBuilder")
        self.interval_minutes = interval_minutes
        self.max_bars = max_bars
        self.bars = {}  # symbol -> deque of closed bars
        self.active_candles = {}  # symbol -> forming candle dict

    def _get_boundary_time(self, dt):
        """Align datetime to the start of the 15-minute interval."""
        minutes = (dt.minute // self.interval_minutes) * self.interval_minutes
        return dt.replace(minute=minutes, second=0, microsecond=0)

    def warm_up_from_df(self, symbol, df):
        """Seed the builder with historical candles to avoid cold RSI."""
        if df is None or df.empty:
            return

        if symbol not in self.bars:
            self.bars[symbol] = deque(maxlen=self.max_bars)

        # Efficiently avoid duplicates
        existing_times = {bar['datetime'] for bar in self.bars[symbol]}

        # Ensure we only take the last 'max_bars'
        records = df.tail(self.max_bars).to_dict('records')
        count = 0
        for rec in records:
            if rec['datetime'] not in existing_times:
                self.bars[symbol].append(rec)
                existing_times.add(rec['datetime'])
                count += 1

        if count > 0:
            self.logger.info(f"Warmed up {symbol} with {count} new bars (Total: {len(self.bars[symbol])})")

    def restore_state(self, symbol, bars_data):
        """
        Restore state from persisted JSON list of dicts.
        Converts datetime strings back to objects.
        """
        if not bars_data:
            return

        if symbol not in self.bars:
            self.bars[symbol] = deque(maxlen=self.max_bars)

        existing_times = {bar['datetime'] for bar in self.bars[symbol]}
        count = 0
        for bar in bars_data:
            if isinstance(bar.get('datetime'), str):
                bar['datetime'] = datetime.fromisoformat(bar['datetime'])

            if bar['datetime'] not in existing_times:
                self.bars[symbol].append(bar)
                existing_times.add(bar['datetime'])
                count += 1

        self.logger.info(f"Restored {count} unique bars for {symbol} (Total: {len(self.bars[symbol])})")

    def feed(self, symbol, ltp, timestamp=None):
        """
        Feed a new LTP tick.
        Returns the closed candle if a boundary was crossed, else None.
        """
        if ltp is None or ltp <= 0:
            return None

        now = timestamp or datetime.now()
        boundary = self._get_boundary_time(now)

        closed_candle = None

        if symbol not in self.active_candles:
            self.active_candles[symbol] = {
                'datetime': boundary,
                'open': ltp,
                'high': ltp,
                'low': ltp,
                'close': ltp,
                'volume': 0,  # Tick count/proxy
                'ticks': 1
            }
        else:
            candle = self.active_candles[symbol]

            # Check if we moved to a new interval
            if boundary > candle['datetime']:
                # Close current candle
                closed_candle = candle.copy()

                # Tick/Thin bar guard
                if closed_candle['ticks'] < 3:
                    self.logger.warning(
                        f"Thin bar detected for {symbol} at {closed_candle['datetime']}: "
                        f"only {closed_candle['ticks']} ticks. Range: {closed_candle['high'] - closed_candle['low']:.2f}"
                    )

                if symbol not in self.bars:
                    self.bars[symbol] = deque(maxlen=self.max_bars)
                self.bars[symbol].append(closed_candle)

                # Start new candle
                self.active_candles[symbol] = {
                    'datetime': boundary,
                    'open': ltp,
                    'high': ltp,
                    'low': ltp,
                    'close': ltp,
                    'volume': 0,
                    'ticks': 1
                }
            else:
                # Update forming candle
                candle['high'] = max(candle['high'], ltp)
                candle['low'] = min(candle['low'], ltp)
                candle['close'] = ltp
                candle['ticks'] += 1

        return closed_candle

    def get_closed_df(self, symbol):
        """Return the history of closed bars as a DataFrame."""
        if symbol not in self.bars or not self.bars[symbol]:
            return pd.DataFrame()

        df = pd.DataFrame(list(self.bars[symbol]))
        # Ensure column order matches strategy expectations
        cols = ['datetime', 'open', 'high', 'low', 'close', 'volume']
        return df[cols] if all(c in df.columns for c in cols) else df

    def get_history(self, symbol):
        """Return raw list of dicts for persistence."""
        if symbol not in self.bars:
            return []
        return list(self.bars[symbol])
