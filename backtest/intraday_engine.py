# backtest/intraday_engine.py
import pandas as pd
import logging
import sys
import numpy as np
from math import ceil
from datetime import datetime, time, timedelta
from utils.nse_calendar import is_trading_day
from utils.symbol_parser import detect_underlying   # P-17: shared underlying detection
from utils.historical_lot_sizes import get_historical_lot_size
from execution.trade_tracker import TradeTracker

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
        """P-19: Get the latest candle at or before time t. O(log n) via searchsorted."""
        if df is None or df.empty:
            return None
        idx = df['datetime'].searchsorted(pd.Timestamp(t), side='right') - 1
        return None if idx < 0 else df.iloc[idx]

    def _get_closed_candle(self, df, bar_open_time):
        """Return the candle whose datetime == bar_open_time exactly.
        More robust than timestamp-offset hacks for 15m aligned data."""
        if df is None or df.empty:
            return None
        matches = df[df['datetime'] == pd.Timestamp(bar_open_time)]
        return matches.iloc[0] if not matches.empty else None

    def _round_to_tick(self, price, underlying):
        idx_cfg = self.config['indices'].get(underlying, {})
        tick_size = idx_cfg.get('tick_size', 0.05) if idx_cfg else 0.05
        return round(price / tick_size) * tick_size

    def _is_expiry_day(self, underlying: str, date) -> bool:
        """
        Check if date is an expiry day for the given underlying.
        Delegates to utils.expiry_calendar which has the full verified
        timeline from Jan 2020 to present (all NSE/BSE circular changes).
        """
        from utils.expiry_calendar import is_expiry_day
        return is_expiry_day(underlying, date)

    def run(self, start_date, end_date):
        self.logger.info(f"Starting backtest from {start_date} to {end_date}")
        self.capital = self.config['capital']['initial']
        self.trades = []

        trade_only_on_expiry = self.config['strategy'].get('trade_only_on_expiry', True)
        self.day_diagnostics = []  # V6-P-001: Store daily diagnostics

        # V6-P-001: Validate data paths once before starting the loop
        for idx in self.config['indices'].keys():
            self._validate_data_paths(idx, start_date)

            # P-17: Ensure index actually has historical data for this range
            import os, glob
            import re

            # Extract year range
            years_to_check = list(range(start_date.year, end_date.year + 1))
            total_files = 0

            idx_dir = os.path.join(self.dm.config['data']['storage_path'], 'derivatives', idx)
            if os.path.exists(idx_dir):
                for d in os.listdir(idx_dir):
                    subdir_path = os.path.join(idx_dir, d)
                    if not os.path.isdir(subdir_path):
                        continue

                    # Support BOTH year directories (e.g. "2024") and expiry directories (e.g. "2024-01-25")
                    m_year = re.match(r'^(\d{4})$', d)
                    m_expiry = re.match(r'^(\d{4})-\d{2}-\d{2}$', d)

                    year = None
                    if m_year:
                        year = int(m_year.group(1))
                    elif m_expiry:
                        year = int(m_expiry.group(1))

                    if year and year in years_to_check:
                        csvs = glob.glob(os.path.join(subdir_path, '*.csv'))
                        total_files += len(csvs)

            if total_files == 0:
                year_range = f"{start_date.year}-{end_date.year}"
                self.logger.error(
                    f"[DATA CHECK] {idx}: NO derivative data found for {year_range}. "
                    f"This index will generate ZERO trades. Remove from config or download data."
                )
            elif total_files < 50 * len(years_to_check):
                self.logger.warning(
                    f"[DATA CHECK] {idx}: Sparse data found ({total_files} files). Expected ~100+ per year."
                )

        current_date = start_date
        while current_date <= end_date:
            sys.stdout.write(f"\r[Backtest] Processing {current_date.date()} ... ")
            sys.stdout.flush()
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
                for idx in self.config['indices'].keys():
                    is_expiry = self._is_expiry_day(idx, current_date)
                    if is_expiry:
                        self.logger.info(f"EXPIRY DAY: {current_date.date()} is expiry for {idx}")
                        indices_to_trade.append(idx)
                        should_trade = True
            else:
                for idx in self.config['indices'].keys():
                    indices_to_trade.append(idx)
                should_trade = len(indices_to_trade) > 0

            if should_trade and indices_to_trade:
                self.logger.info(f"Processing {current_date.date()} - Trading {indices_to_trade}")
                self.current_day_pnl = 0  # Portfolio-wide daily PnL tracker
                for idx in indices_to_trade:
                    # [PORTFOLIO-STOP] Check if limit hit by previous indices today
                    if self.current_day_pnl <= -self.max_loss_per_day:
                        self.logger.warning(
                            f"🛑 Portfolio Daily loss limit reached ({self.current_day_pnl:.2f}). "
                            f"Skipping {idx} on {current_date.date()}."
                        )
                        continue
                    self.process_expiry_day(idx, current_date)
            else:
                self.logger.info(f"Skipping {current_date.date()} - No indices to trade")


            self.dm.clear_cache()
            current_date += pd.Timedelta(days=1)

        # V10: Post-backtest safe_sl compliance check
        if self.config['strategy'].get('safe_sl_mode', False):
            self._verify_safe_sl_compliance(self.trades)

        return self.generate_report()

    def print_diagnostic_summary(self):
        """V6-P-001: End-of-run diagnostic summary"""
        if hasattr(self, 'day_diagnostics') and self.day_diagnostics:
            days_no_data = sum(1 for d in self.day_diagnostics if d['opt_symbols_loaded'] == 0)
            days_no_alerts = sum(1 for d in self.day_diagnostics if d['alerts_fired'] == 0 and d['opt_symbols_loaded'] > 0)
            days_no_entries = sum(1 for d in self.day_diagnostics if d['alerts_fired'] > 0 and d['entries_attempted'] == 0)

            self.logger.info(
                f"\n{'='*60}\n"
                f"BACKTEST DIAGNOSTIC SUMMARY\n"
                f"{'='*60}\n"
                f"Days processed:          {len(self.day_diagnostics)}\n"
                f"Days with NO data:       {days_no_data}  <- (check symbol/path format)\n"
                f"Days with data, no RSI:  {days_no_alerts}  <- (RSI never crossed target)\n"
                f"Days with alert, no entry: {days_no_entries}  <- (validity window issue)\n"
                f"Total trades:            {len(self.trades)}\n"
                f"Final Capital:           {self.capital}\n"
                f"SENSEX pre-launch skips: {sum(1 for d in self.day_diagnostics if d['skip_reason'] == 'sensex_not_launched_yet')}\n"
                f"{'='*60}"
            )

    def _validate_data_paths(self, underlying: str, sample_date) -> None:
        """
        Check if a sample symbol can actually be found on disk.
        Logs a clear WARNING if build_option_symbol output doesn't match any files.
        """
        from datetime import timedelta
        import glob
        import os

        try:
            # Build a sample symbol for a recent date
            from datetime import date
            sample_expiry = sample_date.date() if hasattr(sample_date, 'date') else sample_date

            # Fix for false positives: SENSEX options didn't exist before May 15, 2023
            if underlying == 'SENSEX' and sample_expiry < date(2023, 5, 15):
                sample_expiry = date(2023, 5, 19)

            # Use index-appropriate sample strikes to avoid false mismatches
            sample_strike = 22500 if underlying == 'NIFTY' else 45000
            if underlying == 'SENSEX': sample_strike = 75000

            sample_symbol = self.dm.build_option_symbol(
                underlying, sample_expiry, sample_strike, 'CE', use_historical=True
            )

            # Check if the file exists
            year = sample_expiry.year
            expected_path = os.path.join(
                self.dm.base_path, 'derivatives', underlying,
                str(year), f"{sample_symbol}_15m.csv"
            )

            # Also check what actually exists in that directory
            dir_path = os.path.join(self.dm.base_path, 'derivatives', underlying, str(year))
            if os.path.exists(dir_path):
                existing = glob.glob(os.path.join(dir_path, "*.csv"))
                sample_existing = os.path.basename(existing[0]) if existing else "NONE (No CSV files found in directory)"
            else:
                sample_existing = f"DIRECTORY NOT FOUND: {dir_path}"

            if os.path.exists(expected_path):
                self.logger.info(f"[PATH CHECK] OK {underlying}: symbol format matches files on disk")
            else:
                self.logger.warning(
                    f"[PATH CHECK] WARNING {underlying}: FORMAT MISMATCH or missing dummy file\n"
                    f"  Generated: {sample_symbol}_15m.csv\n"
                    f"  On disk:   {sample_existing}\n"
                    f"  (This is often safely ignored if the sample strike didn't exist that year)"
                )
        except Exception as e:
            self.logger.warning(f"[PATH CHECK] Could not validate paths for {underlying}: {e}")

    def _is_option_data_tradeable(self, df, backtest_date, warmup_start):
        """
        V16-P-05: Data quality filter for option symbols.
        Returns (is_ok, reject_reason).
        """
        if df is None or df.empty:
            return False, 'empty_df'

        warmup_limit = self.config['strategy']['rsi'].get('warmup_periods', 100)
        min_limit = self.config['strategy']['rsi'].get('min_candles_for_signal', 33)
        n_bars = len(df)

        if n_bars < min_limit:
            return False, f'insufficient_bars_{n_bars}'

        if n_bars < warmup_limit + 1:
            # V16-P-07: Soft Accept with Warning
            return True, f'warning_warmup_only_{n_bars}_bars'

        # Check for data integrity (no high<low candles)
        try:
            bd = backtest_date.date() if hasattr(backtest_date, 'date') else backtest_date
            expiry_day_data = df[df['datetime'].dt.date == bd]
            if not expiry_day_data.empty:
                corrupt = (expiry_day_data['high'] < expiry_day_data['low']).sum()
                if corrupt > 0:
                    return False, f'corrupt_candles_{corrupt}'
        except Exception:
            pass

        return True, 'ok'

    def process_expiry_day(self, underlying, date):
        # V6-P-001: Diagnostic Tracking Dictionary
        diag = {
            'date': date.strftime('%Y-%m-%d'),
            'underlying': underlying,
            'opt_symbols_attempted': 0,
            'opt_symbols_loaded': 0,
            'opt_symbols_empty': 0,
            'timestamps_in_window': 0,
            'rsi_checks': 0,
            'alerts_fired': 0,
            'entries_attempted': 0,
            'trades_opened': 0,
            'skip_reason': None
        }

        from datetime import date as _date
        self.logger.info(f"Processing expiry day: {underlying} on {date.date()}")

        # SENSEX weekly options did not exist before May 2023
        SENSEX_WEEKLY_LAUNCH_DATE = _date(2023, 5, 1)
        if underlying == 'SENSEX':
            trade_date = date.date() if hasattr(date, 'date') else date
            if trade_date < SENSEX_WEEKLY_LAUNCH_DATE:
                self.logger.info(
                    f"Skipping SENSEX on {trade_date} - weekly options not yet launched "
                    f"(launched {SENSEX_WEEKLY_LAUNCH_DATE})"
                )
                diag['skip_reason'] = 'sensex_not_launched_yet'
                self._log_day_diagnostic(diag)
                return
        # Calculate RSI warmup dynamically from config
        period = self.config['strategy'].get('rsi', {}).get('period', 14)
        warmup_candles = self.config['strategy'].get('rsi', {}).get('warmup_periods', period * 2)
        min_candles = self.config['strategy']['rsi'].get('min_candles_for_signal', warmup_candles)
        required_candles = max(warmup_candles, min_candles)

        # Derive calendar days from candle count:
        # 375 trading minutes per day / 15 min per candle = 25 candles per day
        required_trading_days = ceil(required_candles * 15 / 375)
        # Buffer 2x for weekends/holidays
        calendar_buffer = max(required_trading_days * 2, 5)
        warmup_start = date - timedelta(days=calendar_buffer)
        self.logger.info(
            f"Warmup: fetching {required_trading_days} trading days "
            f"({required_candles} candles) | warmup_start: {warmup_start.date()}"
        )

        spot_df = self.dm.get_spot_candles(underlying, warmup_start, date.replace(hour=23, minute=59))
        if spot_df.empty:
            self.logger.warning(f"No spot data for {underlying} on {date.date()}")
            diag['skip_reason'] = 'no_spot_data'
            self._log_day_diagnostic(diag)
            return

        spot_df = spot_df.sort_values('datetime').reset_index(drop=True)

        start_datetime = datetime.combine(date.date(), self.start_time)
        start_row = self._get_latest_candle(spot_df, start_datetime)

        if start_row is None:
            self.logger.warning(f"No spot data available at start time {start_datetime} for {underlying}")
            diag['skip_reason'] = 'no_spot_data_at_start_time'
            self._log_day_diagnostic(diag)
            return

        universe_ref_price = start_row['open']

        strike_step = 50 if underlying == 'NIFTY' else 100
        if underlying == 'SENSEX': strike_step = 100

        strike_range = self.config['strategy'].get('strike_range', 4)  # default +/- 4
        center_strike = round(universe_ref_price / strike_step) * strike_step
        min_strike = center_strike - (strike_range * strike_step)
        max_strike = center_strike + (strike_range * strike_step)
        strikes = range(int(min_strike), int(max_strike) + strike_step, strike_step)

        option_data = {}
        for strike in strikes:
            for opt_type in ['CE', 'PE']:
                symbol = self.dm.build_option_symbol(underlying, date.date(), strike, opt_type, use_historical=True)  # Use historical expiry for backtests
                diag['opt_symbols_attempted'] += 1
                try:
                    # Fetch with warmup period
                    df = self.dm.get_derivative_candles(
                        underlying, symbol, date.year, warmup_start, date.replace(hour=23, minute=59)
                    )
                    if not df.empty:
                        df = df.sort_values('datetime').reset_index(drop=True)
                        # V16-P-05: Data quality filter
                        is_ok, reject_reason = self._is_option_data_tradeable(df, date, warmup_start)
                        if is_ok:
                            option_data[symbol] = df
                            diag['opt_symbols_loaded'] += 1
                            if reject_reason and 'warning' in reject_reason:
                                self.logger.warning(f"⚠️  [{symbol}] Limited warmup: {reject_reason}")
                        else:
                            diag['opt_symbols_filtered'] = diag.get('opt_symbols_filtered', 0) + 1
                            if self.config['strategy'].get('rsi_debug', False) or 'insufficient' in reject_reason:
                                self.logger.debug(f"Filtered {symbol}: {reject_reason}")
                    else:
                        diag['opt_symbols_empty'] += 1
                except Exception as e:
                    diag['opt_symbols_empty'] += 1
                    # Silently skip missing options (some strikes may not exist)
                    pass

        if not option_data:
            diag['skip_reason'] = 'no_option_data_loaded'
            self._log_day_diagnostic(diag)
            self.logger.warning("No option data loaded.")
            return

        strategy = self.strategy_cls(self.config)

        # Performance Upgrade: Pre-calculate RSI for all symbols at once
        # This converts a massive O(N^2) bottleneck into an O(N) operation.
        rsi_cache = {}
        for symbol, df in option_data.items():
            # Calculate the ENTIRE RSI series for this option's history including warmup
            # We use .values for the raw numpy array to bypass pandas overhead
            rsi_series = strategy.calculate_wilder_rsi(df['close'].values)
            if rsi_series is not None:
                rsi_cache[symbol] = rsi_series

        timestamps = sorted(spot_df['datetime'].unique())
        # CRITICAL FIX: Only process candles from the actual backtest date, not warmup period
        # This prevents signals from warmup days appearing in backtest results
        backtest_date = date.date()
        timestamps = [t for t in timestamps if t.date() == backtest_date and self.start_time <= t.time()]
        diag['timestamps_in_window'] = len(timestamps)

        active_trade = None
        has_traded_today = False
        # V20: Use portfolio-wide PnL tracker initialized in run()
        if not hasattr(self, 'current_day_pnl'):
            self.current_day_pnl = 0

        # V10-P-08: Circuit breaker tracking
        consecutive_losses = 0
        cooldown_candles_remaining = 0
        max_consec = self.config.get('risk', {}).get('max_consecutive_losses', 999)
        cooldown_n = self.config.get('risk', {}).get('consecutive_loss_cooldown', 0)

        # Debug counter
        debug_count = 0
        max_debug = 3
        self.logger.info(f"DEBUG: Found {len(timestamps)} timestamps to process for {backtest_date}")

        for t in timestamps:
            if t.time() >= self.sq_off_time:
                if active_trade:
                    pnl = self._close_trade(active_trade, t, "SQ_OFF", option_data)
                    self.current_day_pnl += pnl
                    self.trades.append(active_trade)
                    active_trade = None
                break

            current_spot_row = self._get_latest_candle(spot_df, t)
            if current_spot_row is None: continue
            current_spot_price = current_spot_row['close']

            # For direction filter: get the candle just before this one
            prev_spot_row = self._get_latest_candle(spot_df, t - timedelta(minutes=15))
            prev_spot_price = prev_spot_row['close'] if prev_spot_row is not None else None

            if active_trade:
                # ── 1. MANAGE SL / TP (Priority 1) ──────────────────────────
                trade_pnl_realized = self._manage_active_trade(active_trade, t, option_data)

                if active_trade['status'] == 'CLOSED':
                    self.trades.append(active_trade)
                    self.current_day_pnl += trade_pnl_realized
                    active_trade = None

                    # Hard stop for the day if daily limit hit by realized loss
                    if self.current_day_pnl <= -self.max_loss_per_day:
                        self.logger.warning(f"🛑 DAILY LOSS LIMIT REACHED (Realized): {self.current_day_pnl:.2f}. Done for today.")
                        break

                    # Track consecutive losses for circuit breaker
                    if trade_pnl_realized < 0:
                        consecutive_losses += 1
                        if consecutive_losses >= max_consec:
                            self.logger.info(f"[CIRCUIT BREAKER] {consecutive_losses} losses. Cooling off for {cooldown_n} candles.")
                            cooldown_candles_remaining = cooldown_n
                            consecutive_losses = 0
                    else:
                        consecutive_losses = 0

                # ── 2. PROACTIVE DAILY LOSS LIMIT (MTM) (Priority 2) ────────
                # If trade is still active, check if current unrealized loss breaches daily floor
                elif active_trade:
                    symbol = active_trade['symbol']
                    if symbol in option_data:
                        current_candle = self._get_latest_candle(option_data[symbol], t)
                        if current_candle is not None:
                            current_price = current_candle['open']
                            unrealized_pnl = (current_price - active_trade['entry_price']) * active_trade['remaining_qty']
                            total_pnl = self.current_day_pnl + unrealized_pnl + active_trade.get('partial_pnl', 0)

                            if total_pnl <= -self.max_loss_per_day:
                                self.logger.warning(
                                    f"🛑 DAILY LOSS LIMIT HIT (MTM): {total_pnl:.2f} <= -{self.max_loss_per_day}. "
                                    f"Squaring off {symbol} at candle open {current_price:.2f}"
                                )
                                trade_pnl_realized = self._close_trade(active_trade, t, "DAILY_LIMIT", option_data)
                                self.current_day_pnl += trade_pnl_realized
                                self.trades.append(active_trade)
                                active_trade = None
                                break # Stop trading for the day

            if active_trade: continue # Trade still active, skip new signal checks

            if has_traded_today: continue
            if self.current_day_pnl <= -self.max_loss_per_day: break
            if t.time() > self.end_time: continue

            # V10-P-08: Circuit breaker cooldown
            if cooldown_candles_remaining > 0:
                cooldown_candles_remaining -= 1
                continue  # Skip this candle, no new signals

            # V10-P-08: Hard stop if consecutive losses hit max with no cooldown
            if consecutive_losses >= max_consec and cooldown_n == 0:
                self.logger.info(f"[CIRCUIT BREAKER] {consecutive_losses} losses in a row. No new trades today.")
                break

            candidates = []

            for symbol, df in option_data.items():
                # Get the last CLOSED candle: the candle that opened 15m before t
                closed_candle_time = t - timedelta(minutes=15)
                row = self._get_closed_candle(df, closed_candle_time)
                if row is None:
                    # Fallback to searchsorted for non-aligned timestamps
                    row = self._get_latest_candle(df, t - timedelta(seconds=1))
                if row is None: continue

                # Issue 5: Duplicate Candle Check
                last_time = self.last_processed_candle_time.get(symbol)
                current_candle_time = row['datetime']

                if last_time and current_candle_time <= last_time:
                    continue

                self.last_processed_candle_time[symbol] = current_candle_time

                # Performance Upgrade: Use pre-calculated RSI values
                symbol_rsis = rsi_cache.get(symbol)
                if symbol_rsis is None: continue

                # RSI indexing rationale:
                # calculate_wilder_rsi(prices.values) returns rsi_values via np.diff,
                # so len(rsi_values) = len(prices) - 1.
                # rsi_values[i] uses close[0..i+1], i.e. prices up to DataFrame index i+1.
                # Therefore for candle at DataFrame position curr_idx:
                #   curr_rsi = rsi_values[curr_idx - 1]  (uses prices[0..curr_idx])
                #   prev_rsi = rsi_values[curr_idx - 2]  (uses prices[0..curr_idx-1])
                # This is correct: no look-ahead bias.
                curr_idx = row.name
                if curr_idx < 2 or curr_idx - 1 >= len(symbol_rsis): continue

                curr_rsi = symbol_rsis[curr_idx - 1]
                prev_rsi = symbol_rsis[curr_idx - 2]

                if np.isnan(curr_rsi): continue

                # Build price history up to current candle for min_candles check
                price_slice = df['close'].iloc[:curr_idx + 1]
                signal = strategy.check_signal(
                    symbol, row,
                    price_history=price_slice,
                    rsi_values=(curr_rsi, prev_rsi)
                )
                diag['rsi_checks'] += 1

                # Debug signal result
                if debug_count < max_debug and signal:
                    self.logger.info(f"DEBUG: {symbol} signal: {signal.get('action', 'None')}")

                if signal and signal['action'] == 'ALERT':
                    diag['alerts_fired'] += 1

                if signal and signal['action'] == 'ENTRY':
                    # Direction Filter Port from LiveTrader (Trend Following Guard)
                    if self.config['strategy'].get('direction_filter_enabled', False) and prev_spot_price is not None:
                         opt_type = symbol.split('-')[4]
                         if opt_type == 'CE' and current_spot_price < prev_spot_price:
                             continue
                         if opt_type == 'PE' and current_spot_price > prev_spot_price:
                             continue

                    parts = symbol.split('-')
                    try:
                        strike = float(parts[3])
                        dist = abs(strike - current_spot_price)
                        candidates.append({
                            'symbol': symbol,
                            'signal': signal,
                            'dist': dist,
                            'entry_candle_open': row.get('open', signal['price']),

                            'entry_candle_datetime': str(row['datetime'])
                        })
                    except (ValueError, IndexError) as e:
                        self.logger.warning(f"Symbol parse failed: {symbol} - {e}")

            if candidates:
                candidates.sort(key=lambda x: x['dist'])
                best = candidates[0]
                diag['entries_attempted'] += 1
                active_trade = self._enter_trade(best, t)
                if active_trade:
                    diag['trades_opened'] = 1
                    has_traded_today = True
                    strategy.consume_alert(active_trade['symbol'])

        self._log_day_diagnostic(diag)
        if hasattr(self, 'day_diagnostics'):
            self.day_diagnostics.append(diag)

    def _log_day_diagnostic(self, diag):
        self.logger.info(
            f"[DIAG] {diag['date']} {diag['underlying']} | "
            f"{'TRADE' if diag['trades_opened'] else 'NO TRADE'} | "
            f"data={diag['opt_symbols_loaded']}/{diag['opt_symbols_attempted']} "
            f"({diag['opt_symbols_empty']} empty, {diag.get('opt_symbols_filtered', 0)} filtered) | "
            f"ts={diag['timestamps_in_window']} | "
            f"rsi_checks={diag['rsi_checks']} | "
            f"alerts={diag['alerts_fired']} | "
            f"entries={diag['entries_attempted']}"
            + (f" | SKIP: {diag['skip_reason']}" if diag['skip_reason'] else "")
        )

    def _enter_trade(self, candidate, time):
        symbol = candidate['symbol']
        signal = candidate['signal']
        # P-17: use shared symbol parser (checks BANKNIFTY before NIFTY to avoid substring collision)
        underlying = detect_underlying(symbol)
        if underlying == 'UNKNOWN':
            self.logger.error(
                f"[CRITICAL] Cannot determine underlying for symbol: {symbol}. "
                f"Symbol format must contain BANKNIFTY, SENSEX, or NIFTY. "
                f"Trade SKIPPED to prevent incorrect lot sizing."
            )
            return None
        alert_high = signal['price']  # Intended trigger price
        entry_candle_open = candidate.get('entry_candle_open', alert_high)

        if entry_candle_open > alert_high:
            # Gap-up: SL-M fills at open price
            actual_fill = entry_candle_open
            slippage_pct = (actual_fill - alert_high) / alert_high
            max_slippage = self.config.get('risk', {}).get('max_slippage_pct', None)
            self.logger.info(
                f"Gap-fill simulation: trigger=Rs.{alert_high}, open=Rs.{entry_candle_open}, "
                f"fill=Rs.{actual_fill}, slippage={slippage_pct:.2%}"
            )
            if max_slippage is not None and slippage_pct > max_slippage:
                self.logger.warning(
                    f"ENTRY BLOCKED: Gap slippage {slippage_pct:.2%} > max_slippage_pct "
                    f"{max_slippage:.2%} for {symbol}. Trade skipped."
                )
                return None
        else:
            actual_fill = alert_high  # Normal fill at trigger

        price = self._round_to_tick(actual_fill, underlying)
        sl = self._round_to_tick(signal['sl'], underlying)
        targets = [self._round_to_tick(tgt, underlying) for tgt in signal['targets']]

        # Try historical lot size first (correct for backtesting)
        date_of_trade = time.date() if hasattr(time, 'date') else time
        try:
            lot_size = get_historical_lot_size(underlying, date_of_trade)
        except ValueError as e:
            self.logger.warning(
                f"Cannot determine lot size for {underlying} on {date_of_trade}: {e}. "
                f"Skipping trade."
            )
            return None
        except Exception as e:
            # Fallback to config if historical lookup fails unexpectedly
            lot_size = self.config['indices'].get(underlying, {}).get('lot_size')
            self.logger.warning(
                f"Historical lot size lookup failed for {underlying}: {e}. "
                f"Falling back to config value {lot_size}."
            )

        if not lot_size:
            self.logger.warning(f"No lot_size for {underlying} on {date_of_trade}. Skipping.")
            return None

        # Get lots_per_trade from config (for multi-lot mode)
        lots_per_trade = self.config['strategy'].get('lots_per_trade', 1)
        total_qty = lot_size * lots_per_trade

        # V10: CRITICAL FIX — Re-enforce safe_sl using ACTUAL historical qty
        # The strategy computed SL using config lot_size (e.g. 65), but the engine
        # trades historical lot_size (e.g. 75 for NIFTY in 2025). This mismatch
        # causes loss to exceed safe_sl_max_loss. Recalculate here with real qty.
        safe_sl_mode = self.config['strategy'].get('safe_sl_mode', False)
        safe_sl_max_loss = self.config['strategy'].get('safe_sl_max_loss', 5000)
        if safe_sl_mode and total_qty > 0:
            sl_dist = price - sl
            max_allowed_dist = safe_sl_max_loss / total_qty
            if sl_dist > max_allowed_dist:
                old_sl = sl
                sl = self._round_to_tick(price - max_allowed_dist, underlying)
                self.logger.info(
                    f"[SAFE_SL RECALC] {symbol}: historical qty={total_qty} "
                    f"(lot_size={lot_size}) differs from config. "
                    f"SL adjusted: {old_sl:.2f} -> {sl:.2f} "
                    f"(max_loss capped at Rs.{safe_sl_max_loss})"
                )

        cost = price * total_qty

        # FIX #3: Enforce max_position_pct config guard
        max_position_pct = self.config['strategy'].get('max_position_pct', 1.0)
        max_cost = self.capital * max_position_pct
        if cost > max_cost:
            self.logger.info(
                f"Skipping trade {symbol}: Position too large "
                f"({cost:.0f} > {max_position_pct*100:.0f}% of capital {max_cost:.0f})"
            )
            return None

        if self.capital < cost:
            self.logger.info(f"Skipping trade {symbol}: Insufficient capital ({self.capital} < {cost})")
            return None

        self.capital -= cost

        trade = {
            'symbol': symbol,
            'entry_time': time,
            'entry_candle_datetime': str(candidate.get('entry_candle_datetime', '')),
            'entry_price': price,
            'sl': sl,
            'targets': targets,
            'qty': total_qty,
            'remaining_qty': total_qty,  # Initialized here for MTM check
            'tp_hits': 0,
            'partial_pnl': 0,
            'status': 'OPEN',
            'pnl': 0,
            'cost': cost,
            'underlying': underlying,
            'lot_size': lot_size,
            'original_sl': sl,
            'alert_range': targets[0] - price if targets else 0,
            'running_capital': self.capital,
            'is_safe_sl_applied': (sl != signal.get('raw_sl', sl)) or (sl != self._round_to_tick(signal['sl'], underlying)),
            'raw_sl': signal.get('raw_sl', signal['sl'])
        }
        self.logger.info(
            f"ENTRY: {symbol} at {price} | Qty: {total_qty} "
            f"({lots_per_trade} lots * {lot_size} historical lot size on {date_of_trade}) "
            f"| Cost: {cost} | Cap: {self.capital}"
        )
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

        # CRITICAL FIX (V12-P-01): Define underlying from trade dict here so it is
        # available in BOTH multi-lot and single-lot branches below.
        underlying = trade.get('underlying', 'NIFTY')

        # V16-P-06: Management starts at T+2 by design (entry sets active_trade at the END
        # of the T+1 loop iteration, so management loop runs from T+2 onwards).
        # No same-candle SL risk exists in this architecture.

        realized_pnl = 0

        # Get exit mode from config
        exit_mode = self.config['strategy'].get('exit_mode', 'multi_lot')
        lots_per_trade = self.config['strategy'].get('lots_per_trade', 3)

        # Check SL condition (strategy-defined: alert candle low - 1)
        sl_triggered = row['low'] <= trade['sl']

        # V16-P-08: If SL has been trailed ABOVE entry (profitable trail),
        # check final target FIRST. Price must pass through target to hit
        # trailed SL from below, so TP takes priority.
        trailed_sl_above_entry = trade.get('sl', 0) > trade.get('entry_price', 0)
        exit_mode = self.config['strategy'].get('exit_mode', 'multi_lot')

        if trailed_sl_above_entry and sl_triggered:
            # Check if final target was ALSO hit on this candle
            if exit_mode == 'single_lot' or (exit_mode == 'multi_lot' and self.config['strategy'].get('lots_per_trade', 3) < 3):
                target_idx = self.config['strategy'].get('single_lot_exit_target', 2) - 1
                if row['high'] >= trade['targets'][target_idx]:
                    exit_price = max(row['open'], trade['targets'][target_idx])
                    pnl = (exit_price - trade['entry_price']) * trade['qty']
                    self.capital += exit_price * trade['qty']
                    trade['exit_time'] = time
                    trade['exit_price'] = exit_price
                    trade['reason'] = f'TP{target_idx+1}'
                    trade['status'] = 'CLOSED'
                    trade['pnl'] = pnl
                    trade['running_capital'] = self.capital
                    self.logger.info(
                        f"TP-BEFORE-SL (trailed): {symbol} at {exit_price:.2f} | "
                        f"SL was {trade['sl']:.2f} > entry {trade['entry_price']:.2f} | PnL: {pnl:.2f}"
                    )
                    return pnl

        if sl_triggered:
            # FIX #5: Gap-below-SL handling for ALL candles (not just 09:15)
            # If candle opens below SL (overnight gap OR intraday halt/circuit breaker),
            # the SL-M order fills at the open price (worse), not the SL price.
            candle_time = pd.Timestamp(row['datetime']).time()
            is_opening_candle = candle_time == pd.Timestamp('09:15').time()

            if row['open'] < trade['sl']:
                exit_price = row['open']
                if is_opening_candle:
                    self.logger.info(
                        f"OVERNIGHT GAP EXIT: {symbol} | "
                        f"SL={trade['sl']:.2f} but open={row['open']:.2f} "
                        f"(gap below SL). Exit at open."
                    )
                else:
                    self.logger.warning(
                        f"INTRADAY GAP-DOWN EXIT: {symbol} at {row['datetime']} | "
                        f"SL={trade['sl']:.2f} but open={row['open']:.2f} "
                        f"(possible halt/circuit breaker). Exit at open."
                    )
            else:
                # Normal: SL order fills AT the SL price.
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
            trade['running_capital'] = self.capital
            self.logger.info(f"EXIT SL: {symbol} at {exit_price:.2f} | Remaining Qty: {trade['remaining_qty']} | PnL: {realized_pnl:.2f}")
            return realized_pnl

        # V10-P-03: Sequential TP chain — handles single-candle multi-target fills
        # On expiry days, a single candle can spike from below T1 to above T3.
        # With limit sell orders at T1, T2, T3, all three fill in that candle.

        # Multi-lot mode: check each TP level sequentially
        if exit_mode == 'multi_lot' and lots_per_trade >= 3:
            underlying = trade.get('underlying', 'NIFTY')

            # Use lot_size stored in trade or look up historically
            if trade.get('lot_size'):
                lot_size = trade['lot_size']
            else:
                try:
                    entry_date = trade['entry_time'].date() if hasattr(trade['entry_time'], 'date') else trade['entry_time']
                    lot_size = get_historical_lot_size(underlying, entry_date)
                except Exception:
                    lot_size = self.config['indices'].get(underlying, {}).get('lot_size', 1)

            if lot_size == 1 and underlying not in ('UNKNOWN',):
                self.logger.warning(f"lot_size for {underlying} defaulted to 1 - check config.yaml or history")

            # Sequential loop through TP levels in one candle
            for tp_level in range(trade.get('tp_hits', 0), 3):
                target_price = trade['targets'][tp_level]

                if row['high'] < target_price:
                    break  # price didn't reach this TP, stop

                if tp_level < 2:
                    # Partial exit (TP1 or TP2)
                    exit_qty = lot_size
                    exit_price = max(row['open'], target_price)
                    pnl = (exit_price - trade['entry_price']) * exit_qty
                    trade['remaining_qty'] -= exit_qty
                    trade['partial_pnl'] = trade.get('partial_pnl', 0) + pnl
                    trade['tp_hits'] = tp_level + 1
                    # Trail SL — absolute prices to match live_trader._handle_tp_hit()
                    entry_price = trade['entry_price']
                    targets = trade['targets']
                    if tp_level == 0:  # TP1 hit: move SL to entry (break-even)
                        new_sl = self._round_to_tick(entry_price, underlying)
                    elif tp_level == 1:  # TP2 hit: move SL to TP1 price
                        new_sl = self._round_to_tick(targets[0], underlying)
                    else:
                        new_sl = trade['sl']  # No trail change at TP3 (full exit)
                    trade['sl'] = new_sl
                    self.capital += exit_price * exit_qty
                    self.logger.info(
                        f"PARTIAL EXIT TP{tp_level+1}: {symbol} | Qty: {exit_qty} | "
                        f"Price: {exit_price:.2f} | PnL: {pnl:.2f} | New SL: {new_sl:.2f}"
                    )
                else:
                    # TP3: final exit of remaining quantity
                    exit_qty = trade['remaining_qty']
                    exit_price = max(row['open'], target_price)
                    pnl = (exit_price - trade['entry_price']) * exit_qty
                    realized_pnl = pnl + trade.get('partial_pnl', 0)
                    self.capital += exit_price * exit_qty
                    trade['exit_time'] = time
                    trade['exit_price'] = exit_price
                    trade['reason'] = 'TARGET'
                    trade['status'] = 'CLOSED'
                    trade['pnl'] = realized_pnl
                    trade['remaining_qty'] = 0
                    trade['running_capital'] = self.capital
                    self.logger.info(
                        f"FINAL EXIT TP3: {symbol} at {exit_price:.2f} | Total PnL: {realized_pnl:.2f}"
                    )
                    return realized_pnl

        else:
            # Single lot mode (or multi_lot with insufficient lots)
            if exit_mode == 'multi_lot' and lots_per_trade < 3:
                self.logger.warning(
                    f"[CONFIG] exit_mode=multi_lot but lots_per_trade={lots_per_trade}. "
                    f"Treating as single_lot. Fix config.yaml."
                )
            # Single lot mode: trail SL at intermediate TPs, full exit at configured target
            target_idx = self.config['strategy'].get('single_lot_exit_target', 2) - 1

            # Sequential TP trail: process each intermediate TP in order,
            # even if price passed through multiple in the same candle
            for tp in range(trade.get('tp_hits', 0), target_idx):
                if row['high'] >= trade['targets'][tp]:
                    # Absolute trail: TP1 → break-even, TP2 → TP1 price
                    entry_price = trade['entry_price']
                    targets = trade['targets']
                    if tp == 0:   # TP1 hit
                        new_sl = self._round_to_tick(entry_price, underlying)
                    elif tp == 1:  # TP2 hit
                        new_sl = self._round_to_tick(targets[0], underlying)
                    else:
                        new_sl = trade['sl']
                    trade['sl'] = new_sl
                    trade['tp_hits'] = tp + 1
                    self.logger.info(
                        f"SINGLE_LOT TRAIL TP{tp+1}: {symbol} | "
                        f"price {row['high']:.2f} >= target {trade['targets'][tp]:.2f} | "
                        f"New SL: {new_sl:.2f}"
                    )
                else:
                    break  # price didn't reach this TP, stop checking

            # Now check if final configured target was breached
            if row['high'] >= trade['targets'][target_idx]:
                exit_price = max(row['open'], trade['targets'][target_idx])
                pnl = (exit_price - trade['entry_price']) * trade['qty']
                self.capital += exit_price * trade['qty']
                trade['exit_time'] = time
                trade['exit_price'] = exit_price
                trade['reason'] = f'TP{target_idx+1}'
                trade['status'] = 'CLOSED'
                trade['pnl'] = pnl
                trade['running_capital'] = self.capital
                self.logger.info(
                    f"EXIT TP{target_idx+1}: {symbol} at {exit_price:.2f} | PnL: {pnl:.2f}"
                )
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
        remaining = TradeTracker.get_remaining_qty(trade)
        partial_pnl = trade.get('partial_pnl', 0)
        credit = exit_price * remaining
        self.capital += credit
        pnl = (exit_price - trade['entry_price']) * remaining + partial_pnl

        trade['exit_time'] = time
        trade['exit_price'] = exit_price
        trade['reason'] = reason
        trade['status'] = 'CLOSED'
        trade['pnl'] = pnl
        trade['remaining_qty'] = 0  # Fully closed
        trade['running_capital'] = self.capital

        self.logger.info(f"EXIT: {symbol} at {exit_price} | Exited Qty: {remaining} | PnL: {pnl} | Reason: {reason}")
        return pnl

    def _verify_safe_sl_compliance(self, trades):
        """V10: Post-backtest check that no trade exceeded safe_sl_max_loss."""
        safe_sl_max = self.config['strategy'].get('safe_sl_max_loss', float('inf'))
        safe_sl_mode = self.config['strategy'].get('safe_sl_mode', False)

        if not safe_sl_mode or safe_sl_max == float('inf'):
            return

        breaches = []
        for trade in trades:
            gross_loss = trade.get('pnl', 0)
            if gross_loss < 0 and abs(gross_loss) > safe_sl_max * 1.1:  # 10% tolerance for rounding/gaps
                breaches.append({
                    'symbol': trade.get('symbol'),
                    'entry_time': trade.get('entry_time'),
                    'entry_price': trade.get('entry_price'),
                    'sl': trade.get('sl'),
                    'exit_price': trade.get('exit_price'),
                    'original_sl': trade.get('original_sl'),
                    'reason': trade.get('reason'),
                    'actual_loss': abs(gross_loss),
                    'limit': safe_sl_max,
                    'excess': abs(gross_loss) - safe_sl_max
                })

        losing_trades = [t for t in trades if t.get('pnl', 0) < 0]

        if breaches:
            self.logger.warning(
                f"\n{'='*60}\n"
                f"SAFE_SL COMPLIANCE CHECK: {len(breaches)} BREACH(ES) FOUND\n"
                f"{'='*60}"
            )
            for b in breaches:
                self.logger.warning(
                    f"  {b['symbol']} @ {b['entry_time']}: "
                    f"loss=Rs.{b['actual_loss']:.0f} > limit=Rs.{b['limit']} "
                    f"(excess: Rs.{b['excess']:.0f}) | "
                    f"entry={b['entry_price']}, sl={b['sl']}, exit={b['exit_price']}, "
                    f"orig_sl={b['original_sl']}, reason={b['reason']}"
                )
            self.logger.warning(
                f"Total breaches: {len(breaches)} out of {len(losing_trades)} losing trades.\n"
                f"{'='*60}"
            )
        else:
            self.logger.info(
                f"SAFE_SL COMPLIANCE: PASSED. All {len(losing_trades)} "
                f"losing trades respected Rs.{safe_sl_max} limit."
            )

    def generate_report(self):
        return pd.DataFrame(self.trades)
