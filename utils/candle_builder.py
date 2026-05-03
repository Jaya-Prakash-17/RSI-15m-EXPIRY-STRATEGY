import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import deque
import logging

class CandleBuilder:
    def __init__(self, interval_minutes=15, max_bars=150, enforce_timestamp=False):
        self.logger = logging.getLogger("CandleBuilder")
        self.interval_minutes = interval_minutes
        self.max_bars = max_bars
        self.enforce_timestamp = enforce_timestamp
        self.bars = {}  # symbol -> deque of closed bars
        self.active_candles = {}  # symbol -> forming candle dict
        self.continuity_broken = False
        self._continuity_broken_symbols = set()   # ADD: per-symbol tracking
        self._max_continuity_gap_minutes = 120  # ADD: gaps <= 120 min auto-recover (lunch, circuit)

    def _get_boundary_time(self, dt):
        """Align datetime to the start of the 15-minute interval."""
        if not dt:
            return None
        minutes = (dt.minute // self.interval_minutes) * self.interval_minutes
        return dt.replace(minute=minutes, second=0, microsecond=0)

    def _check_continuity(self, symbol, new_dt):
        """
        Validate that the new candle boundary follows the last one without gaps.
        Hard-gate: if gap > interval, set continuity_broken.
        """
        if symbol not in self.bars or not self.bars[symbol]:
            return True

        last_dt = self.bars[symbol][-1]['datetime']
        gap = (new_dt - last_dt).total_seconds()

        if gap > (self.interval_minutes * 60):
            gap_minutes = int(gap / 60)
            self.logger.critical(
                f"🚨 DATA CONTINUITY BROKEN for {symbol}: "
                f"Last bar {last_dt}, Current bar {new_dt}. "
                f"Missing {gap_minutes} minutes."
            )
            self._continuity_broken_symbols.add(symbol)
            # Auto-recover for short gaps (circuit breaker, lunch, brief outage)
            # Hard halt only for gaps that likely indicate data feed failure
            if gap_minutes > self._max_continuity_gap_minutes:
                self.continuity_broken = True   # hard halt: >2hr gap
            return False   # reject this bar; caller will warm_up on next candle

        # Gap is zero or one interval: clear per-symbol flag if previously broken
        if symbol in self._continuity_broken_symbols:
            self.logger.info(f"✅ Continuity restored for {symbol}")
            self._continuity_broken_symbols.discard(symbol)
            # Reset global flag if no symbols remain broken
            if not self._continuity_broken_symbols:
                self.continuity_broken = False

        # Also check for overlaps/duplicates if needed
        if new_dt <= last_dt:
            self.logger.warning(f"Duplicate or stale boundary received for {symbol}: {new_dt}")
            return False

        return True

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

        if self.enforce_timestamp and timestamp is None:
            raise ValueError(f"CandleBuilder: 'timestamp' is REQUIRED when enforce_timestamp=True (Symbol: {symbol})")

        now = timestamp or datetime.now()
        boundary = self._get_boundary_time(now)
        if not boundary:
            return None

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

                # [DATA-01] Bar Quality Guard
                ticks = candle['ticks']
                is_healthy = ticks >= 3  # Configurable threshold proxy

                closed_candle['is_healthy'] = is_healthy

                if not is_healthy:
                    self.logger.warning(
                        f"Thin bar detected for {symbol} at {closed_candle['datetime']}: "
                        f"only {ticks} ticks. Range: {closed_candle['high'] - closed_candle['low']:.2f}"
                    )

                # [CONT-01] Continuity Gate
                self._check_continuity(symbol, boundary)

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
