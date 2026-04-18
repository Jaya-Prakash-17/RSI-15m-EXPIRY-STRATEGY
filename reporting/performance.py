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

        # Calculate cost (capital deployed) if not present
        if 'cost' not in trades_df.columns:
            trades_df['cost'] = trades_df['entry_price'] * trades_df['qty']

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

            # Generate Visual Trade Inspection Report (Detailed Charts)
            inspection_url = None
            try:
                # Dynamic import to avoid circular dependency or path issues
                import sys
                from pathlib import Path
                root = str(Path(__file__).parent.parent)
                if root not in sys.path: sys.path.append(root)

                from scripts.trade_inspector import generate_inspector_dashboard
                # The inspector expects the JSON path
                inspection_path = generate_inspector_dashboard(json_filename)
                if inspection_path:
                    # Create relative path for HTML linking (force forward slashes for web compatibility)
                    rel_path = os.path.relpath(inspection_path, self.reports_dir)
                    inspection_url = rel_path.replace("\\", "/")
            except Exception as e:
                self.logger.warning(f"Trade Inspector failed: {e}")

            self._generate_html_report(trades_df, stats, html_filename, inspection_url=inspection_url)
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
        filepath: str,
        inspection_url: str = None
    ) -> str:
        """
        Generate a premium dark-mode HTML dashboard with standalone HTML/CSS/JS.
        Uses Plotly for interactive charts embedded in a custom-styled page.
        Features: glassmorphism stat cards, gradient accents, proper P&L coloring,
        scrollable trade log, and responsive layout.
        """
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
        except ImportError:
            self.logger.warning("plotly not installed. Skipping HTML report. Install: pip install plotly")
            return ""

        initial_cap = self.config.get('capital', {}).get('initial', 100000)
        bt_cfg = self.config.get('backtest', {})
        strat_cfg = self.config.get('strategy', {})
        rsi_cfg = strat_cfg.get('rsi', {})
        start_dt = bt_cfg.get('start_date', trades_df['entry_time'].iloc[0] if not trades_df.empty else '')
        end_dt = bt_cfg.get('end_date', trades_df['exit_time'].iloc[-1] if not trades_df.empty else '')

        net_pnl = stats['total_pnl']
        ret_pct = (net_pnl / initial_cap * 100) if initial_cap > 0 else 0
        gross_pnl = trades_df['pnl_gross'].sum()
        total_charges = trades_df['charges'].sum()
        total_slippage = trades_df['slippage'].sum()

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

        # ── Chart 1: Equity Curve ────────────────────────────────────────
        fig_equity = go.Figure()
        fig_equity.add_trace(go.Scatter(
            x=times, y=eq_vals, mode='lines', name='Equity',
            line=dict(color='#6366f1', width=2.5),
            fill='tozeroy', fillcolor='rgba(99, 102, 241, 0.08)',
            hovertemplate='%{x|%b %d, %Y}<br>Capital: ₹%{y:,.0f}<extra></extra>'
        ))
        fig_equity.add_trace(go.Scatter(
            x=times, y=peak_arr.tolist(), mode='lines', name='Peak',
            line=dict(color='rgba(255,255,255,0.15)', width=1, dash='dash'),
            hoverinfo='skip'
        ))
        fig_equity.add_hline(y=initial_cap, line_dash="dot", line_color="rgba(250,204,21,0.4)",
                             annotation_text=f"Start: ₹{initial_cap:,}",
                             annotation_font=dict(color='#fbbf24', size=10))
        fig_equity.update_layout(
            template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=10, r=10, t=10, b=30), height=320, showlegend=False,
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.05)', zeroline=False,
                       tickformat=',.0f', tickprefix='₹'),
            font=dict(color='#94a3b8', size=11)
        )
        equity_html = fig_equity.to_html(full_html=False, include_plotlyjs=False, config={'displayModeBar': False})

        # ── Chart 2: P&L Per Trade ───────────────────────────────────────
        fig_pnl = go.Figure()
        pnl_colors = ['#22c55e' if x > 0 else '#ef4444' for x in pnl]
        # Use scatter+bar hybrid: bars for small datasets, scatter for large
        if len(pnl) <= 80:
            fig_pnl.add_trace(go.Bar(
                x=list(range(1, len(pnl)+1)), y=pnl.values.tolist(),
                orientation='v',
                marker_color=pnl_colors, marker_line_width=0,
                hovertemplate='Trade #%{x}<br>P&L: ₹%{y:,.0f}<extra></extra>'
            ))
        else:
            # Scatter stem plot: readable even with 300+ trades
            fig_pnl.add_trace(go.Scatter(
                x=list(range(1, len(pnl)+1)), y=pnl.values.tolist(),
                mode='markers', marker=dict(color=pnl_colors, size=5, opacity=0.85),
                hovertemplate='Trade #%{x}<br>P&L: ₹%{y:,.0f}<extra></extra>'
            ))
        fig_pnl.add_hline(y=0, line_color='rgba(255,255,255,0.3)', line_width=1)
        fig_pnl.update_layout(
            template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=10, r=10, t=10, b=30), height=260, showlegend=False,
            xaxis=dict(showgrid=False, title='Trade #', title_font=dict(size=10, color='#64748b')),
            yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.05)',
                       zeroline=True, zerolinecolor='rgba(255,255,255,0.3)', zerolinewidth=1,
                       tickformat=',.0f', tickprefix='₹'),
            font=dict(color='#94a3b8', size=11),
            bargap=0.15
        )
        pnl_trade_html = fig_pnl.to_html(full_html=False, include_plotlyjs=False, config={'displayModeBar': False})

        # ── Chart 3: Monthly P&L ─────────────────────────────────────────
        fig_monthly = go.Figure()
        if not monthly.empty:
            m_colors = ['#22c55e' if x > 0 else '#ef4444' for x in monthly['pnl_sum']]
            fig_monthly.add_trace(go.Bar(
                x=monthly['month'].tolist(), y=monthly['pnl_sum'].tolist(),
                orientation='v',
                marker_color=m_colors, marker_line_width=0,
                text=[f'₹{v:,.0f}' for v in monthly['pnl_sum']],
                textposition='outside', textfont=dict(size=9, color='#94a3b8'),
                hovertemplate='%{x}<br>P&L: ₹%{y:,.0f}<extra></extra>'
            ))
        fig_monthly.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
        fig_monthly.update_layout(
            template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=10, r=10, t=10, b=50), height=260, showlegend=False,
            xaxis=dict(showgrid=False, tickangle=-45),
            yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.05)',
                       zeroline=True, zerolinecolor='rgba(255,255,255,0.3)', zerolinewidth=1,
                       tickformat=',.0f', tickprefix='₹'),
            font=dict(color='#94a3b8', size=11),
            bargap=0.2
        )
        monthly_html = fig_monthly.to_html(full_html=False, include_plotlyjs=False, config={'displayModeBar': False})

        # ── Chart 4: Drawdown ────────────────────────────────────────────
        fig_dd = go.Figure()
        dd_amt = (eq_arr - peak_arr).tolist()  # drawdown in ₹
        # Build custom hover text with both % and ₹ amount
        dd_hover = [f"{t.strftime('%b %d, %Y') if hasattr(t, 'strftime') else t}<br>"
                    f"DD: {dd_pct[i]:.1f}%<br>"
                    f"DD Amt: ₹{dd_amt[i]:,.0f}"
                    for i, t in enumerate(times)]
        fig_dd.add_trace(go.Scatter(
            x=times, y=dd_pct.tolist(), fill='tozeroy', mode='lines',
            line=dict(color='#ef4444', width=1.5),
            fillcolor='rgba(239, 68, 68, 0.15)',
            text=dd_hover, hoverinfo='text'
        ))
        fig_dd.update_layout(
            template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=10, r=10, t=10, b=30), height=220, showlegend=False,
            xaxis=dict(showgrid=False),
            yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.05)', zeroline=False,
                       ticksuffix='%'),
            font=dict(color='#94a3b8', size=11)
        )
        dd_html = fig_dd.to_html(full_html=False, include_plotlyjs=False, config={'displayModeBar': False})

        # ── Chart 5: P&L Distribution ────────────────────────────────────
        fig_dist = go.Figure()
        if len(pnl[pnl > 0]) > 0:
            fig_dist.add_trace(go.Histogram(
                x=pnl[pnl > 0].tolist(), nbinsx=20,
                marker_color='rgba(34, 197, 94, 0.7)', name=f'Wins ({len(pnl[pnl > 0])})',
                hovertemplate='P&L: ₹%{x:,.0f}<br>Count: %{y}<extra></extra>'
            ))
        if len(pnl[pnl <= 0]) > 0:
            fig_dist.add_trace(go.Histogram(
                x=pnl[pnl <= 0].tolist(), nbinsx=20,
                marker_color='rgba(239, 68, 68, 0.7)', name=f'Losses ({len(pnl[pnl <= 0])})',
                hovertemplate='P&L: ₹%{x:,.0f}<br>Count: %{y}<extra></extra>'
            ))
        fig_dist.add_vline(x=pnl.mean(), line_dash="dash", line_color="#fbbf24", line_width=1.5,
                           annotation_text=f"Avg: ₹{pnl.mean():,.0f}",
                           annotation_font=dict(color='#fbbf24', size=10))
        fig_dist.update_layout(
            template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=10, r=10, t=10, b=30), height=220, barmode='overlay',
            legend=dict(font=dict(size=10, color='#94a3b8'), bgcolor='rgba(0,0,0,0)'),
            xaxis=dict(showgrid=False, title='P&L (₹)', title_font=dict(size=10, color='#64748b')),
            yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.05)', zeroline=False,
                       title='Count', title_font=dict(size=10, color='#64748b')),
            font=dict(color='#94a3b8', size=11)
        )
        dist_html = fig_dist.to_html(full_html=False, include_plotlyjs=False, config={'displayModeBar': False})

        # ── Trade Table HTML ─────────────────────────────────────────────
        trade_tbl = trades_df[['symbol', 'entry_time', 'exit_time', 'entry_price',
                               'exit_price', 'qty', 'cost', 'reason', 'pnl_gross', 'charges', 'pnl_net']].copy()
        trade_tbl['entry_time'] = pd.to_datetime(trade_tbl['entry_time']).dt.strftime('%Y-%m-%d %H:%M')
        trade_tbl['exit_time'] = pd.to_datetime(trade_tbl['exit_time']).dt.strftime('%Y-%m-%d %H:%M')

        table_rows = []
        for i, (idx, trow) in enumerate(trade_tbl.iterrows()):
            gross_val = trow['pnl_gross']
            net_val = trow['pnl_net']
            # BUG FIX: Each column gets its OWN color based on its OWN sign
            gross_cls = 'pnl-pos' if gross_val > 0 else ('pnl-neg' if gross_val < 0 else '')
            net_cls = 'pnl-pos' if net_val > 0 else ('pnl-neg' if net_val < 0 else '')
            reason = trow['reason']
            reason_cls = 'reason-tp' if reason == 'TARGET' else ('reason-sl' if reason == 'SL' else 'reason-sq')

            table_rows.append(f"""<tr>
                <td class="col-idx">{i + 1}</td>
                <td class="col-sym">{trow['symbol']}</td>
                <td>{trow['entry_time']}</td>
                <td>{trow['exit_time']}</td>
                <td>₹{trow['entry_price']:,.2f}</td>
                <td>₹{trow['exit_price']:,.2f}</td>
                <td>{trow['qty']}</td>
                <td style="color:#00d2ff;">₹{trow['cost']:,.0f}</td>
                <td><span class="badge {reason_cls}">{reason}</span></td>
                <td class="{gross_cls}">₹{gross_val:,.2f}</td>
                <td>₹{trow['charges']:,.2f}</td>
                <td class="{net_cls}" style="font-weight:600;">₹{net_val:,.2f}</td>
            </tr>""")
        trade_rows_html = '\n'.join(table_rows)

        # ── Stat card helpers ────────────────────────────────────────────
        pnl_color = '#22c55e' if net_pnl >= 0 else '#ef4444'
        pnl_sign = '+' if net_pnl >= 0 else ''
        pf_val = float(str(stats['profit_factor']).replace('inf', '999'))
        pf_color = '#22c55e' if pf_val >= 1.1 else '#ef4444'
        wr_color = '#22c55e' if stats['win_rate'] >= 40 else ('#ef4444' if stats['win_rate'] < 30 else '#fbbf24')
        sharpe_color = '#22c55e' if stats['sharpe_ratio'] >= 1.0 else ('#ef4444' if stats['sharpe_ratio'] < 0 else '#fbbf24')

        inspect_btn = ''
        if inspection_url:
            inspect_btn = f'''<a href="{inspection_url}" target="_blank" class="inspect-btn">
                <span class="inspect-icon">🔍</span> Deep Inspect Trades
            </a>'''

        # ── Full HTML ────────────────────────────────────────────────────
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RSI-15m Backtest Dashboard | {start_dt} to {end_dt}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background: #0b0f19;
    color: #e2e8f0;
    min-height: 100vh;
    padding: 20px 24px;
    -webkit-font-smoothing: antialiased;
  }}

  .header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 20px 28px;
    margin-bottom: 24px;
    background: linear-gradient(135deg, rgba(99,102,241,0.12) 0%, rgba(139,92,246,0.08) 50%, rgba(0,0,0,0) 100%);
    border: 1px solid rgba(99,102,241,0.2);
    border-radius: 16px;
    backdrop-filter: blur(12px);
  }}
  .header-left h1 {{
    font-size: 20px; font-weight: 700; color: #f1f5f9; letter-spacing: -0.02em;
  }}
  .header-left .sub {{
    font-size: 13px; color: #64748b; margin-top: 4px; font-weight: 400;
  }}
  .header-right {{ display: flex; align-items: center; gap: 16px; }}
  .header-pnl {{
    font-size: 28px; font-weight: 800; color: {pnl_color}; letter-spacing: -0.03em;
  }}
  .header-pnl .pct {{ font-size: 15px; font-weight: 500; opacity: 0.8; }}

  .inspect-btn {{
    display: inline-flex; align-items: center; gap: 8px;
    padding: 10px 20px;
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
    color: #fff; border-radius: 10px; text-decoration: none;
    font-weight: 600; font-size: 13px;
    border: 1px solid rgba(139,92,246,0.4);
    box-shadow: 0 4px 20px rgba(99,102,241,0.3);
    transition: all 0.2s ease;
  }}
  .inspect-btn:hover {{ transform: translateY(-2px); box-shadow: 0 8px 30px rgba(99,102,241,0.5); }}
  .inspect-icon {{ font-size: 16px; }}

  .stats-grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 14px; margin-bottom: 24px;
  }}
  .stat-card {{
    background: rgba(30, 41, 59, 0.6);
    border: 1px solid rgba(100, 116, 139, 0.15);
    border-radius: 12px; padding: 16px 18px;
    backdrop-filter: blur(8px);
    transition: border-color 0.2s, transform 0.15s;
  }}
  .stat-card:hover {{ border-color: rgba(99,102,241,0.4); transform: translateY(-2px); }}
  .stat-card .label {{
    font-size: 11px; font-weight: 500; color: #64748b;
    text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px;
  }}
  .stat-card .value {{ font-size: 20px; font-weight: 700; letter-spacing: -0.02em; }}
  .stat-card .detail {{ font-size: 11px; color: #64748b; margin-top: 4px; }}

  .charts-grid {{
    display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px;
  }}
  .chart-panel {{
    background: rgba(15, 23, 42, 0.7);
    border: 1px solid rgba(100, 116, 139, 0.12);
    border-radius: 14px; padding: 18px; overflow: hidden;
  }}
  .chart-panel.full-width {{ grid-column: 1 / -1; }}
  .chart-panel h3 {{
    font-size: 13px; font-weight: 600; color: #94a3b8; margin-bottom: 12px;
    text-transform: uppercase; letter-spacing: 0.04em;
  }}

  .table-container {{
    background: rgba(15, 23, 42, 0.7);
    border: 1px solid rgba(100, 116, 139, 0.12);
    border-radius: 14px; padding: 18px; margin-bottom: 24px; overflow: hidden;
  }}
  .table-container h3 {{
    font-size: 13px; font-weight: 600; color: #94a3b8; margin-bottom: 14px;
    text-transform: uppercase; letter-spacing: 0.04em;
  }}
  .table-scroll {{ overflow-x: auto; max-height: 600px; overflow-y: auto; }}
  .trade-table {{ width: 100%; border-collapse: collapse; font-size: 12px; white-space: nowrap; }}
  .trade-table thead th {{
    position: sticky; top: 0; background: #1e293b; color: #94a3b8;
    padding: 10px 12px; text-align: left; font-weight: 600; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.04em;
    border-bottom: 2px solid rgba(99,102,241,0.3); z-index: 10;
  }}
  .trade-table tbody tr {{
    border-bottom: 1px solid rgba(100, 116, 139, 0.08); transition: background 0.15s;
  }}
  .trade-table tbody tr:hover {{ background: rgba(99,102,241,0.06); }}
  .trade-table tbody td {{ padding: 9px 12px; color: #cbd5e1; }}
  .col-idx {{ color: #475569 !important; font-weight: 500; }}
  .col-sym {{ color: #e2e8f0 !important; font-weight: 600; font-size: 11px; }}

  .pnl-pos {{ color: #22c55e !important; }}
  .pnl-neg {{ color: #ef4444 !important; }}

  .badge {{
    display: inline-block; padding: 3px 10px; border-radius: 6px;
    font-size: 10px; font-weight: 700; letter-spacing: 0.03em;
  }}
  .reason-tp {{ background: rgba(34,197,94,0.15); color: #22c55e; }}
  .reason-sl {{ background: rgba(239,68,68,0.15); color: #ef4444; }}
  .reason-sq {{ background: rgba(251,191,36,0.15); color: #fbbf24; }}

  .footer {{ text-align: center; padding: 16px; color: #475569; font-size: 11px; }}

  ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
  ::-webkit-scrollbar-track {{ background: transparent; }}
  ::-webkit-scrollbar-thumb {{ background: #334155; border-radius: 3px; }}
  ::-webkit-scrollbar-thumb:hover {{ background: #475569; }}
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <h1>RSI-15m Expiry Breakout</h1>
    <div class="sub">
      {start_dt} &rarr; {end_dt} &nbsp;&middot;&nbsp;
      RSI({rsi_cfg.get('period', 14)}) TH {rsi_cfg.get('threshold', 60)} &nbsp;&middot;&nbsp;
      {strat_cfg.get('exit_mode', 'single_lot').replace('_', ' ').title()} &nbsp;&middot;&nbsp;
      Capital: ₹{initial_cap:,}
    </div>
  </div>
  <div class="header-right">
    {inspect_btn}
    <div class="header-pnl">
      {pnl_sign}₹{abs(net_pnl):,.0f}
      <span class="pct">({pnl_sign}{ret_pct:.1f}%)</span>
    </div>
  </div>
</div>

<div class="stats-grid">
  <div class="stat-card">
    <div class="label">Total Trades</div>
    <div class="value" style="color:#e2e8f0">{stats['total_trades']}</div>
    <div class="detail">{stats['winning_trades']}W / {stats['losing_trades']}L</div>
  </div>
  <div class="stat-card">
    <div class="label">Win Rate</div>
    <div class="value" style="color:{wr_color}">{stats['win_rate']}%</div>
    <div class="detail">Streak: {stats['max_win_streak']}W / {stats['max_loss_streak']}L</div>
  </div>
  <div class="stat-card">
    <div class="label">Profit Factor</div>
    <div class="value" style="color:{pf_color}">{stats['profit_factor']}</div>
    <div class="detail">R:R {stats['risk_reward_ratio']}</div>
  </div>
  <div class="stat-card">
    <div class="label">Sharpe Ratio</div>
    <div class="value" style="color:{sharpe_color}">{stats['sharpe_ratio']}</div>
    <div class="detail">Sortino: {stats['sortino_ratio']}</div>
  </div>
  <div class="stat-card">
    <div class="label">Avg Capital Deployed</div>
    <div class="value" style="color:#00d2ff;">₹{stats['avg_capital_deployed']:,.0f}</div>
    <div class="detail">Max: ₹{stats['max_capital_deployed']:,.0f}</div>
  </div>
  <div class="stat-card">
    <div class="label">Max Drawdown</div>
    <div class="value" style="color:#ef4444">{stats['max_drawdown_pct']}%</div>
    <div class="detail">₹{stats['max_drawdown']:,.0f}</div>
  </div>
  <div class="stat-card">
    <div class="label">Net P&amp;L</div>
    <div class="value" style="color:{pnl_color}">₹{net_pnl:,.0f}</div>
    <div class="detail">Gross: ₹{gross_pnl:,.0f}</div>
  </div>
  <div class="stat-card">
    <div class="label">Avg Win</div>
    <div class="value" style="color:#22c55e">₹{stats['avg_win']:,.0f}</div>
    <div class="detail">Best: ₹{stats['largest_win']:,.0f}</div>
  </div>
  <div class="stat-card">
    <div class="label">Avg Loss</div>
    <div class="value" style="color:#ef4444">₹{stats['avg_loss']:,.0f}</div>
    <div class="detail">Worst: ₹{stats['largest_loss']:,.0f}</div>
  </div>
</div>

<div class="charts-grid">
  <div class="chart-panel full-width"><h3>Equity Curve</h3>{equity_html}</div>
</div>
<div class="charts-grid">
  <div class="chart-panel"><h3>P&amp;L Per Trade</h3>{pnl_trade_html}</div>
  <div class="chart-panel"><h3>Monthly P&amp;L</h3>{monthly_html}</div>
</div>
<div class="charts-grid">
  <div class="chart-panel"><h3>Drawdown</h3>{dd_html}</div>
  <div class="chart-panel"><h3>P&amp;L Distribution</h3>{dist_html}</div>
</div>

<div class="table-container">
  <h3>Trade Log ({len(trade_tbl)} trades)</h3>
  <div class="table-scroll">
    <table class="trade-table">
      <thead>
        <tr>
          <th>#</th><th>Symbol</th><th>Entry Time</th><th>Exit Time</th>
          <th>Entry</th><th>Exit</th><th>Qty</th><th>Capital Deployed</th><th>Reason</th>
          <th>Gross P&amp;L</th><th>Charges</th><th>Net P&amp;L</th>
        </tr>
      </thead>
      <tbody>
        {trade_rows_html}
      </tbody>
    </table>
  </div>
</div>

<div class="footer">
  Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} &nbsp;&middot;&nbsp; RSI-15m Expiry Breakout Strategy
</div>

</body>
</html>"""

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)

        # Auto-open in browser
        try:
            import webbrowser
            webbrowser.open(f'file:///{os.path.abspath(filepath)}')
        except Exception:
            pass

        return filepath
