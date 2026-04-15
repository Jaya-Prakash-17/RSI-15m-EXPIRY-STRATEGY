# live/live_trader.py
import logging
import traceback
import pytz
import json
import time
import os
import tempfile
import pandas as pd
import numpy as np
from datetime import datetime, time as datetime_time, timedelta
from data.data_manager import DataManager
from execution.order_manager import OrderManager, is_order_filled
from execution.trade_tracker import TradeTracker
from strategy.expiry_rsi_breakout import ExpiryRSIBreakout
from core.groww_client import GrowwClient
from utils.trade_logger import TradeLogger
from utils.telegram_notifier import TelegramNotifier
from utils.symbol_parser import detect_underlying
from core.exceptions import InsufficientMarginError
from utils.expiry_calendar import get_expiry_for_date
from utils.candle_builder import CandleBuilder

IST = pytz.timezone('Asia/Kolkata')
MARKET_OPEN_IST = datetime_time(9, 15)    # 9:15 AM IST
MARKET_CLOSE_IST = datetime_time(15, 30)  # 3:30 PM IST

# Operational Kill Switch — Touch this file to force graceful shutdown
# e.g., touch /tmp/rsi_bot_kill (Linux) or %TEMP%\rsi_bot_kill (Windows)
KILL_SWITCH_FILE = os.path.join(tempfile.gettempdir(), 'rsi_bot_kill')

# ─── P-18: Named constants (no more magic numbers in loops) ──
MAIN_LOOP_SLEEP_SECONDS    = 1   # Main while-True polling cadence
POST_ORDER_FILL_WAIT_SECONDS = 3  # Wait after placing order before checking fill
SQOFF_RETRY_WAIT_SECONDS   = 5   # Tier-2 retry wait after SQ_OFF order
GAP_FILL_ABORT_PCT         = 0.04  # Abort trade if fill > trigger × (1 + this)
GAP_FILL_RECALC_PCT        = 0.02  # Recalculate SL/targets if fill > this
PAPER_GAP_THRESHOLD_PCT    = 0.02  # Gap simulation threshold in paper mode
LTP_CACHE_TTL_SECONDS      = 1     # Re-use LTP if fetched within last second

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
        self._halt_alert_sent: bool = False
        self.expiry_date = None
        self.underlying = None

        self.last_candle_time = None
        self.prev_closed_candle_time = None
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

        # V11: Circuit breaker state
        self.consecutive_losses = 0
        self.circuit_breaker_active = False

        # Strategy filters
        self.enable_direction_filter = config['strategy'].get('direction_filter_enabled', False)
        self.max_loss_per_day = config['risk']['max_loss_per_day']
        self.max_position_pct = config['risk'].get('max_position_pct', 0.20)
        self.logger.info(f"Position size cap: {self.max_position_pct*100:.0f}% of available balance")

        # P-08: Incremental candle cache — full download once, append-only after
        self._candle_cache: dict = {}   # symbol → pd.DataFrame

        # P-20: LTP TTL cache — avoids redundant API calls within 1s window
        self._ltp_cache: dict = {}      # symbol → (price, timestamp)

        # P-05: Market halt detection state
        self._market_halted: bool = False
        self._consecutive_halt_failures: int = 0
        self._halt_connectivity_alert_sent: bool = False
        self._halt_detected_at = None
        self._state_save_alert_sent: bool = False
        self._halt_alert_sent: bool = False

        # Trading window
        self.start_time = datetime.strptime(config['trading']['window']['start'], "%H:%M").time()
        self.end_time = datetime.strptime(config['trading']['window']['end'], "%H:%M").time()
        self.sq_off_time = datetime.strptime(config['trading']['window']['auto_square_off'], "%H:%M").time()

        # Configuration
        self.trade_only_on_expiry = config['strategy'].get('trade_only_on_expiry', True)

        # Candle Builder for local option candles (P-21)
        self.candle_builder = CandleBuilder(interval_minutes=15)
        self._pending_closed_bars = {}  # symbol -> bar dict

        # Hardening: LTP & Starvation trackers
        self._consecutive_ltp_failures = 0
        self._last_bar_close_time = datetime.now()
        self._starvation_alert_sent = False

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
        from utils.expiry_calendar import run_startup_assertions

        # P-08 / P-20: Clear memory caches from previous days to prevent leaks
        self._candle_cache.clear()
        self._ltp_cache.clear()
        self.last_processed_candle_time.clear()
        self.logger.info("Candle processing timestamps reset for new session.")

        try:
            run_startup_assertions()
            self.logger.info("✅ Expiry calendar assertions passed")
        except AssertionError as e:
            self.logger.critical(f"🚨 Expiry calendar broken: {e}")
            self.telegram._send_to_owner(f"🚨 <b>Expiry Calendar Assertion Failed</b>\n{e}\n<i>Do not trade until fixed.</i>")
            # Don't crash — let user decide if they want to stop, or if it's an old test breaking.

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
                # Cross-check calendar expiry with Groww API
                try:
                    # Direct check using GrowwClient on self
                    api_expiries = self.client.get_expiries(underlying)
                    today_str = datetime.now().strftime("%Y-%m-%d")

                    if api_expiries and today_str not in api_expiries:
                        self.logger.warning(
                            f"⚠️ CALENDAR CHECK: {underlying} calendar says expiry today "
                            f"but Groww API disagrees. API expiries: {api_expiries[:3]}"
                        )
                        self.telegram._send_to_owner(
                            f"⚠️ <b>Expiry Calendar Mismatch</b>\n"
                            f"{underlying}: Calendar expects expiry today, but API disagrees.\n"
                            f"Verify before trading."
                        )
                    else:
                        self.logger.info(f"✅ Calendar verified for {underlying}")
                except Exception as e:
                    self.logger.warning(f"Could not verify {underlying} expiry with API: {e}")

            self.spot_symbols[underlying] = underlying
            self.tracked_options[underlying] = {}  # Nested dict: {underlying: {symbol: df}}

        # Reconcile positions on startup BEFORE clearing day data
        # MUST run first so any crashed/open trades from yesterday are detected
        # and checked before being blindly moved to 'EXPIRED'.
        self._reconcile_positions()

        # Clear stale data from previous sessions to keep bot_trades.json lean
        self.tracker.clear_day_data()
        self.tracker.trim_old_closed_trades(keep_days=30)
        self.logger.info("Session data cleared: previous day's trades archived")

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
            # Restore strategy state
            try:
                import os, json
                filepath = 'data/strategy_state.json'
                if os.path.exists(filepath):
                    with open(filepath) as f:
                        saved_state = json.load(f)
                    self.strategy.import_state(saved_state)
                    self.logger.info(f"Restored strategy state for {len(saved_state)} symbols")
                    os.remove(filepath)  # clear after restore
            except Exception as e:
                self.logger.warning(f"Could not restore strategy state: {e}")

            # Verify tracked active trades
            active_trades = self.tracker.get_active_trades()

            if active_trades:
                self.logger.warning(f"Found {len(active_trades)} active trades from previous session:")
                for trade in active_trades:
                    symbol = trade['symbol']
                    self.logger.warning(f"  - {symbol} | Qty: {TradeTracker.get_remaining_qty(trade)} | Entry: {trade['entry_price']}")

                    # Verify if position still exists (using LTP as a proxy for symbol validity)
                    # If LTP exists, the option is not expired/delisted.
                    try:
                        ltp = self.client.get_ltp(symbol)
                        if ltp is not None:
                            self.logger.critical(f"🚨 ACTIVE POSITION CARRIED OVER: {symbol} @ LTP {ltp}. Resuming monitor.")
                            self.telegram._send_to_owner(
                                f"🚨 <b>STALE POSITION RECOVERED</b>\n"
                                f"Symbol: <code>{symbol}</code>\n"
                                f"Bot crashed mid-trade previously.\n"
                                f"Resuming tracking. Check Groww app."
                            )
                        else:
                            self.logger.info(f"Symbol {symbol} delisted/expired. Closing stale trade.")
                            self.tracker.close_trade(trade['trade_id'], float(trade['entry_price']), "STALE_RECOVERY", 0)
                    except Exception as e:
                        self.logger.error(f"Error checking LTP for stale trade {symbol}: {e}")

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
        """P-19: Get the latest candle at or before time t. O(log n) via searchsorted."""
        if df is None or df.empty:
            return None
        idx = df['datetime'].searchsorted(pd.Timestamp(t), side='right') - 1
        return None if idx < 0 else df.iloc[idx]

    def _get_ltp_cached(self, symbol: str):
        """P-20: Return LTP from 1-second TTL cache, or fetch fresh from broker."""
        now = datetime.now()
        cached = self._ltp_cache.get(symbol)
        if cached:
            price, ts = cached
            if (now - ts).total_seconds() < LTP_CACHE_TTL_SECONDS:
                return price
        price = self.client.get_ltp(symbol)
        if price is not None:
            self._ltp_cache[symbol] = (price, now)
        return price

    def _get_candles_incremental(
        self, underlying: str, symbol: str, year: int,
        warmup_start, now, is_spot=False
    ):
        """P-08: Full download on first call; incremental thereafter."""
        if symbol not in self._candle_cache or self._candle_cache[symbol].empty:
            if is_spot:
                df = self.dm.get_spot_candles(symbol, warmup_start, now, refresh=True)
            else:
                df = self.dm.get_derivative_candles(
                    underlying, symbol, year, warmup_start, now, refresh=True
                )
            self._candle_cache[symbol] = df
            return df

        cached = self._candle_cache[symbol]
        last_known = cached['datetime'].max()

        if is_spot:
            new_df = self.dm.get_spot_candles(symbol, last_known, now, refresh=True)
        else:
            new_df = self.dm.get_derivative_candles(
                underlying, symbol, year, last_known, now, refresh=True
            )

        if not new_df.empty:
            combined = pd.concat([cached, new_df]).drop_duplicates(subset=['datetime'])
            combined = combined.sort_values('datetime').reset_index(drop=True)
            max_rows = max(200, self.strategy.rsi_warmup + 50)
            if len(combined) > max_rows:
                combined = combined.tail(max_rows).reset_index(drop=True)
            self._candle_cache[symbol] = combined

        return self._candle_cache[symbol]

    def _is_market_open(self) -> bool:
        """P-05: Proxy check using NIFTY LTP. Returns False if market appears halted."""
        try:
            ltp = self.client.get_ltp('NIFTY')
            if ltp is not None and ltp > 0:
                self._consecutive_halt_failures = 0
                self._halt_connectivity_alert_sent = False
                return True
            self._consecutive_halt_failures += 1
        except Exception:
            self._consecutive_halt_failures += 1
        if self._consecutive_halt_failures >= 5 and not self._halt_connectivity_alert_sent:
            self.telegram._send_to_owner("⚠️ API connectivity issue: 5 consecutive NIFTY LTP failures. Check connection.")
            self._halt_connectivity_alert_sent = True
        return self._consecutive_halt_failures < 5

    def _check_correlation_limit(self, opt_type: str, underlying: str) -> bool:
        """P-09: Returns True if trade allowed, False if would over-concentrate direction."""
        max_same_dir = self.config['strategy'].get('max_correlated_positions', 1)
        active = self.tracker.get_active_trades()
        same_direction = sum(
            1 for t in active
            if t.get('opt_type') == opt_type
            and t.get('underlying') != underlying
        )
        if same_direction >= max_same_dir:
            self.logger.info(
                f"[{underlying}] Skipping {opt_type}: already {same_direction} "
                f"{opt_type} on other index (correlation limit={max_same_dir})."
            )
            return False
        return True

    def _get_warmup_start_time(self):
        """Calculate start time for RSI warmup period, factoring in weekends and holidays."""
        warmup_candles = self.strategy.rsi_warmup

        # 1 day = ~25 candles (6.25 hrs).
        # Add 3 days for weekend + minimum 1-2 days holidays buffer
        days_back = max(7, (warmup_candles // 25) + 4)

        # Start from market open today
        now = datetime.now()
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)

        # Go back safely across weekends and holidays
        warmup_start = market_open - timedelta(days=days_back)

        self.logger.info(f"RSI warmup requires {warmup_candles} candles. Fetching {days_back} calendar days back from {warmup_start}")

        return warmup_start

    def _update_option_universe(self, warmup_start=None):
        """Update tracked option universe based on current spot price for ALL indices."""
        now = datetime.now()
        if warmup_start is None:
            warmup_start = self._get_warmup_start_time()

        for underlying in self.underlyings:
            spot_symbol = self.spot_symbols.get(underlying, underlying)
            expiry_date = self.expiry_dates.get(underlying, datetime.now().date())

            try:
                # V16-BUG-002: Use refresh=True ONLY on the first underlying or a global sync
                # Passing refresh=True on every call re-parses CSV and checks gaps unnecessarily.
                spot_df = self.dm.get_spot_candles(spot_symbol, warmup_start, now, refresh=(underlying == self.underlyings[0]))
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
            strike_range = self.config['strategy'].get('strike_range', 4)
            strikes = [
                center_strike + (i * strike_gap)
                for i in range(-strike_range, strike_range + 1)
            ]

            for strike in strikes:
                for opt_type in ['CE', 'PE']:
                    symbol = self.dm.build_option_symbol(underlying, expiry_date, strike, opt_type)

                    # Ensure nested dict structure
                    if underlying not in self.tracked_options:
                        self.tracked_options[underlying] = {}

                    if symbol not in self.tracked_options[underlying]:
                        # Issue #8: Minimum Volume Filter
                        # We only add to tracking if the option has sufficient volume
                        # or if we're doing initial discovery. For now, we add everything
                        # but check volume during signal generation.
                        self.logger.info(f"Adding {symbol} to tracking for {underlying}.")
                        self.tracked_options[underlying][symbol] = pd.DataFrame()

                        # Warm up local candle builder with Gap Filling (Phase 2 Refinement)
                        try:
                            cached_bars = self.tracker.load_candle_state(symbol)
                            last_cached_time = warmup_start

                            if cached_bars:
                                self.logger.info(f"Restoring {len(cached_bars)} bars from candle cache for {symbol}")
                                self.candle_builder.restore_state(symbol, cached_bars)
                                # Infer last time to fetch gap
                                last_dt_str = cached_bars[-1].get('datetime')
                                if last_dt_str:
                                    try:
                                        last_cached_time = datetime.fromisoformat(last_dt_str).replace(tzinfo=None)
                                    except:
                                        pass

                            # Always fetch the gap from last known bar to NOW
                            # If no cache, last_cached_time is warmup_start (full download)
                            # If cache is old, this fetches everything in between.
                            if (now - last_cached_time).total_seconds() > (self.candle_builder.interval_minutes * 60):
                                self.logger.info(f"Filling candle gap for {symbol} from {last_cached_time} to {now}")
                                hist_df = self.dm.get_derivative_candles(
                                    underlying, symbol, now.year, last_cached_time, now, refresh=False
                                )
                                if not hist_df.empty:
                                    self.candle_builder.warm_up_from_df(symbol, hist_df)
                            else:
                                self.logger.debug(f"No gap filling required for {symbol} (last update: {last_cached_time})")

                        except Exception as e:
                            self.logger.warning(f"Warmup/Restore failed for {symbol}: {e}")

    def _poll_candle_close(self, warmup_start=None):
        """Poll latest spot candle to detect 15-min period close."""
        if warmup_start is None:
            warmup_start = self._get_warmup_start_time()

        now = datetime.now()
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
                self.prev_closed_candle_time = self.last_candle_time  # save closed time
                self.last_candle_time = latest_candle_time
                self.logger.info(
                    f"Candle closed: {self.prev_closed_candle_time} | "
                    f"New forming: {self.last_candle_time}"
                )
                return True
        except Exception as e:
            self.logger.error(f"Error polling candle: {e}")
        return False

    def _poll_option_ltps(self):
        """
        Poll LTP for all tracked options in batch and feed to CandleBuilder.
        Throttled to run every ~2 seconds in main loop.
        """
        from core.exceptions import RateLimitExceededError

        for underlying in self.underlyings:
            symbols = list(self.tracked_options.get(underlying, {}).keys())
            if not symbols:
                continue

            try:
                # BATCH LTP POLLING (Hardening Step 1)
                batch_results = self.client.get_batch_ltp(symbols)
                self._consecutive_ltp_failures = 0  # reset on successful batch call

                for symbol, ltp in batch_results.items():
                    if ltp:
                        closed_bar = self.candle_builder.feed(symbol, ltp)
                        if closed_bar:
                            self._pending_closed_bars[symbol] = closed_bar
                            self.logger.debug(f"Local bar closed for {symbol} at {closed_bar['datetime']}")

                            # Starvation tracking: update last closure time
                            self._last_bar_close_time = datetime.now()
                            self._starvation_alert_sent = False

                            # Save state immediately on closure (Phase 2 atomic persistence)
                            self.tracker.save_candle_state(symbol, self.candle_builder.get_history(symbol))

                # Update LTP cache for other methods to use
                now = datetime.now()
                for symbol, ltp in batch_results.items():
                    if ltp:
                        self._ltp_cache[symbol] = (ltp, now)

            except RateLimitExceededError as e:
                self._consecutive_ltp_failures += 1
                self.logger.critical(f"LTP POLLING HALTED: {e}")
                if self._consecutive_ltp_failures == 1: # only alert once per burst
                    self.telegram._send_to_owner(f"🚨 <b>Rate Limit Exceeded</b>\nLTP polling paused. Retrying with backoff.")
                return # skip this poll tick
            except Exception as e:
                self.logger.error(f"Error in batch LTP polling: {e}")

    def _round_to_tick(self, price, underlying=None):
        """Round price to tick size for given underlying."""
        if underlying is None:
            underlying = self.underlyings[0] if self.underlyings else 'NIFTY'
        tick_size = self.config['indices'].get(underlying, {}).get('tick_size', 0.05)
        return round(price / tick_size) * tick_size

    def _get_unrealized_pnl(self) -> float:
        """
        Calculates the total unrealized P&L of all currently open trades.
        Uses LTP TTL cache (P-20) to avoid redundant API calls within same second.
        """
        total_unrealized = 0.0
        active_trades = self.tracker.get_active_trades()
        for trade in active_trades:
            ltp = self._get_ltp_cached(trade.get('symbol', ''))  # P-20 cached
            if ltp and ltp > 0:
                remaining_qty = TradeTracker.get_remaining_qty(trade)
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

    def _process_strategy_logic(self, warmup_start=None):
        """Process strategy logic for all tracked options across ALL indices.

        Handles:
        - ALERT: Places pending SL-M BUY order
        - NEGATED/EXPIRED: Cancels pending entry order
        - ENTRY: For backward compatibility (breakout already happened)
        """
        if warmup_start is None:
            warmup_start = self._get_warmup_start_time()
        # V11-P-02: Circuit breaker gate
        if self.circuit_breaker_active:
            self.logger.info("[CIRCUIT BREAKER] Active — skipping signal scan for all indices")
            return

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
            spot_df = pd.DataFrame()  # RESET: prevent cross-contamination from previous iteration
            spot_price = 0

            spot_symbol = self.spot_symbols.get(underlying, underlying)
            expiry_date = self.expiry_dates.get(underlying, datetime.now().date())

            # Get spot price for this underlying
            try:
                spot_df = self.dm.get_spot_candles(spot_symbol, warmup_start, now, refresh=False)
            except Exception as e:
                self.logger.error(f"Failed to fetch spot data for {underlying}: {e}")

            # Validate before use — skip this underlying if spot data is unavailable
            if spot_df is None or spot_df.empty:
                self.logger.warning(f"Spot data empty for {underlying}. Skipping.")
                continue

            if 'datetime' not in spot_df.columns:
                self.logger.warning(f"Spot data for {underlying} missing 'datetime' column. Skipping.")
                continue

            try:
                current_spot_row = self._get_latest_candle(spot_df, now)
                if current_spot_row is not None:
                    spot_price = current_spot_row['close']
            except Exception as e:
                self.logger.warning(f"Could not extract spot price for {underlying}: {e}")

            # Get tracked options for this underlying
            if underlying not in self.tracked_options:
                continue

            # ── VECTORIZED LIVE PULSE ──────────────────────────────────────
            # Phase 1: Collect candle data and close arrays for all symbols
            symbol_candle_data = {}   # {symbol: (df, last_row, current_candle_time)}
            symbols_closes = {}       # {symbol: np.array of close prices}

            if self.prev_closed_candle_time:
                closed_candle_cutoff = self.prev_closed_candle_time + timedelta(seconds=30)
            elif self.last_candle_time:
                closed_candle_cutoff = self.last_candle_time - timedelta(seconds=1)
            else:
                closed_candle_cutoff = now - timedelta(minutes=15)

            for symbol in list(self.tracked_options[underlying].keys()):
                try:
                    # REPLACE API FETCH WITH LOCAL CANDLE BUILDER (P-21)
                    df = self.candle_builder.get_closed_df(symbol)
                    if df.empty:
                        continue

                    last_row_data = df.iloc[-1].to_dict()
                    last_row = pd.Series(last_row_data)

                    # Thin Bar Guard
                    min_range = self.config['strategy'].get('min_alert_range_points', 0)
                    if (last_row.get('high', 0) - last_row.get('low', 0)) < min_range:
                        self.logger.debug(f"[{symbol}] Skipping: thin bar range < {min_range}")
                        continue

                    current_candle_time = last_row['datetime']

                    # Prevent duplicate processing
                    last_processed = self.last_processed_candle_time.get(symbol)
                    if last_processed and current_candle_time <= last_processed:
                        continue

                    self.tracked_options[underlying][symbol] = df

                    # RSI calculation from builder close series
                    close_arr = df['close'].values

                    symbol_candle_data[symbol] = (df, last_row, current_candle_time)
                    symbols_closes[symbol] = close_arr

                except Exception as e:
                    self.logger.error(f"Error collecting data for {symbol}: {e}")

            # Phase 2: Batch RSI computation (single call for ALL symbols)
            if symbols_closes:
                batch_rsi = self.strategy.batch_calculate_rsi(symbols_closes)
            else:
                batch_rsi = {}

            # Phase 3: Signal checking with pre-computed RSI values
            for symbol, (df, last_row, current_candle_time) in symbol_candle_data.items():
                try:
                    rsi_pair = batch_rsi.get(symbol, (None, None))

                    self.logger.debug(
                        f"[{symbol}] RSI check on CLOSED candle: "
                        f"{last_row['datetime'].strftime('%H:%M')} "
                        f"H={last_row['high']:.2f} L={last_row['low']:.2f} "
                        f"range={last_row['high']-last_row['low']:.2f} "
                        f"RSI={rsi_pair[0]:.2f}" if rsi_pair[0] else
                        f"[{symbol}] RSI=None (insufficient data)"
                    )

                    self.last_processed_candle_time[symbol] = current_candle_time

                    signal = self.strategy.check_signal(
                        symbol, last_row,
                        price_history=None,      # Not needed when rsi_values provided
                        is_tradable=is_tradable,
                        rsi_values=rsi_pair       # Pre-computed (current, prev)
                    )

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
                                    from datetime import date
                                    today = datetime.now().date()
                                    today_spot = spot_df[spot_df['datetime'].dt.date == today]
                                    if len(today_spot) < 2:
                                        self.logger.debug(f"[{symbol}] Direction filter: insufficient today candles ({len(today_spot)}). Skipping filter.")
                                    else:
                                        prev_spot = today_spot.iloc[-2]['close']
                                        curr_spot = today_spot.iloc[-1]['close']
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
                    alert_validity_candles=self.config['strategy'].get('alert_validity', 1),
                    is_safe_sl_applied=signal.get('is_safe_sl_applied', False),
                    raw_sl=signal.get('raw_sl')
                )

                # Log other candidates for this index (if any)
                if len(candidates) > 1:
                    others = [c['symbol'] for c in candidates[1:]]
                    self.logger.info(f"[{index_name}] Other candidates for index (not selected): {others}")

                self._place_pending_entry(best)

    def _cancel_pending_entry(self, symbol, reason):
        """Cancel a pending entry order when alert is negated or expired.

        Guards against the race condition where the SL-M order filled between
        the alert candle and the negation candle (AUDIT-016): checks fill status
        first and activates the trade instead of silently orphaning a live position.
        """
        if symbol not in self.pending_entries:
            return

        pending = self.pending_entries[symbol]
        order_id = pending.get('order_id')

        # For real orders only: check fill status BEFORE attempting cancel
        if order_id and not (self.paper_trading and order_id.startswith('PAPER_')):
            try:
                status = self.client.get_order_status(order_id)
                if status and is_order_filled(status.get('status', '')):
                    # Order already filled — activate trade instead of cancelling
                    fill_price = status.get('fill_price') or pending['trigger_price']
                    self.logger.warning(
                        f"⚠️ Alert {reason} but order {order_id} already filled "
                        f"at ₹{fill_price}. Activating trade despite negation."
                    )
                    self.telegram._send_to_owner(
                        f"⚠️ <b>Alert Negated But Order Already Filled</b>\n"
                        f"Symbol: <code>{symbol}</code>\n"
                        f"Fill: ₹{fill_price} | Reason: {reason}\n"
                        f"Trade activated — monitor closely."
                    )
                    self._activate_trade_from_pending(pending, fill_price=float(fill_price))
                    del self.pending_entries[symbol]
                    self.tracker.save_pending_entries(self.pending_entries)
                    self._save_strategy_state()
                    return
            except Exception as e:
                self.logger.error(f"Error checking order status before cancel: {e}")

        # Proceed with cancellation
        if order_id:
            self.logger.info(f"🚫 Canceling pending entry order {order_id} for {symbol} - {reason}")
            try:
                result = self.om.cancel_order(order_id)
                if result:
                    self.logger.info(f"✓ Pending order {order_id} cancelled successfully")
                else:
                    # Cancel failed — keep in pending_entries to avoid orphaning a position
                    self.logger.warning(
                        f"⚠️ Failed to cancel pending order {order_id}. "
                        f"Keeping {symbol} in monitoring."
                    )
                    # Telegram alert: trader must know this — cancel fail leaves
                    # a live SL-M order at the broker that may still fill
                    self.telegram._send(
                        f"⚠️ <b>Cancel Order Failed</b>\n"
                        f"Symbol: <code>{symbol}</code>\n"
                        f"Order: {order_id}\n"
                        f"Reason: {reason}\n"
                        f"The SL-M entry order is still live at Groww.\n"
                        f"If price hits ₹{pending.get('trigger_price', '?')}, "
                        f"the trade will activate automatically.\n"
                        f"Monitor closely or cancel manually in Groww app."
                    )
                    return  # DO NOT delete — continue monitoring this symbol
            except Exception as e:
                self.logger.error(f"Error canceling pending order: {e}")
                return  # DO NOT delete on exception either

        # Safe to remove from tracking
        del self.pending_entries[symbol]
        self.tracker.save_pending_entries(self.pending_entries)
        self._save_strategy_state()

        # Telegram: notify that setup expired/was negated
        if reason == 'EXPIRED':
            underlying = pending.get('underlying', '')
            strike = pending.get('strike', 0)
            opt_type = pending.get('opt_type', '')
            self.telegram.alert_expired(symbol, underlying, strike, opt_type, pending.get('trigger_price', 0))

    def _save_strategy_state(self):
        filepath = 'data/strategy_state.json'
        dir_name = os.path.dirname(os.path.abspath(filepath))
        temp_path = None
        try:
            import json
            state = self.strategy.export_state()
            with tempfile.NamedTemporaryFile(
                mode='w', dir=dir_name, delete=False, suffix='.tmp'
            ) as tf:
                json.dump(state, tf, indent=2, default=str)
                temp_path = tf.name
            os.replace(temp_path, filepath)
        except Exception as e:
            self.logger.warning(f"Could not save strategy state: {e}")
            if not getattr(self, '_state_save_alert_sent', False):
                self.telegram._send_to_owner(f"⚠️ Strategy state WRITE FAILED: {e}. Crash recovery may be incomplete.")
                self._state_save_alert_sent = True
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    def _cancel_all_pending_entries_at_sqoff(self):
        if not self.pending_entries:
            return
        self.logger.warning(f"SQ-OFF: Cancelling {len(self.pending_entries)} pending entry order(s)")
        for symbol in list(self.pending_entries.keys()):
            pending = self.pending_entries[symbol]
            order_id = pending.get('order_id', '')
            if order_id and not order_id.startswith('PAPER_'):
                try:
                    result = self.om.cancel_order(order_id)
                    if result:
                        self.logger.info(f"Cancelled pending entry {order_id} for {symbol}")
                    else:
                        self.logger.error(f"Failed to cancel {order_id} for {symbol} at sq-off")
                except Exception as e:
                    self.logger.error(f"Error cancelling {order_id}: {e}")
            self.telegram._send(
                f"🕐 <b>SQ-OFF: Pending Entry Cancelled</b>\n"
                f"Symbol: <code>{symbol}</code> | Order: {order_id}\n"
                f"No fill before sq_off_time — order cancelled."
            )
        self.pending_entries.clear()
        self.tracker.save_pending_entries({})

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

        # FIX #3: Enforce max_lots config guard
        max_lots = self.config['strategy'].get('max_lots', 999)
        if lots_per_trade > max_lots:
            self.logger.warning(f"lots_per_trade ({lots_per_trade}) > max_lots ({max_lots}). Capping to {max_lots}.")
            lots_per_trade = max_lots

        qty = lot_size * lots_per_trade
        trigger_price = self._round_to_tick(signal['price'], underlying)
        cost = trigger_price * qty

        # Check available balance (Bypass for Paper Trading)
        if not self.paper_trading:
            balance = self.client.get_balance()
            if balance is None or balance < cost:
                self.logger.warning(f"Insufficient Capital: ₹{balance} < ₹{cost}")
                return

            max_cost = balance * self.max_position_pct
            if cost > max_cost:
                self.logger.warning(f"Position too large: ₹{cost:.0f} > {self.max_position_pct*100:.0f}% of balance (₹{max_cost:.0f}). Skipping.")
                return

        # Portfolio-level risk cap (Hardening Step 4)
        max_total_premium = self.config['risk'].get('max_total_premium_deployed', 25000)
        current_premium = 0
        for trade in self.tracker.get_active_trades():
            current_premium += trade['entry_price'] * trade['remaining_qty']

        if (current_premium + cost) > max_total_premium:
            self.logger.warning(
                f"🛑 PORTFOLIO EXPOSURE CAP: Current=\u20b9{current_premium:.0f} + "
                f"New=\u20b9{cost:.0f} > Max=\u20b9{max_total_premium:.0f}. Entry aborted."
            )
            self.telegram._send(
                f"🛑 <b>Exposure Cap Hit</b>\n"
                f"Cannot entry {symbol}. Aggregate premium cap would be exceeded.\n"
                f"Active: \u20b9{current_premium:.0f} | Limit: \u20b9{max_total_premium:.0f}"
            )
            self.strategy.consume_alert(symbol)
            return

        self.logger.info(f"📌 PLACING PENDING ENTRY ORDER for {symbol} ({underlying}) at ₹{trigger_price}")

        # Place SL-M BUY order (pending until price hits trigger)
        try:
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
                self._save_strategy_state()
            else:
                self.logger.error(f"Failed to place pending entry order for {symbol}")
                # Consume the alert so we don't get orphan ENTRY signals later
                self.strategy.consume_alert(symbol)
                self.logger.info(f"Alert consumed for {symbol} due to order failure")
        except InsufficientMarginError as e:
            self.logger.warning(f"Skipping entry: {e}")
            self.strategy.consume_alert(symbol)
            return

    # _execute_entry() removed (AUDIT-013/014).
    # Superseded by _place_pending_entry() + _activate_trade_from_pending().
    # The old method used a global trade guard that blocked multi-index trading.

    def _activate_trade_from_pending(self, pending, fill_price, override_qty=None):
        """Activate a trade after pending entry order is filled.

        Includes a GAP-FILL guard to protect against excessive slippage on open.
        """
        order_id = pending['order_id']
        underlying = pending['underlying']
        signal = pending['signal']
        qty = override_qty if override_qty is not None else pending['qty']
        trading_symbol = pending['trading_symbol']
        original_symbol = pending.get('original_symbol', trading_symbol)
        trigger_price = float(pending['trigger_price'])
        fill_price = float(fill_price)

        if override_qty is not None and override_qty != pending['qty']:
             self.telegram._send(
                 f"⚠️ <b>Partial fill: {override_qty}/{pending['qty']} units filled.</b>\n"
                 f"Symbol: <code>{original_symbol}</code>\n"
                 f"Exit orders sized to actual fill."
             )

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
            alert_range = float(signal.get('alert_range', 0))
            if alert_range <= 0:
                self.logger.critical(f"[GAP-RECALC] alert_range={alert_range:.2f} <= 0 for {original_symbol}. "
                                     f"Using original signal targets to prevent inverted orders.")
                signal = {**signal}  # copy only — do NOT mutate
                # Skip recalc entirely; fall through with original targets
            else:
                new_sl = round(fill_price - alert_range, 2)

                # ADD INVERTED SL ABORT GUARD HERE:
                if new_sl >= fill_price:
                    self.logger.critical(
                        f"🚫 INVERTED SL ABORT: {original_symbol} | "
                        f"new_sl={new_sl} >= fill_price={fill_price}. "
                        f"Triggering emergency exit."
                    )
                    self.om.place_exit_order(trading_symbol, qty, trading_symbol, "INVERTED_SL_ABORT")
                    self.strategy.consume_alert(original_symbol)
                    self.telegram._send(
                        f"🚨 <b>Inverted SL Abort</b>\nSymbol: <code>{original_symbol}</code>\n"
                        f"new_sl={new_sl} >= fill={fill_price}. Position closed immediately."
                    )
                    return

                new_targets = [
                    round(fill_price + alert_range, 2),
                    round(fill_price + 2 * alert_range, 2),
                    round(fill_price + 3 * alert_range, 2),
                ]
                assert all(t > fill_price for t in new_targets), "Target below fill price"
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
        exit_orders = self.om.place_partial_exits(original_symbol, trading_symbol, signal, fill_price, actual_qty=qty)

        target_order_ids = [None, None, None]
        for order in exit_orders['orders']:
            # map order ids to their respective index (0 for TP1, 1 for TP2, 2 for TP3)
            idx = int(order['target_level']) - 1
            if 0 <= idx < 3:
                target_order_ids[idx] = order.get('order_id')

        # Create trade record — include exit_orders from the start (single write)
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
            'exit_orders': exit_orders,           # ← MOVED HERE
            'alert_range': signal.get('alert_range', 0),  # ← MOVED HERE
        }

        # Add to tracker — single atomic write, no follow-up update needed
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

        # exit_mode for Telegram message
        exit_mode = exit_orders.get('mode', signal.get('exit_mode', 'single_lot'))

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
                        self._save_strategy_state()
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
                    self._save_strategy_state()

                elif status in ('CANCELLED', 'REJECTED', 'EXPIRED'):
                    # BUG-001: Check for partial fill before total cleanup
                    filled_qty = int(order_status.get('filled_quantity', 0))
                    if filled_qty > 0:
                        self.logger.warning(
                            f"🔔 Partial Entry detected for {symbol} ({filled_qty} units). "
                            f"Order was {status}, but partial fill occurred. Activating Stub Trade."
                        )
                        fill_price = order_status.get('fill_price') or pending['trigger_price']
                        self._activate_trade_from_pending(pending, fill_price=fill_price, override_qty=filled_qty)

                        self.telegram._send(
                            f"⚠️ <b>Partial Fill — Trade Activated</b>\n"
                            f"Symbol: <code>{symbol}</code>\n"
                            f"Filled: {filled_qty} units (order was {status})\n"
                            f"Trade is LIVE with stub quantity. Monitor SL closely."
                        )
                    else:
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
                    self._save_strategy_state()

            except Exception as e:
                self.logger.error(f"Error monitoring pending entry for {symbol}: {e}")

    def _close_paper_trade_hit_target(self, trade, target_idx, target_price, ltp):
        """Helper to close a paper trade when a target is hit."""
        symbol = trade['symbol']
        trade_id = trade['trade_id']
        fill_price = target_price  # Limit sell fills at target price

        self.logger.info(f"🎯 [PAPER] TARGET HIT (FINAL) for {symbol} @ ₹{fill_price} (LTP: ₹{ltp:.2f}) - Closing Trade")

        final_pnl = (fill_price - float(trade['entry_price'])) * float(trade['remaining_qty'])
        total_pnl = final_pnl + float(trade.get('partial_pnl', 0))
        self.daily_pnl += final_pnl

        reason = f"TP{target_idx+1}_HIT"
        trade['exit_price'] = ltp
        trade['reason'] = reason
        trade['pnl'] = total_pnl

        self.tracker.close_trade(trade_id, ltp, reason, total_pnl)
        self._update_circuit_breaker(final_pnl, reason)
        self.trade_logger.log_exit(trade, self.daily_pnl)

        self.telegram.target_hit(
            symbol=symbol,
            tp_num=target_idx+1,
            price=fill_price,
            entry_price=float(trade['entry_price']),
            qty_exited=float(trade['remaining_qty']),
            new_sl=None
        )

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
            exit_mode = exit_orders.get('mode', 'single_lot')
            targets = trade.get('targets', [])
            current_sl = exit_orders.get('current_sl', trade['sl'])
            underlying = trade.get('underlying', 'NIFTY')

            # --- BEGIN SINGLE LOT SL TRAILING (LIVE & PAPER) ---
            if exit_mode == 'single_lot' and len(targets) > 0:
                ltp = self._get_ltp_cached(symbol)
                if ltp is not None:
                    target_idx = self.config.get('strategy', {}).get('single_lot_exit_target', 2) - 1
                    for tp in range(trail_state, target_idx):
                        if tp < len(targets) and ltp >= targets[tp]:
                            entry_price = float(trade['entry_price'])
                            new_sl_price = 0
                            if tp == 0:
                                new_sl_price = entry_price
                            elif tp == 1:
                                new_sl_price = targets[0]

                            if new_sl_price > 0:
                                new_sl_price = self._round_to_tick(new_sl_price, underlying)
                                if new_sl_price > current_sl:
                                    self.logger.info(f"📈 TRAILING SL to ₹{new_sl_price} (TP{tp+1} crossed @ ₹{ltp})")
                                    # Modified actual SL order if live
                                    if sl_order_id and not (self.paper_trading and sl_order_id.startswith('PAPER_')):
                                        self.om.modify_sl_order(sl_order_id, new_sl_price, symbol, new_qty=trade['remaining_qty'])

                                    exit_orders['current_sl'] = new_sl_price
                                    exit_orders['trail_state'] = tp + 1
                                    self.tracker.update_trade(trade_id, {'exit_orders': exit_orders})

                                    self.telegram._send(
                                        f"📈 <b>SL Trailed (Single Lot)</b>\n"
                                        f"Symbol: <code>{symbol}</code>\n"
                                        f"Crossed TP{tp+1}. New SL: ₹{new_sl_price}"
                                    )
                                    trail_state = tp + 1
                                    current_sl = new_sl_price
                        else:
                            break
            # --- END SINGLE LOT SL TRAILING ---

            # PAPER TRADING: Use LTP-based simulation
            if self.paper_trading and sl_order_id and sl_order_id.startswith('PAPER_'):
                ltp = self._get_ltp_cached(symbol)
                if ltp is None:
                    continue



                # V16-P-08: TP-before-SL when SL trailed above entry (profitable trail)
                # Check for target hit FIRST if the SL is in profit territory.
                trailed_sl_above_entry = current_sl > float(trade['entry_price'])

                if trailed_sl_above_entry:
                    if exit_mode == 'single_lot':
                        target_idx = self.config.get('strategy', {}).get('single_lot_exit_target', 2) - 1
                        target_price = targets[target_idx] if target_idx < len(targets) else targets[-1]
                        if ltp >= target_price:
                            # Target takes priority
                            self._close_paper_trade_hit_target(trade, target_idx, target_price, ltp)
                            continue

                # Normal SL Check
                sl_triggered = ltp <= current_sl
                if sl_triggered:
                    exit_price = current_sl
                    exit_reason = "SL_HIT"
                    self.logger.info(f"🔴 [PAPER] SL HIT for {symbol} @ ₹{exit_price}")

                    final_pnl = (exit_price - float(trade['entry_price'])) * float(trade['remaining_qty'])
                    total_pnl = final_pnl + float(trade.get('partial_pnl', 0))
                    self.daily_pnl += final_pnl
                    trade['exit_price'] = exit_price
                    trade['reason'] = exit_reason
                    trade['pnl'] = total_pnl
                    self.tracker.close_trade(trade_id, exit_price, exit_reason, total_pnl)
                    self._update_circuit_breaker(final_pnl, exit_reason)
                    self.trade_logger.log_exit(trade, self.daily_pnl)
                    self.telegram.sl_hit(symbol, exit_price, float(trade['entry_price']), float(trade['remaining_qty']), self.daily_pnl)
                    continue

                # Check single lot final target
                if exit_mode == 'single_lot':
                    target_idx = self.config.get('strategy', {}).get('single_lot_exit_target', 2) - 1
                    target_price = targets[target_idx] if target_idx < len(targets) else targets[-1]
                    if ltp >= target_price:
                        self._close_paper_trade_hit_target(trade, target_idx, target_price, ltp)
                    continue

                # Check TP1 (multi-lot only - trail SL)
                if exit_mode == 'multi_lot' and len(targets) > 0 and trail_state < 1 and ltp >= targets[0]:
                    tp1_fill = targets[0]  # Limit sell fills at target price (not current LTP)
                    self.logger.info(f"🎯 [PAPER] TP1 HIT for {symbol} @ ₹{tp1_fill} (LTP: ₹{ltp:.2f})")
                    self._handle_paper_tp_hit(trade, 1, tp1_fill)
                    trail_state = trade.get('exit_orders', {}).get('trail_state', 0)  # Re-read

                # Check TP2
                if exit_mode == 'multi_lot' and len(targets) > 1 and trail_state == 1 and ltp >= targets[1]:
                    tp2_fill = targets[1]  # Limit sell fills at target price
                    self.logger.info(f"🎯 [PAPER] TP2 HIT for {symbol} @ ₹{tp2_fill} (LTP: ₹{ltp:.2f})")
                    self._handle_paper_tp_hit(trade, 2, tp2_fill)
                    trail_state = trade.get('exit_orders', {}).get('trail_state', 0)  # Re-read

                # Check TP3 (multi-lot only - final exit)
                if exit_mode == 'multi_lot' and len(targets) > 2 and trail_state == 2 and ltp >= targets[2]:
                    tp3_fill = targets[2]  # Limit sell fills at target price (not current LTP)
                    self.logger.info(f"🚀 [PAPER] TP3 HIT for {symbol} @ ₹{tp3_fill} (LTP: ₹{ltp:.2f}) - Closing Trade")
                    final_pnl = (tp3_fill - float(trade['entry_price'])) * float(trade['remaining_qty'])
                    total_pnl = final_pnl + float(trade.get('partial_pnl', 0))
                    self.daily_pnl += final_pnl
                    reason = "TP3_HIT"
                    trade['exit_price'] = tp3_fill
                    trade['exit_time'] = datetime.now().isoformat()
                    trade['reason'] = reason
                    trade['pnl'] = total_pnl
                    self.tracker.close_trade(trade_id, tp3_fill, reason, total_pnl)
                    self._update_circuit_breaker(final_pnl, reason)
                    self.trade_logger.log_exit(trade, self.daily_pnl)
                    self.telegram.target_hit(
                        symbol=symbol,
                        tp_num=3,
                        price=tp3_fill,
                        entry_price=float(trade['entry_price']),
                        qty_exited=int(trade.get('remaining_qty', 0)),
                        new_sl=None
                    )
                    continue  # CRITICAL: prevents fall-through to live section
                        # ─── LIVE TRADING MONITORING (Broker Calls) ──────────────────────
            if not self.paper_trading:
                # 1. Check SL Order Status
                if sl_order_id:
                    sl_status = self.client.get_order_status(sl_order_id)
                    if sl_status:
                        sl_state = sl_status.get('status', '').upper()

                        if is_order_filled(sl_state):
                            self.logger.info(f"🔴 SL HIT for {symbol} (Order {sl_order_id})")
                            actual_fill = float(sl_status.get('fill_price') or trade['sl'])
                            self.logger.info(f"SL Fill price extracted: \u20b9{actual_fill} (reference was: \u20b9{trade['sl']})")

                            overshoot_pct = (float(trade['sl']) - actual_fill) / float(trade['sl'])
                            if overshoot_pct > 0.03:
                                excess_loss = (float(trade['sl']) - actual_fill) * float(trade['remaining_qty'])
                                self.logger.critical(f"SL OVERSHOOT: {symbol} Expected \u20b9{trade['sl']}, Got \u20b9{actual_fill} ({overshoot_pct*100:.1f}%). Excess loss: \u20b9{excess_loss:.0f}")
                                self.telegram._send_to_owner(f"🔴 SL OVERSHOOT\n{symbol}\nExpected \u20b9{trade['sl']} → Got \u20b9{actual_fill}\nExcess loss: \u20b9{excess_loss:.0f}")

                            fill_price = actual_fill

                            # Cancel all pending target orders with verification (Real Money Safety)
                            for tid in target_ids:
                                if tid:
                                    self._cancel_with_retry(tid, context=f"SL_HIT Target Cancel for {trade_id}")

                            # 2. Guard for SL exit logic: qty mismatch
                            qty_filled = int(sl_status.get('filled_quantity') or 0)
                            expected_qty = int(trade.get('remaining_qty', 0))
                            if qty_filled > 0 and qty_filled != expected_qty:
                                self.logger.critical(
                                    f"SL qty mismatch for {trade_id}: Filled {qty_filled} "
                                    f"but tracked {expected_qty}. Using broker qty."
                                )
                                exit_qty = qty_filled
                            else:
                                exit_qty = expected_qty

                            # Close trade
                            final_pnl = (float(fill_price) - float(trade['entry_price'])) * exit_qty
                            total_pnl = final_pnl + float(trade.get('partial_pnl', 0))
                            self.daily_pnl += final_pnl
                            trade['exit_price'] = fill_price
                            trade['reason'] = "SL_HIT"
                            trade['pnl'] = total_pnl
                            self.tracker.close_trade(trade_id, fill_price, "SL_HIT", total_pnl)
                            self._update_circuit_breaker(final_pnl, "SL_HIT")
                            self.trade_logger.log_exit(trade, self.daily_pnl)

                            # V17-H-02: Immediate check for daily loss after closure
                            if self._check_daily_loss_limit():
                                self.logger.critical("Daily loss limit breached via SL hit. halting.")

                            continue

                        elif sl_state == 'PARTIALLY_FILLED':
                            # 3. SL partially filled
                            self.logger.critical(f"SL order {sl_order_id} PARTIALLY FILLED for {trade_id}.")
                            self.telegram._send_to_owner(f"🚨 SL partial fill on {symbol}. Check manually.")
                            # Do NOT close trade. Re-check next poll cycle.
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
                            remaining_qty = TradeTracker.get_remaining_qty(trade)
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
                                ltp = self._get_ltp_cached(symbol) or current_sl
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
                    if exit_mode == 'multi_lot' and tp_level <= trail_state:
                        continue

                    t_status = self.client.get_order_status(tid)
                    if t_status:
                        s = t_status.get('status', '').upper()
                        qty_filled = int(t_status.get('filled_quantity', 0) or 0)

                        if s == 'PARTIALLY_FILLED' and qty_filled > 0:
                            # 1. Update remaining_qty by ACTUALLY filled amount
                            current_remaining = TradeTracker.get_remaining_qty(trade)
                            new_remaining = current_remaining - qty_filled
                            if new_remaining < 0:
                                self.logger.critical(f"Remaining qty would go negative for {trade_id}. Clamping to 0.")
                                new_remaining = 0

                            # Record partial PnL
                            fill_price = float(t_status.get('fill_price') or trade['entry_price'])
                            partial_profit = (fill_price - float(trade['entry_price'])) * qty_filled
                            self.daily_pnl += partial_profit
                            new_partial_pnl = float(trade.get('partial_pnl', 0)) + partial_profit

                            self.tracker.update_trade(trade_id, {
                                'remaining_qty': new_remaining,
                                'partial_pnl': new_partial_pnl
                            })
                            self.trade_logger.log_partial_exit(trade, qty_filled, fill_price,
                                                               f"TP{tp_level}_PARTIAL", partial_profit, self.daily_pnl)
                            self.telegram._send(
                                f"⚠️ <b>Partial Fill TP{tp_level}</b>\n"
                                f"Symbol: <code>{symbol}</code>\n"
                                f"Filled: {qty_filled}/{qty_filled + new_remaining} units @ ₹{fill_price}\n"
                                f"Remaining: {new_remaining} units still live."
                            )
                            continue

                        if is_order_filled(s):
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
                                reason = f"TP{tp_level}_HIT"
                                trade['exit_price'] = fill_price
                                trade['reason'] = reason
                                trade['pnl'] = total_pnl
                                self.tracker.close_trade(trade_id, fill_price, reason, total_pnl)
                                self._update_circuit_breaker(final_pnl, reason)
                                self.trade_logger.log_exit(trade, self.daily_pnl)
                                break  # Trade is closed
                            elif exit_mode == 'multi_lot':
                                # Partial Exit (TP1 or TP2)
                                self.logger.info(f"🎯 TP{tp_level} HIT for {symbol}")
                                self._handle_tp_hit(trade, tp_level, t_status)
                                trail_state = trade.get('exit_orders', {}).get('trail_state', 0)

            # End if not self.paper_trading
        # End for trade in active_trades

    def _handle_paper_tp_hit(self, trade, tp_level, fill_price):
        """Handle paper trading TP hit with LTP-based simulation."""
        trade_id = trade['trade_id']
        exit_orders = trade.get('exit_orders', {})
        targets = trade.get('targets', [])
        underlying = trade.get('underlying', 'NIFTY')

        # Update trail state
        exit_orders['trail_state'] = tp_level

        # Trail SL — absolute prices (matches _handle_tp_hit for live mode)
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

        partial_profit = (fill_price - float(trade['entry_price'])) * partial_qty
        self.daily_pnl += partial_profit
        trade['partial_pnl'] = trade.get('partial_pnl', 0) + partial_profit

        # Update remaining qty
        remaining = TradeTracker.get_remaining_qty(trade) - partial_qty
        trade['remaining_qty'] = remaining

        self.tracker.update_trade(trade_id, {
            'exit_orders': exit_orders,
            'remaining_qty': remaining,
            'partial_pnl': trade['partial_pnl']
        })

        self.logger.info(f"✅ [PAPER] Partial Exit TP{tp_level}: {partial_qty} units | P&L: ₹{partial_profit:.2f}")

        # Telegram: notify
        self.telegram.target_hit(trade['symbol'], tp_level, fill_price, float(trade['entry_price']), partial_qty, new_sl if new_sl > 0 else None)

    def _handle_tp_hit(self, trade, tp_level, order_status):
        """Handle logic when a Target is hit (Partial Exit + Trail SL)."""
        trade_id = trade['trade_id']
        exit_orders = trade['exit_orders']
        sl_order_id = trade['sl_order_id']

        fill_price = float(order_status.get('fill_price') or order_status.get('price') or trade['entry_price'])
        self.logger.info(f"Target Hit: Fill price extracted: ₹{fill_price} (reference was: {trade['entry_price']})")
        qty_filled = int(
            order_status.get('filled_quantity') or    # Groww's correct key
            order_status.get('quantity') or           # fallback
            0
        )

        # Safety guard: if qty_filled is 0, infer from the exit order book entry
        if qty_filled == 0:
            self.logger.warning(
                f"qty_filled=0 from order status for trade {trade_id} TP{tp_level}. "
                f"Attempting to infer from exit order quantity."
            )
            exit_order_info = next(
                (o for o in trade.get('exit_orders', {}).get('orders', [])
                 if o.get('target_level') == tp_level),
                {}
            )
            qty_filled = exit_order_info.get('quantity', 0)

        if qty_filled == 0:
            tid = order_status.get('order_id', 'UNKNOWN')
            self.logger.error(
                f"Cannot determine qty_filled for TP{tp_level} on trade {trade_id}. "
                f"Nulling target order {tid} to prevent reprocessing. Verify P&L in Groww app."
            )
            # Null out this target order so monitoring loop skips it next cycle
            target_ids = trade.get('target_order_ids', [])
            idx = tp_level - 1
            if 0 <= idx < len(target_ids):
                target_ids[idx] = None
                self.tracker.update_trade(trade_id, {'target_order_ids': target_ids})

            # Also send Telegram alert for manual review
            self.telegram._send_to_owner(
                f"⚠️ <b>TP{tp_level} fill qty unknown</b>\n"
                f"Trade: <code>{trade.get('symbol', trade_id)}</code>\n"
                f"Order {tid} shows COMPLETE but qty unknown.\n"
                f"P&L may be inaccurate. Check Groww app."
            )
            return

        self.logger.info(f"TP{tp_level} fill: price=₹{fill_price} qty={qty_filled} (from order status)")

        # Update trade record
        # FIX #2: Guard against negative remaining_qty
        current_remaining = trade['remaining_qty']
        new_remaining = current_remaining - qty_filled
        if new_remaining < 0:
            self.logger.critical(
                f"🚨 remaining_qty would go NEGATIVE for {trade_id}: "
                f"{current_remaining} - {qty_filled} = {new_remaining}. Clamping to 0."
            )
            self.telegram._send_to_owner(
                f"🚨 <b>CRITICAL: Negative Remaining Qty</b>\n"
                f"Trade: <code>{trade.get('symbol', trade_id)}</code>\n"
                f"remaining={current_remaining}, filled={qty_filled}\n"
                f"Clamped to 0. Check Groww app NOW."
            )
            new_remaining = 0
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
             if sl_order_id and not self.paper_trading:
                 self.om.modify_sl_order(sl_order_id, new_sl_price, trade['symbol'], new_qty=new_remaining)

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



    def _cancel_with_retry(self, order_id: str, max_retries: int = 3, context: str = "") -> bool:
        """FIX #1: Cancel an order with retry and verification.

        After each cancel attempt, verifies the order is actually cancelled
        by checking order status. Retries up to max_retries times with 1s delay.
        Sends CRITICAL alert to owner if cancel ultimately fails.

        Returns True if cancelled, False if all retries exhausted.
        """
        if not order_id or (isinstance(order_id, str) and order_id.startswith('PAPER_')):
            return True  # Paper orders don't need broker cancellation

        for attempt in range(1, max_retries + 1):
            try:
                self.om.cancel_order(order_id)
                self.logger.info(f"Cancel attempt {attempt}/{max_retries} sent for {order_id} ({context})")
            except Exception as e:
                self.logger.error(f"Cancel attempt {attempt}/{max_retries} failed for {order_id}: {e}")

            # Verify cancellation
            time.sleep(1)
            try:
                status = self.client.get_order_status(order_id)
                order_status = (status or {}).get('status', '').upper()
                if order_status in ('CANCELLED', 'REJECTED', 'COMPLETE', 'COMPLETED'):
                    self.logger.info(f"Order {order_id} confirmed {order_status} ({context})")
                    return True
                else:
                    self.logger.warning(
                        f"Order {order_id} still {order_status} after cancel attempt "
                        f"{attempt}/{max_retries} ({context})"
                    )
            except Exception as e:
                self.logger.error(f"Status check failed for {order_id}: {e}")

        # All retries exhausted — CRITICAL
        self.logger.critical(
            f"🚨 CANCEL FAILED after {max_retries} retries: {order_id} ({context}). "
            f"Order may still be LIVE at broker. CHECK GROWW APP IMMEDIATELY."
        )
        self.telegram._send_to_owner(
            f"🚨 <b>CRITICAL: Cancel Failed</b>\n"
            f"Order: <code>{order_id}</code>\n"
            f"Context: {context}\n"
            f"Order may still be LIVE after {max_retries} retries.\n"
            f"<b>CHECK GROWW APP NOW.</b>"
        )
        return False

    def _update_circuit_breaker(self, trade_pnl: float, reason: str) -> None:
        """V11-P-02: Update consecutive loss counter and activate circuit breaker if needed."""
        max_consec = self.config.get('risk', {}).get('max_consecutive_losses', 999)

        if trade_pnl < 0 or 'SL' in reason:
            self.consecutive_losses += 1
            self.logger.info(
                f"[CIRCUIT BREAKER] Consecutive losses: {self.consecutive_losses}/{max_consec}"
            )
            if self.consecutive_losses >= max_consec:
                self.circuit_breaker_active = True
                self.logger.warning(
                    f"[CIRCUIT BREAKER] ACTIVATED after {self.consecutive_losses} consecutive losses. "
                    f"No new trades for rest of session."
                )
                self.telegram._send_to_owner(
                    f"<b>Circuit Breaker Activated</b>\n"
                    f"{datetime.now().strftime('%H:%M:%S')}\n"
                    f"{self.consecutive_losses} consecutive losses in a row.\n"
                    f"No new trades for rest of session.\n"
                    f"Daily P&L: Rs.{self.daily_pnl:+.0f}"
                )
        else:
            # Reset on any win
            if self.consecutive_losses > 0:
                self.logger.info(
                    f"[CIRCUIT BREAKER] Reset after win. Was at "
                    f"{self.consecutive_losses} consecutive losses."
                )
            self.consecutive_losses = 0
            self.circuit_breaker_active = False

    def _close_entire_position(self, trade, ltp, reason):
        """Close entire position and update tracker."""
        symbol = trade['symbol']
        trading_symbol = trade['trading_symbol']
        trade_id = trade['trade_id']
        remaining_qty = TradeTracker.get_remaining_qty(trade)
        sl_order_id = trade.get('sl_order_id')
        exit_orders = trade.get('exit_orders', {})

        # Cancel broker SL order (no longer needed, we're exiting)
        if sl_order_id:
            self._cancel_with_retry(sl_order_id, context=f"CLOSE_POSITION SL for {trade_id}")

        # Cancel pending target orders
        target_ids = trade.get('target_order_ids', [])
        for tid in target_ids:
            if tid:
                self._cancel_with_retry(tid, context=f"CLOSE_POSITION Target for {trade_id}")

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

        # Close trade in tracker
        self.tracker.close_trade(trade_id, ltp, reason, total_pnl)
        self._update_circuit_breaker(final_pnl, reason)

        # V17-H-02: Immediate check for daily loss after closure
        if self._check_daily_loss_limit():
            self.logger.critical(f"Daily loss limit breached via {reason} hit. halting.")

        # Log to CSV for audit
        self.trade_logger.log_exit(trade, self.daily_pnl, 0)

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

        # Order monitoring throttle — only poll order status every N seconds.
        # Candle-close detection (1-second) is unaffected.
        # Groww has API rate limits; 5s is sufficient for a 15-min candle strategy.
        ORDER_POLL_INTERVAL = self.config.get('trading', {}).get('order_poll_interval_seconds', 5)
        # Forces monitoring to run on the first loop iteration, then every ORDER_POLL_INTERVAL seconds
        last_order_poll = datetime.now() - timedelta(seconds=ORDER_POLL_INTERVAL + 1)
        import json
        session_start_time = datetime.now()

        # Main loop
        while True:
            try:
                now = datetime.now()
                warmup_start = self._get_warmup_start_time()

                # Kill switch check — touch /tmp/rsi_bot_kill to trigger graceful shutdown
                # To trigger kill switch from another terminal:
                #   touch /tmp/rsi_bot_kill
                #
                # To trigger from Telegram bot (future enhancement):
                #   Send "/kill" to the bot — requires incoming message handling
                import os
                if os.path.exists(KILL_SWITCH_FILE):
                    self.logger.critical("🛑 KILL SWITCH ACTIVATED. Squaring off all positions.")
                    self.telegram._send("🛑 <b>Kill Switch Activated</b>\nBot stopping. Check positions in Groww app.")
                    try:
                        os.remove(KILL_SWITCH_FILE)
                    except Exception:
                        pass
                    # The prompt suggested `break` here assuming a finally block existed.
                    # Since square-off is handled IN the loop at `self.sq_off_time`, we
                    # trigger it by advancing the square off time to midnight, ensuring
                    # it triggers synchronously on this exact iteration.
                    self.sq_off_time = datetime_time(0, 0)

                # HEARTBEAT
                if (now - last_heartbeat).total_seconds() >= heartbeat_interval:
                    self.logger.info(f"Heartbeat - Bot is running. Active trades: {len(self.tracker.get_active_trades())}")
                    last_heartbeat = now

                    # Write heartbeat file for external monitoring
                    try:
                        heartbeat_data = {
                            'timestamp': now.isoformat(),
                            'status': 'RUNNING',
                            'daily_pnl': round(self.daily_pnl, 2),
                            'active_trades': len(self.tracker.get_active_trades()),
                            'pending_entries': len(self.pending_entries),
                            'last_candle_time': self.last_candle_time.isoformat() if self.last_candle_time else None,
                            'paper_trading': self.paper_trading,
                            'uptime_seconds': (now - session_start_time).total_seconds()
                        }
                        # Use cross-platform temporary directory
                        heartbeat_path = os.path.join(tempfile.gettempdir(), 'rsi_bot_heartbeat.json')
                        with open(heartbeat_path, 'w') as hf:
                            json.dump(heartbeat_data, hf)

                        # PHASE 2: Periodic Candle State Backup (every heartbeat)
                        for underlying in self.underlyings:
                            for symbol in self.tracked_options.get(underlying, {}):
                                history = self.candle_builder.get_history(symbol)
                                if history:
                                    self.tracker.save_candle_state(symbol, history)
                    except Exception as e:
                        self.logger.debug(f"Heartbeat write failed: {e}")

                    # Circuit breaker awareness
                    if not self._is_market_open():
                        if not self._halt_alert_sent:
                            self.logger.warning("NIFTY LTP unavailable — possible market halt or circuit breaker")
                            self.telegram._send(
                                f"⚠️ <b>Possible Market Halt</b>\n"
                                f"🕐 {datetime.now().strftime('%H:%M:%S')}\n"
                                "NIFTY LTP unavailable. Possible NSE circuit breaker.\n"
                                "Check: nseindia.com | Monitor positions manually.\n"
                                "Bot continues running normally."
                            )
                            self._halt_alert_sent = True
                    else:
                        if self._halt_alert_sent:
                            self.logger.info("NIFTY LTP restored — market appears to have resumed")
                        self._halt_alert_sent = False

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
                    self._cancel_all_pending_entries_at_sqoff()

                    # Square off active trades
                    active_trades = self.tracker.get_active_trades()
                    for trade in active_trades:
                        self.logger.info(f"Squaring off: {trade['trade_id']}")

                        # FIX #1: Cancel SL and target orders with retry verification
                        sl_id = trade.get('sl_order_id')
                        if sl_id:
                            self._cancel_with_retry(sl_id, context=f"SQ_OFF SL for {trade['trade_id']}")
                        for tid in trade.get('target_order_ids', []):
                            if tid:
                                self._cancel_with_retry(tid, context=f"SQ_OFF TP for {trade['trade_id']}")

                        remaining_qty = TradeTracker.get_remaining_qty(trade)

                        # Place exit order
                        exit_resp = self.om.place_exit_order(
                            trade['symbol'], remaining_qty, trade['trading_symbol'], "SQ_OFF"
                        )

                        # Actual fill Detection (PROMPT 16 - Tiered approach)
                        actual_fill = None
                        exit_order_id = None  # V11-P-01: init before conditional to prevent NameError
                        if exit_resp and exit_resp.get('groww_order_id'):
                            exit_order_id = exit_resp['groww_order_id']
                            time.sleep(3)  # Allow time to fill
                            try:
                                exit_status = self.client.get_order_status(exit_order_id)
                                if exit_status and is_order_filled(exit_status.get('status', '')):
                                    actual_fill = exit_status.get('fill_price')
                                    self.logger.info(f"SQ_OFF filled at \u20b9{actual_fill} via our order")
                            except Exception as e:
                                self.logger.error(f"SQ_OFF fill check failed: {e}")

                        # --- TIER 2: Retry our exit order after longer wait (market orders take 2-10s) ---
                        if not actual_fill and exit_order_id:
                            try:
                                time.sleep(5)   # additional wait for settlement
                                retry_status = self.client.get_order_status(exit_order_id)
                                if retry_status and is_order_filled(retry_status.get('status', '')):
                                    actual_fill = retry_status.get('fill_price')
                                    if actual_fill:
                                        self.logger.info(f"SQ_OFF filled at ₹{actual_fill} (Tier 2 retry)")
                                elif retry_status:
                                    self.logger.warning(
                                        f"SQ_OFF order {exit_order_id} status after retry: "
                                        f"{retry_status.get('status')} — position may have been "
                                        f"auto-squared by Groww MIS at 3:20 PM"
                                    )
                            except Exception as e:
                                self.logger.warning(f"Tier 2 retry failed: {e}")

                        # Tier 3: Fallback to LTP
                        if not actual_fill:
                            actual_fill = self.client.get_ltp(trade['symbol']) or float(trade['entry_price'])
                            self.logger.warning(f"Using LTP fallback for SQ_OFF P&L: \u20b9{actual_fill}")

                        # Close trade
                        partial_pnl = trade.get('partial_pnl', 0)
                        final_pnl = (float(actual_fill) - float(trade['entry_price'])) * remaining_qty
                        total_pnl = final_pnl + partial_pnl
                        self.daily_pnl += final_pnl

                        trade['exit_price'] = actual_fill
                        trade['reason'] = "SQ_OFF"
                        trade['pnl'] = total_pnl
                        self.tracker.close_trade(trade['trade_id'], actual_fill, "SQ_OFF", total_pnl)
                        self._update_circuit_breaker(final_pnl, "SQ_OFF")
                        self.trade_logger.log_exit(trade, self.daily_pnl)
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
                        remaining_qty = TradeTracker.get_remaining_qty(trade)

                        # FIX #1: Cancel broker SL / target orders with retry verification
                        sl_id = trade.get('sl_order_id')
                        if sl_id:
                            self._cancel_with_retry(sl_id, context=f"DAILY_LOSS SL for {trade['trade_id']}")
                        for tid in trade.get('target_order_ids', []):
                            if tid:
                                self._cancel_with_retry(tid, context=f"DAILY_LOSS TP for {trade['trade_id']}")

                        # Place exit order and capture response
                        exit_resp = self.om.place_exit_order(
                            trade['symbol'],
                            remaining_qty,
                            trade['trading_symbol'],
                            "DAILY_LOSS_LIMIT"
                        )

                        # Tier 1: Actual fill from our exit order response
                        actual_fill = None
                        exit_order_id = None  # V11-P-01: init before conditional to prevent NameError
                        if exit_resp and exit_resp.get('groww_order_id'):
                            exit_order_id = exit_resp['groww_order_id']
                            time.sleep(3)  # Allow time to fill
                            try:
                                exit_status = self.client.get_order_status(exit_order_id)
                                if exit_status and is_order_filled(exit_status.get('status', '')):
                                    actual_fill = exit_status.get('fill_price')
                                    self.logger.info(f"DAILY_LOSS_LIMIT filled at ₹{actual_fill} via our order")
                            except Exception as e:
                                self.logger.error(f"DAILY_LOSS fill check failed: {e}")

                        # --- TIER 2: Retry our exit order after longer wait (market orders take 2-10s) ---
                        if not actual_fill and exit_order_id:
                            try:
                                time.sleep(5)   # additional wait for settlement
                                retry_status = self.client.get_order_status(exit_order_id)
                                if retry_status and is_order_filled(retry_status.get('status', '')):
                                    actual_fill = retry_status.get('fill_price')
                                    if actual_fill:
                                        self.logger.info(f"SQ_OFF filled at ₹{actual_fill} (Tier 2 retry)")
                                elif retry_status:
                                    self.logger.warning(
                                        f"SQ_OFF order {exit_order_id} status after retry: "
                                        f"{retry_status.get('status')} — position may have been "
                                        f"auto-squared by Groww MIS at 3:20 PM"
                                    )
                            except Exception as e:
                                self.logger.warning(f"Tier 2 retry failed: {e}")

                        # Tier 3: Fallback to LTP
                        if not actual_fill:
                            actual_fill = self.client.get_ltp(trade['symbol']) or float(trade['entry_price'])
                            self.logger.warning(f"Using LTP fallback for DAILY_LOSS_LIMIT P&L: ₹{actual_fill}")

                        # Close trade
                        partial_pnl = trade.get('partial_pnl', 0)
                        final_pnl = (float(actual_fill) - float(trade['entry_price'])) * remaining_qty
                        total_pnl = final_pnl + partial_pnl
                        self.daily_pnl += final_pnl

                        trade['exit_price'] = actual_fill
                        trade['reason'] = "DAILY_LOSS_LIMIT"
                        trade['pnl'] = total_pnl
                        self.tracker.close_trade(trade['trade_id'], actual_fill, "DAILY_LOSS_LIMIT", total_pnl)
                        self._update_circuit_breaker(final_pnl, "DAILY_LOSS_LIMIT")
                        self.trade_logger.log_exit(trade, self.daily_pnl)
                        self.telegram.square_off(trade['symbol'], actual_fill, float(trade['entry_price']), remaining_qty, "DAILY_LOSS_LIMIT")

                    self.logger.info(f"🛑 Emergency shutdown. Daily P&L: ₹{self.daily_pnl:.2f}")
                    break

                # P-05: Market halt detection — NSE circuit breaker guard
                # Pause order management if NIFTY LTP unavailable (circuit breaker)
                if not self._is_market_open():
                    if not self._market_halted:
                        self._market_halted = True
                        self._halt_detected_at = now
                        self.logger.warning("Market may be halted (NSE circuit breaker?). Pausing order management.")
                        if not self._halt_alert_sent:
                            self.telegram._send(
                                "⚠️ <b>Market Halt Detected</b>\n"
                                "NIFTY LTP unavailable. Possible circuit breaker.\n"
                                "Order management paused. Will auto-resume."
                            )
                            self._halt_alert_sent = True
                    time.sleep(30)
                    continue
                else:
                    if self._market_halted:
                        mins = (now - self._halt_detected_at).seconds // 60
                        self.logger.info(f"Market resumed after ~{mins}m halt.")
                        self.telegram._send(f"✅ Market resumed after ~{mins}m. Resuming order management.")
                    self._market_halted = False
                    self._halt_alert_sent = False
                # Process Candle Logic
                if self._poll_candle_close(warmup_start):
                    self._update_option_universe(warmup_start)
                    self._process_strategy_logic(warmup_start)

                # Poll LTPs for CandleBuilder (P-21) every 2s
                # Throttled by internal LTP cache and loop cadence
                static_poll_interval = 2
                if int(now.timestamp()) % static_poll_interval == 0:
                    self._poll_option_ltps()

                # Candle Starvation Check (Hardening Step 3)
                # If no bar has closed in 20 minutes (15m interval + 5m buffer), alert.
                if (now - self._last_bar_close_time).total_seconds() > 1200: # 20 mins
                    if not self._starvation_alert_sent and now_ist.time() > datetime_time(9, 35):
                        self.logger.critical("🔥 CANDLE STARVATION: No bar closed in >20 minutes!")
                        self.telegram._send_to_owner(
                            f"🔥 <b>Candle Starvation Alert</b>\n"
                            f"No 15-min bars produced for 20 mins.\n"
                            f"Check if LTP feed is active (Groww connection)."
                        )
                        self._starvation_alert_sent = True

                # Monitor active positions and pending entries (throttled to ORDER_POLL_INTERVAL)
                # Order status API calls are expensive — checking every 5s is sufficient
                # for a 15-min candle strategy and keeps us well within Groww rate limits.
                if (now - last_order_poll).total_seconds() >= ORDER_POLL_INTERVAL:
                    self._monitor_pending_entries()
                    self._monitor_active_trades()
                    last_order_poll = now

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
