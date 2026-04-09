# reporting/performance.py
import pandas as pd
import numpy as np
import logging
from datetime import datetime
import os
import json

class PerformanceReporter:
    def __init__(self, config=None):
        self.logger = logging.getLogger("Performance")
        self.config = config or {}

        # Default charges if not in config
        defaults = {
            'brokerage_per_trade': 20,
            'stt': 0.0005,
            'exchange_txn_fee': 0.00053,
            'gst': 0.18,
            'sebi_charges': 0.0001,
            'stamp_duty': 0.00003
        }

        # Override with values from config.yaml
        self.charges = defaults.copy()
        if 'charges' in self.config:
            self.logger.info("Using custom trading charges from config.yaml")
            self.charges.update(self.config['charges'])

        # Reports directory
        self.reports_dir = "reports"
        os.makedirs(self.reports_dir, exist_ok=True)

    def calculate_charges(self, entry_price, exit_price, quantity):
        """Calculate total trading charges for a trade"""
        entry_value = entry_price * quantity
        exit_value = exit_price * quantity
        total_turnover = entry_value + exit_value

        # Brokerage (flat per trade, both entry + exit)
        brokerage = self.charges['brokerage_per_trade'] * 2

        # STT (on sell side only for options)
        stt = exit_value * self.charges['stt']

        # Exchange transaction charges
        exchange_fee = total_turnover * self.charges['exchange_txn_fee']

        # GST (on brokerage + exchange fee)
        gst = (brokerage + exchange_fee) * self.charges['gst']

        # SEBI charges
        sebi = total_turnover * self.charges['sebi_charges']

        # Stamp duty (on buy side)
        stamp = entry_value * self.charges['stamp_duty']

        total_charges = brokerage + stt + exchange_fee + gst + sebi + stamp

        return {
            'brokerage': brokerage,
            'stt': stt,
            'exchange_fee': exchange_fee,
            'gst': gst,
            'sebi': sebi,
            'stamp_duty': stamp,
            'total': total_charges
        }

    def calculate_advanced_stats(self, trades_df, initial_cap=None):
        """Calculate advanced performance statistics"""
        if trades_df.empty:
            return {}

        pnl = trades_df['pnl_net']
        win_trades = trades_df[trades_df['pnl_net'] > 0]
        loss_trades = trades_df[trades_df['pnl_net'] < 0]

        # Basic stats
        total_trades = len(trades_df)
        winning_trades = len(win_trades)
        losing_trades = len(loss_trades)
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

        # P&L stats
        total_pnl = pnl.sum()
        avg_pnl = pnl.mean()
        avg_win = win_trades['pnl_net'].mean() if not win_trades.empty else 0
        avg_loss = abs(loss_trades['pnl_net'].mean()) if not loss_trades.empty else 0

        # Profit Factor
        gross_profit = win_trades['pnl_net'].sum() if not win_trades.empty else 0
        gross_loss = abs(loss_trades['pnl_net'].sum()) if not loss_trades.empty else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Drawdown — use running_capital (actual equity) if available;
        # fallback to initial_cap-based calculation.
        if 'running_capital' in trades_df.columns and initial_cap is not None:
            # Shift running_capital to represent equity AFTER exit for each trade
            # (In intraday_engine, it's captured both at entry and exit, but we want the sequence of equity levels)
            equity_after_trades = trades_df['running_capital'].tolist()
            cap_series = pd.Series([float(initial_cap)] + equity_after_trades)

            peak_cap = cap_series.cummax()
            drawdown_cap = cap_series - peak_cap
            max_drawdown = drawdown_cap.min()

            # Use initial_cap as baseline for DD% if requested, or peak_cap (standard)
            # Default to initial_cap to satisfy user requirement of avoiding hardcoded/peak-only logic
            denom = float(initial_cap)
            max_drawdown_pct = (max_drawdown / denom * 100) if denom > 0 else 0
        else:
            cum_pnl = pnl.cumsum()
            peak = cum_pnl.cummax()
            drawdown = cum_pnl - peak
            max_drawdown = drawdown.min()
            denom = float(initial_cap) if initial_cap and initial_cap > 0 else 100000
            max_drawdown_pct = (max_drawdown / denom * 100)

        # Risk-adjusted metrics
        std_pnl = pnl.std() if len(pnl) > 1 else 0

        # Sharpe Ratio (annualized)
        # n_annual = estimated number of trades per year at the observed trading frequency.
        # Used to scale the per-trade Sharpe to an annualized figure via sqrt(n_annual).
        if len(trades_df) >= 2 and 'entry_time' in trades_df.columns:
            try:
                first_trade = pd.to_datetime(trades_df['entry_time'].iloc[0])
                last_trade = pd.to_datetime(trades_df['entry_time'].iloc[-1])
                date_span_days = max((last_trade - first_trade).days, 1)
                # Approximate trading days in the span (252 trading days per calendar year)
                trading_days_in_span = date_span_days * (252 / 365)
                trades_per_year = total_trades * (252 / max(trading_days_in_span, 1))
                # Cap at reasonable bounds: no fewer than 10, no more than 500 trades/year
                n_annual = max(min(trades_per_year, 500), 10)
            except Exception:
                n_annual = 52  # fallback: weekly expiry strategy
        else:
            n_annual = 52  # fallback for small samples

        annualization_factor = np.sqrt(n_annual)

        if std_pnl > 0:
            sharpe_ratio = (avg_pnl / std_pnl) * annualization_factor
        else:
            sharpe_ratio = 0

        # Sortino Ratio (using downside deviation — same annualization_factor)
        negative_returns = pnl[pnl < 0]
        downside_std = negative_returns.std() if len(negative_returns) > 1 else 0
        if downside_std > 0:
            sortino_ratio = (avg_pnl / downside_std) * annualization_factor
        else:
            sortino_ratio = 0

        # Calmar Ratio
        if abs(max_drawdown) > 0:
            calmar_ratio = total_pnl / abs(max_drawdown)
        else:
            calmar_ratio = 0

        # Expectancy
        expectancy = (win_rate/100 * avg_win) - ((1 - win_rate/100) * avg_loss)

        # Risk/Reward Ratio
        risk_reward = avg_win / avg_loss if avg_loss > 0 else 0

        # Win/Loss streaks
        streaks = []
        current_streak = 0
        current_type = None
        for p in pnl:
            is_win = p > 0
            if current_type is None:
                current_type = is_win
                current_streak = 1
            elif is_win == current_type:
                current_streak += 1
            else:
                streaks.append((current_type, current_streak))
                current_type = is_win
                current_streak = 1
        streaks.append((current_type, current_streak))

        win_streaks = [s[1] for s in streaks if s[0]]
        loss_streaks = [s[1] for s in streaks if not s[0]]
        max_win_streak = max(win_streaks) if win_streaks else 0
        max_loss_streak = max(loss_streaks) if loss_streaks else 0

        # Largest win/loss
        largest_win = pnl.max()
        largest_loss = pnl.min()

        # Holding period (if timestamps available)
        try:
            trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])
            trades_df['exit_time'] = pd.to_datetime(trades_df['exit_time'])
            trades_df['duration'] = (trades_df['exit_time'] - trades_df['entry_time']).dt.total_seconds() / 60
            avg_holding_mins = trades_df['duration'].mean()
        except:
            avg_holding_mins = 0

        return {
            # Basic
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': round(win_rate, 2),

            # P&L
            'total_pnl': round(total_pnl, 2),
            'avg_pnl_per_trade': round(avg_pnl, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'largest_win': round(largest_win, 2),
            'largest_loss': round(largest_loss, 2),

            # Risk
            'profit_factor': round(profit_factor, 2) if profit_factor != float('inf') else 'inf',
            'risk_reward_ratio': round(risk_reward, 2),
            'expectancy': round(expectancy, 2),

            # Drawdown
            'max_drawdown': round(max_drawdown, 2),
            'max_drawdown_pct': round(max_drawdown_pct, 2),

            # Risk-adjusted
            'sharpe_ratio': round(sharpe_ratio, 2),
            'sortino_ratio': round(sortino_ratio, 2),
            'calmar_ratio': round(calmar_ratio, 2),

            # Streaks
            'max_win_streak': max_win_streak,
            'max_loss_streak': max_loss_streak,

            # Timing
            'avg_holding_mins': round(avg_holding_mins, 1),

            # Capital Deployment
            'avg_capital_deployed': round(trades_df['cost'].mean(), 2) if 'cost' in trades_df.columns else 0,
            'max_capital_deployed': round(trades_df['cost'].max(), 2) if 'cost' in trades_df.columns else 0,

            # Volatility
            'pnl_std_dev': round(std_pnl, 2)
        }

    def generate_report(self, trades_df, save_to_file=True):
        """Generate comprehensive performance report with trading charges"""
        if trades_df.empty:
            self.logger.info("No trades generated.")
            return None

        # Calculate trading charges for each trade
        # Ensure cost column exists (entry_price * qty)
        if 'cost' not in trades_df.columns:
            trades_df['cost'] = trades_df['entry_price'] * trades_df['qty']

        # Read exit config once, outside the loop
        exit_mode = self.config.get('strategy', {}).get('exit_mode', 'single_lot')
        lots_per_trade = self.config.get('strategy', {}).get('lots_per_trade', 1)

        charges_list = []
        for idx, trade in trades_df.iterrows():
            charges = self.calculate_charges(
                trade['entry_price'],
                trade['exit_price'],
                trade['qty']
            )

            # Multi-lot trades have extra exit legs: TP1 and TP2 are separate orders
            # from the final exit, each incurring ₹20 brokerage.
            # single_lot: 1 entry + 1 exit = ₹40 (covered by calculate_charges)
            # multi_lot:  1 entry + TP1 + TP2 + TP3 = ₹80 (2 extra legs added here)
            if exit_mode == 'multi_lot' and lots_per_trade >= 3:
                extra_exits = 2  # TP1 and TP2 are separate from the final TP3 exit
                extra_brokerage = self.charges['brokerage_per_trade'] * extra_exits
                charges['brokerage'] += extra_brokerage
                charges['total'] += extra_brokerage

            charges_list.append(charges)

        # Add charges to dataframe
        trades_df['charges'] = [c['total'] for c in charges_list]
        trades_df['pnl_gross'] = trades_df['pnl']

        # P-28 / V16-P-04: Apply configurable slippage buffer per trade
        slip_cfg = self.config.get('reporting', {})
        slip_enabled = slip_cfg.get('slippage_buffer_enabled', False)
        slip_model = slip_cfg.get('slippage_model', 'flat')

        if slip_enabled:
            if slip_model == 'position_scaled':
                # V16-P-04: Position-scaled slippage
                ticks_per_side = slip_cfg.get('slippage_ticks_per_side', 1)
                slip_min = float(slip_cfg.get('slippage_min_per_trade', 50))
                slip_max = float(slip_cfg.get('slippage_max_per_trade', 500))

                slippage_vals = []
                for _, trade in trades_df.iterrows():
                    underlying = trade.get('underlying', 'NIFTY')
                    tick = self.config.get('indices', {}).get(underlying, {}).get('tick_size', 0.05)
                    qty = trade.get('qty', 1)
                    slip = ticks_per_side * tick * qty * 2  # 2 sides (entry + exit)
                    slip = max(slip_min, min(slip_max, slip))
                    slippage_vals.append(slip)

                trades_df['slippage'] = slippage_vals
                self.logger.info(
                    f"Position-scaled slippage applied: "
                    f"avg=Rs.{trades_df['slippage'].mean():.2f}/trade, "
                    f"total=Rs.{trades_df['slippage'].sum():.2f}"
                )
            else:
                # Flat model (backward compatible)
                slip_amount = float(slip_cfg.get('slippage_buffer_per_trade', 0))
                trades_df['slippage'] = slip_amount
                self.logger.info(
                    f"Flat slippage buffer applied: Rs.{slip_amount}/trade x "
                    f"{len(trades_df)} trades = Rs.{trades_df['slippage'].sum():.2f} total"
                )

            trades_df['pnl_net'] = (trades_df['pnl_gross']
                                   - trades_df['charges']
                                   - trades_df['slippage'])
        else:
            trades_df['slippage'] = 0.0
            trades_df['pnl_net'] = trades_df['pnl_gross'] - trades_df['charges']

        # Calculate all statistics
        initial_cap = self.config.get('capital', {}).get('initial', None)
        stats = self.calculate_advanced_stats(trades_df, initial_cap=initial_cap)
        total_charges = trades_df['charges'].sum()
        total_slippage = trades_df['slippage'].sum()


        # Print comprehensive console report
        print("\n" + "="*70)
        print(" BACKTEST PERFORMANCE REPORT")
        print("="*70)

        # Config parameters
        if self.config:
            print("\n STRATEGY PARAMETERS")
            print("-"*70)
            if 'backtest' in self.config:
                bt = self.config['backtest']
                print(f"  Period:          {bt.get('start_date', 'N/A')} to {bt.get('end_date', 'N/A')}")
            if 'strategy' in self.config:
                st = self.config['strategy']
                print(f"  RSI Period:      {st.get('rsi', {}).get('period', 'N/A')}")
                print(f"  RSI Threshold:   {st.get('rsi', {}).get('threshold', 'N/A')}")
                print(f"  Exit Mode:       {st.get('exit_mode', 'N/A')}")
                print(f"  Lots/Trade:      {st.get('lots_per_trade', 'N/A')}")
            if 'capital' in self.config:
                print(f"  Initial Capital: Rs.{self.config['capital'].get('initial', 'N/A'):,}")

        print("\n TRADE STATISTICS")
        print("-"*70)
        print(f"  Total Trades:    {stats['total_trades']}")
        print(f"  Winning Trades:  {stats['winning_trades']} ({stats['win_rate']}%)")
        print(f"  Losing Trades:   {stats['losing_trades']}")
        print(f"  Win/Loss Streak: {stats['max_win_streak']} / {stats['max_loss_streak']}")

        print("\n PROFIT & LOSS")
        print("-"*70)
        print(f"  Gross P&L:       Rs.{trades_df['pnl_gross'].sum():,.2f}")
        print(f"  Total Charges:   Rs.{total_charges:,.2f}")
        if total_slippage > 0:
            avg_slip = total_slippage / max(1, len(trades_df))
            print(f"  Slippage Buffer: Rs.{total_slippage:,.2f}  (Avg Rs.{avg_slip:.0f}/trade)")
        print(f"  Net P&L:         Rs.{stats['total_pnl']:,.2f}")
        print(f"  Avg P&L/Trade:   Rs.{stats['avg_pnl_per_trade']:,.2f}")
        print(f"  Avg Win:         Rs.{stats['avg_win']:,.2f}")
        print(f"  Avg Loss:        Rs.{stats['avg_loss']:,.2f}")
        print(f"  Largest Win:     Rs.{stats['largest_win']:,.2f}")
        print(f"  Largest Loss:    Rs.{stats['largest_loss']:,.2f}")

        print("\n RISK METRICS")
        print("-"*70)
        print(f"  Profit Factor:   {stats['profit_factor']}")
        print(f"  Risk/Reward:     {stats['risk_reward_ratio']}")
        print(f"  Expectancy:      Rs.{stats['expectancy']:,.2f}")
        print(f"  Max Drawdown:    Rs.{stats['max_drawdown']:,.2f} ({stats['max_drawdown_pct']}%)")
        print(f"  P&L Std Dev:     Rs.{stats['pnl_std_dev']:,.2f}")

        print("\n RISK-ADJUSTED RETURNS")
        print("-"*70)
        print(f"  Sharpe Ratio:    {stats['sharpe_ratio']}")
        print(f"  Sortino Ratio:   {stats['sortino_ratio']}")
        print(f"  Calmar Ratio:    {stats['calmar_ratio']}")

        print("\n TIMING")
        print("-"*70)
        print(f"  Avg Holding:     {stats['avg_holding_mins']} mins")

        print("="*70 + "\n")

        # Prepare report data
        report_data = {
            'config': self.config,
            'summary': stats,
            'charges_total': round(total_charges, 2),
            'trades': trades_df.to_dict('records')
        }

        # Save to file if requested
        if save_to_file:
            # Descriptive filename convention:
            # RSI-15m_2020-2025_P11_TH60_100k_20260406_1830.json

            # 1. Fetch parameters for filename
            bt_cfg = self.config.get('backtest', {})
            strat_cfg = self.config.get('strategy', {})
            rsi_cfg = strat_cfg.get('rsi', {})
            cap_cfg = self.config.get('capital', {})

            # Parse start/end year
            s_year = pd.to_datetime(bt_cfg.get('start_date', '2020')).year
            e_year = pd.to_datetime(bt_cfg.get('end_date', '2025')).year

            # RSI Parameters
            rsi_p = rsi_cfg.get('period', 11)
            rsi_t = rsi_cfg.get('threshold', 60)

            # Exit Mode & Target
            mode = "SINGLE" if strat_cfg.get('exit_mode') == 'single_lot' else "MULTI"
            tgt = strat_cfg.get('single_lot_exit_target', 1) if mode == "SINGLE" else "123"

            # Capital (e.g. 500000 -> 500k)
            cap_val = cap_cfg.get('initial', 100000)
            cap_str = f"{int(cap_val/1000)}k" if cap_val >= 1000 else str(cap_val)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M")

            # Base prefix for related files:
            # RSI-15m_2020-2025_P11_TH60_SINGLE_T1_500k_20260406_1854
            prefix = f"RSI-15m_{s_year}-{e_year}_P{rsi_p}_TH{rsi_t}_{mode}_T{tgt}_{cap_str}_{timestamp}"

            # Save summary JSON
            json_filename = os.path.join(self.reports_dir, f"{prefix}_summary.json")
            with open(json_filename, 'w') as f:
                json.dump(report_data, f, indent=2, default=str)
            self.logger.info(f"Summary report saved to: {json_filename}")

            # Generate PNG report (non-overlapping layout)
            img_filename = os.path.join(self.reports_dir, f"{prefix}.png")
            self._generate_report_image(trades_df, stats, img_filename)
            self.logger.info(f"PNG report saved to: {img_filename}")

            # Generate interactive HTML report
            html_filename = os.path.join(self.reports_dir, f"{prefix}.html")
            self._generate_html_report(trades_df, stats, html_filename)
            self.logger.info(f"HTML report saved to: {html_filename}")

            print(f"\n Reports saved to '{self.reports_dir}' directory")
            print(f"   - JSON: {json_filename}")
            print(f"   - PNG:  {img_filename}")
            print(f"   - HTML: {html_filename}\n")

        return report_data

    def _generate_report_image(
        self,
        trades_df: pd.DataFrame,
        stats: dict,
        filepath: str
    ) -> str:
        """
        Generate a clean, non-overlapping PNG with 6-panel layout:
        Row 1: Equity Curve | Stats Panel
        Row 2: P&L Per Trade | Monthly P&L
        Row 3: Win/Loss Distribution | Drawdown Timeline
        """
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            from matplotlib.figure import Figure
            from matplotlib.gridspec import GridSpec
            import matplotlib.ticker as mticker
        except ImportError:
            self.logger.warning("matplotlib not installed. Cannot generate PNG report.")
            return ""

        fig = Figure(figsize=(20, 16), dpi=130, facecolor='#1a1a2e')

        if trades_df.empty:
            ax = fig.add_subplot(111)
            ax.text(0.5, 0.5, "No trades in period", ha='center', va='center', fontsize=20, color='white')
            ax.set_facecolor('#1a1a2e')
            ax.axis('off')
            fig.savefig(filepath, bbox_inches='tight', facecolor=fig.get_facecolor())
            return filepath

        # Layout: 3 rows, 2 columns with generous spacing
        gs = GridSpec(3, 2, figure=fig, width_ratios=[1.6, 1], height_ratios=[1.1, 0.9, 0.8])
        gs.update(wspace=0.25, hspace=0.40, left=0.06, right=0.96, top=0.90, bottom=0.06)

        # Dark theme colors
        bg_dark = '#16213e'
        bg_card = '#0f3460'
        c_green = '#00d166'
        c_red = '#ff4757'
        c_cyan = '#00d2ff'
        c_gold = '#ffd700'
        c_gray = '#8892b0'
        c_text = '#e6f1ff'
        c_muted = '#a8b2d1'

        # Date strings and capital from config
        bt_cfg = self.config.get('backtest', {})
        start_dt_str = bt_cfg.get('start_date', trades_df['entry_time'].iloc[0] if not trades_df.empty else 'N/A')
        end_dt_str = bt_cfg.get('end_date', trades_df['exit_time'].iloc[-1] if not trades_df.empty else 'N/A')

        start_dt = pd.to_datetime(start_dt_str)
        end_dt = pd.to_datetime(end_dt_str)
        initial_cap = self.config.get('capital', {}).get('initial', 100000)

        net_pnl = stats['total_pnl']
        ret_pct = (net_pnl / initial_cap * 100) if initial_cap > 0 else 0
        pnl_color = c_green if net_pnl >= 0 else c_red

        fig.suptitle(
            f"RSI-15m Backtest Report  |  {start_dt.strftime('%b %d %Y')} - {end_dt.strftime('%b %d %Y')}"
            f"  |  {stats['total_trades']} trades  |  "
            f"Net P&L: Rs.{net_pnl:,.0f} ({ret_pct:+.1f}%)",
            fontsize=15, fontweight='bold', color=c_text, y=0.96
        )

        def style_ax(ax, title=''):
            ax.set_facecolor(bg_dark)
            ax.tick_params(colors=c_muted, labelsize=9)
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['left'].set_color(c_gray)
            ax.spines['bottom'].set_color(c_gray)
            if title:
                ax.set_title(title, fontweight='bold', color=c_text, fontsize=12, pad=10)
            ax.grid(True, linestyle=':', alpha=0.2, color=c_gray)

        # ── Panel 1: Equity Curve ────────────────────────────────────────────
        ax1 = fig.add_subplot(gs[0, 0])
        style_ax(ax1, 'Equity Curve & Drawdown')

        trade_dates = pd.to_datetime(trades_df['exit_time'])
        equity = trades_df['running_capital']
        times = [start_dt] + trade_dates.tolist()
        eq_vals = [initial_cap] + equity.tolist()

        ax1.plot(times, eq_vals, color=c_cyan, linewidth=2.0, zorder=3)
        running_max = np.maximum.accumulate(eq_vals)
        ax1.plot(times, running_max, color=c_gray, linestyle='--', alpha=0.4, linewidth=1)
        ax1.fill_between(times, running_max, eq_vals,
                         where=[rm > ev for rm, ev in zip(running_max, eq_vals)],
                         color=c_red, alpha=0.15)
        ax1.fill_between(times, initial_cap, eq_vals,
                         where=[ev >= initial_cap for ev in eq_vals],
                         color=c_green, alpha=0.08)
        ax1.axhline(initial_cap, color=c_gold, linestyle=':', alpha=0.4, linewidth=1)
        ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'Rs.{x/1000:.0f}K'))
        ax1.tick_params(axis='x', rotation=0)

        # ── Panel 2: Stats Panel ─────────────────────────────────────────────
        ax2 = fig.add_subplot(gs[0, 1])
        ax2.set_facecolor(bg_dark)
        ax2.axis('off')

        gross = trades_df['pnl_gross'].sum()
        charges = gross - net_pnl
        slip_cfg = self.config.get('reporting', {}).get('slippage_buffer_enabled', False)
        slip_amt = self.config.get('reporting', {}).get('slippage_buffer_per_trade', 0) if slip_cfg else 0

        # Build stats as a structured table
        sections = [
            ("RETURNS", [
                ("Net P&L", f"Rs.{net_pnl:,.0f}", pnl_color),
                ("Gross P&L", f"Rs.{gross:,.0f}", c_text),
                ("Charges+Slip", f"Rs.{charges:,.0f}", c_muted),
                ("Return %", f"{ret_pct:+.1f}%", pnl_color),
                ("Best Trade", f"Rs.{stats['largest_win']:,.0f}", c_green),
                ("Worst Trade", f"Rs.{stats['largest_loss']:,.0f}", c_red),
            ]),
            ("RISK METRICS", [
                ("Win Rate", f"{stats['win_rate']}%", c_gold if stats['win_rate'] >= 40 else c_red),
                ("Profit Factor", f"{stats['profit_factor']}", c_green if float(str(stats['profit_factor']).replace('inf','999')) >= 1.1 else c_red),
                ("Sharpe", f"{stats['sharpe_ratio']}", c_text),
                ("Sortino", f"{stats['sortino_ratio']}", c_text),
                ("Max DD", f"Rs.{stats['max_drawdown']:,.0f} ({stats['max_drawdown_pct']}%)", c_red),
                ("Avg Capital", f"Rs.{stats['avg_capital_deployed']:,.0f}", c_cyan),
                ("Streaks W/L", f"{stats['max_win_streak']} / {stats['max_loss_streak']}", c_text),
                ("Avg Hold", f"{stats['avg_holding_mins']:.0f} min", c_muted),
            ]),
        ]

        # Build a single formatted text block for reliability
        lines = []
        for section_title, items in sections:
            lines.append(f"{'='*32}")
            lines.append(f"  {section_title}")
            lines.append(f"{'='*32}")
            for label, value, _ in items:
                lines.append(f"  {label:<16s} {value}")
            lines.append("")

        stats_text = '\n'.join(lines)
        ax2.text(0.05, 0.95, stats_text, fontsize=9.5, color=c_text,
                family='monospace', va='top', ha='left',
                transform=ax2.transAxes, linespacing=1.5,
                bbox=dict(boxstyle='round,pad=0.5', facecolor=bg_card,
                         edgecolor=c_gray, alpha=0.8))

        # ── Panel 3: P&L Per Trade Bars ──────────────────────────────────────
        ax3 = fig.add_subplot(gs[1, 0])
        style_ax(ax3, 'Net P&L Per Trade')

        pnl = trades_df['pnl_net']
        colors = [c_green if x > 0 else c_red for x in pnl]
        ax3.bar(range(1, len(pnl)+1), pnl, color=colors, width=0.7, alpha=0.85)
        ax3.axhline(0, color=c_text, linewidth=0.6, alpha=0.5)
        ax3.set_xlabel("Trade #", color=c_muted, fontsize=9)
        ax3.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'Rs.{x/1000:.1f}K'))

        # ── Panel 4: Monthly P&L ─────────────────────────────────────────────
        ax4 = fig.add_subplot(gs[1, 1])
        style_ax(ax4, 'Monthly Net P&L')

        trades_df_copy = trades_df.copy()
        trades_df_copy['month'] = pd.to_datetime(trades_df_copy['exit_time']).dt.to_period('M')
        monthly = trades_df_copy.groupby('month')['pnl_net'].sum()

        if not monthly.empty:
            m_colors = [c_green if x > 0 else c_red for x in monthly]
            month_labels = [str(m) for m in monthly.index]
            bars = ax4.bar(month_labels, monthly.values, color=m_colors, alpha=0.85)
            ax4.axhline(0, color=c_text, linewidth=0.6, alpha=0.5)
            ax4.tick_params(axis='x', rotation=45, labelsize=8)
            for bar in bars:
                height = bar.get_height()
                v_off = 200 if height >= 0 else -200
                ax4.text(bar.get_x() + bar.get_width()/2., height + v_off,
                        f'Rs.{int(height):,}', ha='center', va='bottom' if height >= 0 else 'top',
                        fontsize=7, fontweight='bold', color=c_text)

        # ── Panel 5: Win/Loss Distribution ───────────────────────────────────
        ax5 = fig.add_subplot(gs[2, 0])
        style_ax(ax5, 'P&L Distribution')

        win_pnl = pnl[pnl > 0]
        loss_pnl = pnl[pnl <= 0]
        bins = np.linspace(pnl.min(), pnl.max(), 25)
        if len(win_pnl) > 0:
            ax5.hist(win_pnl, bins=bins, color=c_green, alpha=0.7, label=f'Wins ({len(win_pnl)})')
        if len(loss_pnl) > 0:
            ax5.hist(loss_pnl, bins=bins, color=c_red, alpha=0.7, label=f'Losses ({len(loss_pnl)})')
        ax5.axvline(pnl.mean(), color=c_gold, linestyle='--', linewidth=1.5,
                   label=f'Avg: Rs.{pnl.mean():,.0f}')
        ax5.legend(fontsize=8, facecolor=bg_dark, edgecolor=c_gray, labelcolor=c_text)
        ax5.set_xlabel("P&L (Rs.)", color=c_muted, fontsize=9)
        ax5.set_ylabel("Frequency", color=c_muted, fontsize=9)

        # ── Panel 6: Drawdown Timeline ───────────────────────────────────────
        ax6 = fig.add_subplot(gs[2, 1])
        style_ax(ax6, 'Drawdown %')

        eq_series = pd.Series(eq_vals, index=times)
        peak_series = eq_series.cummax()
        dd_pct_png = ((eq_series - peak_series) / peak_series * 100)
        ax6.fill_between(dd_pct_png.index, dd_pct_png.values, 0, color=c_red, alpha=0.3)
        ax6.plot(dd_pct_png.index, dd_pct_png.values, color=c_red, linewidth=1.2)
        ax6.axhline(0, color=c_text, linewidth=0.5, alpha=0.3)
        ax6.set_ylabel("DD %", color=c_muted, fontsize=9)
        ax6.tick_params(axis='x', rotation=0, labelsize=8)
        ax6.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{x:.0f}%'))

        fig.savefig(filepath, bbox_inches='tight', facecolor=fig.get_facecolor(), edgecolor='none')
        return filepath

    def _generate_html_report(
        self,
        trades_df: pd.DataFrame,
        stats: dict,
        filepath: str
    ) -> str:
        """
        Generate an interactive HTML dashboard using Plotly.
        Features: hover tooltips, zoomable charts, full trade table.
        """
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
        except ImportError:
            self.logger.warning("plotly not installed. Skipping HTML report. Install: pip install plotly")
            return ""

        initial_cap = self.config.get('capital', {}).get('initial', 100000)
        bt_cfg = self.config.get('backtest', {})
        start_dt = bt_cfg.get('start_date', trades_df['entry_time'].iloc[0] if not trades_df.empty else '')
        end_dt = bt_cfg.get('end_date', trades_df['exit_time'].iloc[-1] if not trades_df.empty else '')

        net_pnl = stats['total_pnl']
        ret_pct = (net_pnl / initial_cap * 100) if initial_cap > 0 else 0

        trade_dates = pd.to_datetime(trades_df['exit_time'])
        equity = trades_df['running_capital'].tolist()
        times = [pd.to_datetime(start_dt)] + trade_dates.tolist()
        eq_vals = [initial_cap] + equity

        pnl = trades_df['pnl_net']

        # Monthly aggregation
        trades_copy = trades_df.copy()
        trades_copy['month'] = pd.to_datetime(trades_copy['exit_time']).dt.to_period('M').astype(str)
        monthly = trades_copy.groupby('month').agg(
            pnl_sum=('pnl_net', 'sum'),
            count=('pnl_net', 'count'),
            wins=('pnl_net', lambda x: (x > 0).sum())
        ).reset_index()

        # Drawdown
        eq_arr = np.array(eq_vals)
        peak_arr = np.maximum.accumulate(eq_arr)
        dd_pct = (eq_arr - peak_arr) / peak_arr * 100

        # Build figure: 4 rows, 2 cols
        fig = make_subplots(
            rows=4, cols=2,
            row_heights=[0.28, 0.24, 0.22, 0.26],
            column_widths=[0.6, 0.4],
            subplot_titles=[
                'Equity Curve', 'Key Metrics',
                'Net P&L Per Trade', 'Monthly P&L',
                'Drawdown %', 'P&L Distribution',
                'Trade Log', ''
            ],
            specs=[
                [{"type": "scatter"}, {"type": "table"}],
                [{"type": "bar"}, {"type": "bar"}],
                [{"type": "scatter"}, {"type": "histogram"}],
                [{"type": "table", "colspan": 2}, None],
            ],
            vertical_spacing=0.06,
            horizontal_spacing=0.08
        )

        # 1. Equity Curve
        fig.add_trace(go.Scatter(
            x=times, y=eq_vals,
            mode='lines', name='Equity',
            line=dict(color='#00d2ff', width=2.5),
            hovertemplate='Date: %{x}<br>Capital: Rs.%{y:,.0f}<extra></extra>'
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=times, y=peak_arr.tolist(),
            mode='lines', name='Peak',
            line=dict(color='#8892b0', width=1, dash='dash'),
            hoverinfo='skip'
        ), row=1, col=1)

        fig.add_hline(y=initial_cap, line_dash="dot", line_color="#ffd700",
                      annotation_text=f"Initial: Rs.{initial_cap:,}", row=1, col=1)

        # 2. Stats Table
        gross = trades_df['pnl_gross'].sum()
        pf_str = str(stats['profit_factor'])

        metric_names = [
            'Net P&L', 'Gross P&L', 'Return %', 'Win Rate', 'Profit Factor',
            'Sharpe', 'Sortino', 'Max Drawdown', 'Avg Capital', 'Avg Win',
            'Avg Loss', 'Best Trade', 'Worst Trade', 'Win Streak', 'Loss Streak', 'Avg Hold'
        ]
        metric_vals = [
            f'Rs.{net_pnl:,.0f}', f'Rs.{gross:,.0f}', f'{ret_pct:+.1f}%',
            f'{stats["win_rate"]}%', pf_str,
            str(stats['sharpe_ratio']), str(stats['sortino_ratio']),
            f'Rs.{stats["max_drawdown"]:,.0f} ({stats["max_drawdown_pct"]}%)',
            f'Rs.{stats["avg_capital_deployed"]:,.0f}',
            f'Rs.{stats["avg_win"]:,.0f}', f'Rs.{stats["avg_loss"]:,.0f}',
            f'Rs.{stats["largest_win"]:,.0f}', f'Rs.{stats["largest_loss"]:,.0f}',
            str(stats['max_win_streak']), str(stats['max_loss_streak']),
            f'{stats["avg_holding_mins"]:.0f} min'
        ]

        val_colors = []
        for v in metric_vals:
            if v.startswith('Rs.-') or v.startswith('-'):
                val_colors.append('#ff4757')
            elif v.startswith('Rs.') and not v.startswith('Rs.0'):
                val_colors.append('#00d166')
            else:
                val_colors.append('#e6f1ff')

        fig.add_trace(go.Table(
            header=dict(
                values=['Metric', 'Value'],
                fill_color='#0f3460',
                font=dict(color='#ffd700', size=12),
                align='left', height=30
            ),
            cells=dict(
                values=[metric_names, metric_vals],
                fill_color='#16213e',
                font=dict(color=[['#8892b0']*len(metric_names), val_colors], size=11),
                align='left', height=25
            )
        ), row=1, col=2)

        # 3. P&L Per Trade
        pnl_colors = ['#00d166' if x > 0 else '#ff4757' for x in pnl]
        fig.add_trace(go.Bar(
            x=list(range(1, len(pnl)+1)),
            y=pnl.values,
            marker_color=pnl_colors,
            name='Trade P&L',
            hovertemplate='Trade #%{x}<br>P&L: Rs.%{y:,.0f}<extra></extra>',
            showlegend=False
        ), row=2, col=1)

        # 4. Monthly P&L
        if not monthly.empty:
            m_colors = ['#00d166' if x > 0 else '#ff4757' for x in monthly['pnl_sum']]
            fig.add_trace(go.Bar(
                x=monthly['month'],
                y=monthly['pnl_sum'],
                marker_color=m_colors,
                name='Monthly P&L',
                text=[f'Rs.{v:,.0f}' for v in monthly['pnl_sum']],
                textposition='outside',
                textfont=dict(size=10),
                hovertemplate='%{x}<br>P&L: Rs.%{y:,.0f}<extra></extra>',
                showlegend=False
            ), row=2, col=2)

        # 5. Drawdown %
        fig.add_trace(go.Scatter(
            x=times, y=dd_pct.tolist(),
            fill='tozeroy',
            mode='lines',
            line=dict(color='#ff4757', width=1.5),
            fillcolor='rgba(255, 71, 87, 0.2)',
            name='Drawdown',
            hovertemplate='Date: %{x}<br>DD: %{y:.1f}%<extra></extra>',
            showlegend=False
        ), row=3, col=1)

        # 6. P&L Distribution
        fig.add_trace(go.Histogram(
            x=pnl[pnl > 0], nbinsx=20,
            marker_color='#00d166', opacity=0.7,
            name=f'Wins ({len(pnl[pnl > 0])})',
            hovertemplate='P&L: Rs.%{x}<br>Count: %{y}<extra></extra>'
        ), row=3, col=2)

        fig.add_trace(go.Histogram(
            x=pnl[pnl <= 0], nbinsx=20,
            marker_color='#ff4757', opacity=0.7,
            name=f'Losses ({len(pnl[pnl <= 0])})',
            hovertemplate='P&L: Rs.%{x}<br>Count: %{y}<extra></extra>'
        ), row=3, col=2)

        # 7. Trade Log Table
        trade_tbl = trades_df[['symbol', 'entry_time', 'exit_time', 'entry_price',
                               'exit_price', 'qty', 'cost', 'reason', 'pnl_gross', 'pnl_net']].copy()
        trade_tbl['entry_time'] = pd.to_datetime(trade_tbl['entry_time']).dt.strftime('%Y-%m-%d %H:%M')
        trade_tbl['exit_time'] = pd.to_datetime(trade_tbl['exit_time']).dt.strftime('%Y-%m-%d %H:%M')

        cell_colors_pnl = ['#00d166' if v > 0 else '#ff4757' for v in trade_tbl['pnl_net']]
        n_rows = len(trade_tbl)

        fig.add_trace(go.Table(
            header=dict(
                values=['Symbol', 'Entry Time', 'Exit Time', 'Entry Px', 'Exit Px',
                        'Qty', 'Capital', 'Reason', 'Gross P&L', 'Net P&L'],
                fill_color='#0f3460',
                font=dict(color='#ffd700', size=11),
                align='left', height=28
            ),
            cells=dict(
                values=[trade_tbl[c].tolist() for c in trade_tbl.columns],
                fill_color='#16213e',
                font=dict(
                    color=[['#e6f1ff']*n_rows, ['#e6f1ff']*n_rows, ['#e6f1ff']*n_rows,
                           ['#e6f1ff']*n_rows, ['#e6f1ff']*n_rows, ['#e6f1ff']*n_rows,
                           ['#ffd700']*n_rows, ['#e6f1ff']*n_rows, cell_colors_pnl, cell_colors_pnl],
                    size=10
                ),
                align='left', height=24
            )
        ), row=4, col=1)

        # Layout styling
        pnl_sign = '+' if net_pnl >= 0 else ''
        fig.update_layout(
            title=dict(
                text=(f"<b>RSI-15m Backtest Dashboard</b>  |  {start_dt} to {end_dt}  |  "
                      f"{stats['total_trades']} trades  |  "
                      f"<span style='color:{'#00d166' if net_pnl >= 0 else '#ff4757'}'>"
                      f"Net: Rs.{net_pnl:,.0f} ({pnl_sign}{ret_pct:.1f}%)</span>"),
                font=dict(size=16, color='#e6f1ff'),
                x=0.01
            ),
            template='plotly_dark',
            paper_bgcolor='#1a1a2e',
            plot_bgcolor='#16213e',
            font=dict(color='#e6f1ff', family='Segoe UI, sans-serif'),
            height=1600,
            showlegend=False,
            barmode='overlay'
        )

        # Write HTML
        fig.write_html(filepath, include_plotlyjs='cdn', full_html=True)

        # Auto-open in browser
        try:
            import webbrowser
            webbrowser.open(f'file:///{os.path.abspath(filepath)}')
        except Exception:
            pass

        return filepath
