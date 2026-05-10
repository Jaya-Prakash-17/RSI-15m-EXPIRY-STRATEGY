# nifty_futures_rsi/engine.py
"""
NIFTY Futures RSI-60 Breakout -- Backtest Engine

Executes the RSI-60 crossover strategy on NIFTY spot data,
simulating trades on 1-lot NIFTY Futures with:
  - Historical lot sizes (2020-2025)
  - Multi-target exits with trailing SL
  - Daily loss limits
  - Realistic slippage model
  - Integration with the existing PerformanceReporter
"""

import sys
import logging
import numpy as np
import pandas as pd
from math import ceil
from datetime import datetime, time, timedelta

from utils.nse_calendar import is_trading_day
from utils.historical_lot_sizes import get_historical_lot_size
from nifty_futures_rsi.strategy import NiftyFuturesRSI60


class NiftyFuturesEngine:
    def __init__(self, data_manager, config):
        self.logger = logging.getLogger("NiftyFuturesEngine")
        self.dm = data_manager
        self.config = config

        self.strategy = NiftyFuturesRSI60(config)

        self.capital = config['capital']['initial']
        self.trades = []

        self.start_time = datetime.strptime(
            config['trading']['window']['start'], "%H:%M"
        ).time()
        self.end_time = datetime.strptime(
            config['trading']['window']['end'], "%H:%M"
        ).time()
        self.sq_off_time = datetime.strptime(
            config['trading']['window']['auto_square_off'], "%H:%M"
        ).time()

        self.max_loss_per_day = config['risk']['max_loss_per_day']

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_latest_candle(self, df, t):
        """O(log n) lookup: latest candle at or before time t."""
        if df is None or df.empty:
            return None
        idx = df['datetime'].searchsorted(pd.Timestamp(t), side='right') - 1
        return None if idx < 0 else df.iloc[idx]

    def _get_closed_candle(self, df, bar_time):
        """Return the candle whose datetime == bar_time exactly."""
        if df is None or df.empty:
            return None
        matches = df[df['datetime'] == pd.Timestamp(bar_time)]
        return matches.iloc[0] if not matches.empty else None

    def _round_to_tick(self, price):
        tick = self.config['indices']['NIFTY']['tick_size']
        return round(price / tick) * tick

    def _get_slippage_ticks(self):
        cfg = self.config.get('reporting', {})
        if not cfg.get('slippage_buffer_enabled', False):
            return 0, 0
        ticks = cfg.get('slippage_ticks_per_side', 1)
        tick_size = self.config['indices']['NIFTY']['tick_size']
        return ticks, tick_size

    def _apply_entry_slippage(self, price):
        ticks, tick_size = self._get_slippage_ticks()
        if ticks > 0:
            price += ticks * tick_size
        return self._round_to_tick(price)

    def _apply_exit_slippage(self, price):
        ticks, tick_size = self._get_slippage_ticks()
        if ticks > 0:
            price -= ticks * tick_size
        return self._round_to_tick(price)

    # ── Main Loop ────────────────────────────────────────────────────────────

    def run(self, start_date, end_date):
        self.logger.info(f"Starting NIFTY Futures RSI-60 backtest: {start_date} to {end_date}")
        self.capital = self.config['capital']['initial']
        self.trades = []
        self.day_diagnostics = []

        current_date = start_date
        while current_date <= end_date:
            sys.stdout.write(f"\r[FuturesBacktest] Processing {current_date.date()} ... ")
            sys.stdout.flush()

            if not is_trading_day(current_date):
                current_date += pd.Timedelta(days=1)
                continue

            self._process_day(current_date)
            self.dm.clear_cache()
            current_date += pd.Timedelta(days=1)

        sys.stdout.write("\n")
        sys.stdout.flush()
        return self.generate_report()

    def _process_day(self, date):
        """Process a single trading day."""
        diag = {
            'date': date.strftime('%Y-%m-%d'),
            'candles_processed': 0,
            'alerts_fired': 0,
            'entries_attempted': 0,
            'trades_opened': 0,
        }

        # RSI warmup: fetch enough history for stable calculation
        period = self.config['strategy']['rsi']['period']
        warmup_candles = self.config['strategy']['rsi'].get('warmup_periods', period * 10)
        calendar_buffer = max(ceil(warmup_candles * 15 / 375) * 2, 5)
        warmup_start = date - timedelta(days=calendar_buffer)

        # Fetch spot data with warmup
        spot_df = self.dm.get_spot_candles(
            'NIFTY', warmup_start, date.replace(hour=23, minute=59)
        )
        if spot_df.empty:
            self.logger.warning(f"No NIFTY spot data for {date.date()}")
            return

        spot_df = spot_df.sort_values('datetime').reset_index(drop=True)

        # Pre-calculate full RSI series
        rsi_values = self.strategy.calculate_wilder_rsi(spot_df['close'].values)
        if rsi_values is None:
            self.logger.warning(f"Insufficient data for RSI on {date.date()}")
            return

        # Reset strategy state for new day
        self.strategy.reset_for_day()

        # Filter to today's candles only (after 09:15 at minimum)
        backtest_date = date.date()
        timestamps = sorted(spot_df['datetime'].unique())
        timestamps = [
            t for t in timestamps
            if t.date() == backtest_date and t.time() >= self.start_time
        ]

        active_trade = None
        has_traded_today = False
        day_pnl = 0

        for t in timestamps:
            # Square-off time check
            if t.time() >= self.sq_off_time:
                if active_trade:
                    pnl = self._close_trade(active_trade, t, "SQ_OFF", spot_df)
                    day_pnl += pnl
                    self.trades.append(active_trade)
                    active_trade = None
                break

            # ── 1. Manage active trade ───────────────────────────────────
            if active_trade:
                trade_pnl = self._manage_active_trade(active_trade, t, spot_df)

                if active_trade['status'] == 'CLOSED':
                    self.trades.append(active_trade)
                    day_pnl += trade_pnl
                    active_trade = None

                    if day_pnl <= -self.max_loss_per_day:
                        self.logger.warning(
                            f"[STOP] Daily loss limit reached: {day_pnl:.2f}. Done for today."
                        )
                        break
                continue  # Don't look for new signals while in a trade

            # Skip new entries if already traded or loss limit hit
            if has_traded_today:
                continue
            if day_pnl <= -self.max_loss_per_day:
                break

            signal_end = datetime.strptime(
                self.config['strategy'].get('signal_window_end', '14:45'), "%H:%M"
            ).time()
            if t.time() > signal_end:
                continue

            # ── 2. Check for entry on existing alert ────────────────────
            if self.strategy.alert is not None:
                # Age the alert
                if self.strategy.last_processed is not None and t > self.strategy.last_processed:
                    if t > self.strategy.alert_time:
                        self.strategy.alert_age += 1
                        if self.strategy.alert_age > self.strategy.alert_validity:
                            self.logger.info(
                                f"Alert expired at {t} (age={self.strategy.alert_age})"
                            )
                            self.strategy.consume_alert()

                self.strategy.last_processed = t

                if self.strategy.alert is not None:
                    current_candle = self._get_closed_candle(spot_df, t)
                    if current_candle is not None:
                        entry_signal = self.strategy.check_entry(current_candle)
                        if entry_signal:
                            diag['entries_attempted'] += 1
                            active_trade = self._enter_trade(entry_signal, t, date)
                            if active_trade:
                                diag['trades_opened'] += 1
                                has_traded_today = True
                                self.strategy.consume_alert()
                continue

            # ── 3. Check for new alert ──────────────────────────────────
            self.strategy.last_processed = t

            # Use the CLOSED candle (the one that just completed)
            closed_candle_time = t - timedelta(minutes=15)
            row = self._get_closed_candle(spot_df, closed_candle_time)
            if row is None:
                continue

            # RSI indexing: rsi_values[i] uses close[0..i+1]
            curr_idx = row.name
            if curr_idx < 2 or curr_idx - 1 >= len(rsi_values):
                continue

            curr_rsi = rsi_values[curr_idx - 1]
            prev_rsi = rsi_values[curr_idx - 2]

            if np.isnan(curr_rsi):
                continue

            diag['candles_processed'] += 1

            alert = self.strategy.check_alert(row, curr_rsi, prev_rsi)
            if alert:
                diag['alerts_fired'] += 1
                self.strategy.alert = alert
                self.strategy.alert_age = 0
                self.strategy.alert_time = t

        self.day_diagnostics.append(diag)

    # ── Trade Execution ──────────────────────────────────────────────────────

    def _enter_trade(self, signal, time, date):
        """Open a long position in NIFTY Futures."""
        trade_date = date.date() if hasattr(date, 'date') else date

        # Historical lot size lookup
        try:
            lot_size = get_historical_lot_size('NIFTY', trade_date)
        except (ValueError, Exception) as e:
            self.logger.warning(f"Lot size lookup failed for {trade_date}: {e}")
            lot_size = self.config['indices']['NIFTY'].get('lot_size', 65)

        lots = self.config['strategy'].get('lots_per_trade', 1)
        total_qty = lot_size * lots

        # Apply entry slippage
        entry_price = self._apply_entry_slippage(signal['entry_price'])
        sl = self._round_to_tick(signal['sl'])
        targets = [self._round_to_tick(t) for t in signal['targets']]

        cost = entry_price * total_qty

        # Capital check (margin-based for futures)
        margin_required = 200000 * lots  # Rs.2L per lot margin
        if self.capital < margin_required:
            self.logger.info(
                f"Skipping: Insufficient margin ({self.capital:.0f} < {margin_required})"
            )
            return None

        # For futures: track margin deployment, not full notional
        # P&L is computed on exit as (exit - entry) * qty
        self.capital -= margin_required

        trade = {
            'symbol': f'NIFTY-FUT-{trade_date}',
            'underlying': 'NIFTY',
            'entry_time': time,
            'entry_price': entry_price,
            'sl': sl,
            'original_sl': sl,
            'targets': targets,
            'qty': total_qty,
            'remaining_qty': total_qty,
            'tp_hits': 0,
            'partial_pnl': 0,
            'status': 'OPEN',
            'pnl': 0,
            'cost': cost,
            'lot_size': lot_size,
            'alert_range': signal['alert_range'],
            'alert_high': signal['alert_high'],
            'alert_low': signal['alert_low'],
            'running_capital': self.capital,
            'opt_type': 'FUT',
            'margin_deployed': margin_required,
        }

        self.logger.info(
            f"ENTRY: NIFTY-FUT at {entry_price:.2f} | Qty={total_qty} "
            f"({lots}x{lot_size}) | SL={sl:.2f} | T1={targets[0]:.2f}"
        )
        return trade

    def _manage_active_trade(self, trade, time, spot_df):
        """
        Manage SL/TP for active trade using multi-target trailing logic.

        Trail scheme (matches existing options strategy):
          - T1 hit -> SL moves to entry (break-even)
          - T2 hit -> SL moves to T1 price
          - T3 hit -> full exit
          - SL hit -> exit all remaining
        """
        # Use the closed candle (completed bar)
        closed_time = time - timedelta(minutes=15)
        row = self._get_closed_candle(spot_df, closed_time)
        if row is None:
            return 0

        realized_pnl = 0

        exit_mode = self.config['strategy'].get('exit_mode', 'single_lot')
        lots_per_trade = self.config['strategy'].get('lots_per_trade', 1)

        # Check SL
        sl_triggered = row['low'] <= trade['sl']

        # If SL trailed above entry, check targets first (priority)
        trailed_above_entry = trade['sl'] > trade['entry_price']

        # ── Target Checks ───────────────────────────────────────────────
        if exit_mode == 'multi_lot' and lots_per_trade >= 3:
            lot_size = trade['lot_size']

            for tp_level in range(trade['tp_hits'], len(trade['targets'])):
                if row['high'] < trade['targets'][tp_level]:
                    break

                if tp_level < len(trade['targets']) - 1:
                    # Partial exit
                    exit_qty = lot_size
                    exit_price = self._apply_exit_slippage(
                        max(row['open'], trade['targets'][tp_level])
                    )
                    pnl = (exit_price - trade['entry_price']) * exit_qty
                    trade['remaining_qty'] -= exit_qty
                    trade['partial_pnl'] = trade.get('partial_pnl', 0) + pnl
                    trade['tp_hits'] = tp_level + 1

                    # Trail SL
                    if tp_level == 0:
                        trade['sl'] = self._round_to_tick(trade['entry_price'])
                    elif tp_level == 1:
                        trade['sl'] = self._round_to_tick(trade['targets'][0])

                    # Futures: partial P&L adjusts capital (no margin partial release)
                    self.capital += pnl
                    self.logger.info(
                        f"PARTIAL EXIT TP{tp_level+1}: Qty={exit_qty} "
                        f"Price={exit_price:.2f} PnL={pnl:.2f} NewSL={trade['sl']:.2f}"
                    )
                else:
                    # TP3: full exit
                    exit_qty = trade['remaining_qty']
                    exit_price = self._apply_exit_slippage(
                        max(row['open'], trade['targets'][tp_level])
                    )
                    pnl = (exit_price - trade['entry_price']) * exit_qty
                    realized_pnl = pnl + trade.get('partial_pnl', 0)
                    # Futures: return margin + total realized P&L
                    self.capital += trade.get('margin_deployed', margin_required) + realized_pnl

                    trade['exit_time'] = time
                    trade['exit_price'] = exit_price
                    trade['reason'] = 'TARGET'
                    trade['status'] = 'CLOSED'
                    trade['pnl'] = realized_pnl
                    trade['remaining_qty'] = 0
                    trade['running_capital'] = self.capital
                    self.logger.info(
                        f"FULL EXIT TP3: Price={exit_price:.2f} TotalPnL={realized_pnl:.2f}"
                    )
                    return realized_pnl
        else:
            # Single lot: trail at intermediate TPs, full exit at configured target
            target_idx = self.config['strategy'].get('single_lot_exit_target', 3) - 1
            target_idx = min(target_idx, len(trade['targets']) - 1)

            # Sequential TP trail
            for tp in range(trade.get('tp_hits', 0), target_idx):
                if row['high'] >= trade['targets'][tp]:
                    if tp == 0:
                        trade['sl'] = self._round_to_tick(trade['entry_price'])
                    elif tp == 1:
                        trade['sl'] = self._round_to_tick(trade['targets'][0])
                    trade['tp_hits'] = tp + 1
                    self.logger.info(
                        f"TRAIL TP{tp+1}: SL moved to {trade['sl']:.2f}"
                    )
                else:
                    break

            # Final target exit
            if row['high'] >= trade['targets'][target_idx]:
                exit_price = self._apply_exit_slippage(
                    max(row['open'], trade['targets'][target_idx])
                )
                pnl = (exit_price - trade['entry_price']) * trade['qty']
                # Futures: return margin + P&L
                self.capital += trade.get('margin_deployed', 200000) + pnl

                trade['exit_time'] = time
                trade['exit_price'] = exit_price
                trade['reason'] = f'TP{target_idx+1}'
                trade['status'] = 'CLOSED'
                trade['pnl'] = pnl
                trade['running_capital'] = self.capital
                self.logger.info(
                    f"EXIT TP{target_idx+1}: Price={exit_price:.2f} PnL={pnl:.2f}"
                )
                return pnl

        # ── SL Check (after targets, to honor trailed-above-entry priority) ──
        if sl_triggered and not (trailed_above_entry and trade['tp_hits'] < len(trade['targets'])):
            remaining = trade['remaining_qty']
            exit_price = self._apply_exit_slippage(
                min(row['open'], trade['sl'])
            )
            partial = trade.get('partial_pnl', 0)
            pnl = (exit_price - trade['entry_price']) * remaining + partial
            # Futures: return margin + P&L
            self.capital += trade.get('margin_deployed', 200000) + pnl

            trade['exit_time'] = time
            trade['exit_price'] = exit_price
            trade['reason'] = 'SL'
            trade['status'] = 'CLOSED'
            trade['pnl'] = pnl
            trade['remaining_qty'] = 0
            trade['running_capital'] = self.capital
            self.logger.info(
                f"EXIT SL: Price={exit_price:.2f} PnL={pnl:.2f}"
            )
            return pnl

        # Re-check SL for non-trailed case
        if sl_triggered and not trailed_above_entry:
            remaining = trade['remaining_qty']
            exit_price = self._apply_exit_slippage(
                min(row['open'], trade['sl'])
            )
            partial = trade.get('partial_pnl', 0)
            pnl = (exit_price - trade['entry_price']) * remaining + partial
            # Futures: return margin + P&L
            self.capital += trade.get('margin_deployed', 200000) + pnl

            trade['exit_time'] = time
            trade['exit_price'] = exit_price
            trade['reason'] = 'SL'
            trade['status'] = 'CLOSED'
            trade['pnl'] = pnl
            trade['remaining_qty'] = 0
            trade['running_capital'] = self.capital
            return pnl

        return 0

    def _close_trade(self, trade, time, reason, spot_df):
        """Force close a trade (e.g., at square-off time)."""
        row = self._get_latest_candle(spot_df, time)
        if row is not None:
            exit_price = self._apply_exit_slippage(row['close'])
        else:
            exit_price = trade['entry_price']

        remaining = trade['remaining_qty']
        partial = trade.get('partial_pnl', 0)
        pnl = (exit_price - trade['entry_price']) * remaining + partial
        # Futures: return margin + P&L
        self.capital += trade.get('margin_deployed', 200000) + pnl

        trade['exit_time'] = time
        trade['exit_price'] = exit_price
        trade['reason'] = reason
        trade['status'] = 'CLOSED'
        trade['pnl'] = pnl
        trade['remaining_qty'] = 0
        trade['running_capital'] = self.capital

        self.logger.info(
            f"EXIT {reason}: Price={exit_price:.2f} PnL={pnl:.2f}"
        )
        return pnl

    # ── Reporting ────────────────────────────────────────────────────────────

    def generate_report(self):
        """Convert trades list to DataFrame for PerformanceReporter."""
        return pd.DataFrame(self.trades)

    def print_diagnostic_summary(self):
        """End-of-run diagnostic summary."""
        if not self.day_diagnostics:
            return

        total_days = len(self.day_diagnostics)
        days_with_alerts = sum(1 for d in self.day_diagnostics if d['alerts_fired'] > 0)
        days_with_trades = sum(1 for d in self.day_diagnostics if d['trades_opened'] > 0)

        self.logger.info(
            f"\n{'='*60}\n"
            f"NIFTY FUTURES RSI-60 BACKTEST DIAGNOSTICS\n"
            f"{'='*60}\n"
            f"Days processed:     {total_days}\n"
            f"Days with alerts:   {days_with_alerts}\n"
            f"Days with trades:   {days_with_trades}\n"
            f"Total trades:       {len(self.trades)}\n"
            f"Final Capital:      {self.capital:.2f}\n"
            f"{'='*60}"
        )
