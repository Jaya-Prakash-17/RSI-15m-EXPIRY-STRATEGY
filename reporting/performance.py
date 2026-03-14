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
        
        # Trading charges (typical Indian broker charges)
        self.charges = {
            'brokerage_per_trade': 20,  # Flat ₹20 per trade
            'stt': 0.0005,  # 0.05% on sell side for options
            'exchange_txn_fee': 0.00053,  # 0.053% NSE charges
            'gst': 0.18,  # 18% on brokerage + txn fees
            'sebi_charges': 0.0001,  # 0.01% SEBI charges
            'stamp_duty': 0.00003  # 0.003% on buy side
        }
        
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

    def calculate_advanced_stats(self, trades_df):
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
        
        # Drawdown
        cum_pnl = pnl.cumsum()
        peak = cum_pnl.cummax()
        drawdown = cum_pnl - peak
        max_drawdown = drawdown.min()
        max_drawdown_pct = (max_drawdown / peak.max() * 100) if peak.max() > 0 else 0
        
        # Risk-adjusted metrics
        std_pnl = pnl.std() if len(pnl) > 1 else 0
        
        # Sharpe Ratio (annualized, assuming daily returns)
        # Using 252 trading days per year
        if std_pnl > 0:
            sharpe_ratio = (avg_pnl / std_pnl) * np.sqrt(252)
        else:
            sharpe_ratio = 0
        
        # Sortino Ratio (using downside deviation)
        negative_returns = pnl[pnl < 0]
        downside_std = negative_returns.std() if len(negative_returns) > 1 else 0
        if downside_std > 0:
            sortino_ratio = (avg_pnl / downside_std) * np.sqrt(252)
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
            
            # Volatility
            'pnl_std_dev': round(std_pnl, 2)
        }

    def generate_report(self, trades_df, save_to_file=True):
        """Generate comprehensive performance report with trading charges"""
        if trades_df.empty:
            self.logger.info("No trades generated.")
            return None

        # Calculate trading charges for each trade
        charges_list = []
        for idx, trade in trades_df.iterrows():
            charges = self.calculate_charges(
                trade['entry_price'], 
                trade['exit_price'], 
                trade['qty']
            )
            charges_list.append(charges)
        
        # Add charges to dataframe
        trades_df['charges'] = [c['total'] for c in charges_list]
        trades_df['pnl_gross'] = trades_df['pnl']
        trades_df['pnl_net'] = trades_df['pnl'] - trades_df['charges']
        
        # Calculate all statistics
        stats = self.calculate_advanced_stats(trades_df)
        total_charges = trades_df['charges'].sum()
        
        # Print comprehensive console report
        print("\n" + "="*70)
        print(" 📊 BACKTEST PERFORMANCE REPORT")
        print("="*70)
        
        # Config parameters
        if self.config:
            print("\n📋 STRATEGY PARAMETERS")
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
                print(f"  Initial Capital: ₹{self.config['capital'].get('initial', 'N/A'):,}")
        
        print("\n📈 TRADE STATISTICS")
        print("-"*70)
        print(f"  Total Trades:    {stats['total_trades']}")
        print(f"  Winning Trades:  {stats['winning_trades']} ({stats['win_rate']}%)")
        print(f"  Losing Trades:   {stats['losing_trades']}")
        print(f"  Win/Loss Streak: {stats['max_win_streak']} / {stats['max_loss_streak']}")
        
        print("\n💰 PROFIT & LOSS")
        print("-"*70)
        print(f"  Gross P&L:       ₹{trades_df['pnl_gross'].sum():,.2f}")
        print(f"  Total Charges:   ₹{total_charges:,.2f}")
        print(f"  Net P&L:         ₹{stats['total_pnl']:,.2f}")
        print(f"  Avg P&L/Trade:   ₹{stats['avg_pnl_per_trade']:,.2f}")
        print(f"  Avg Win:         ₹{stats['avg_win']:,.2f}")
        print(f"  Avg Loss:        ₹{stats['avg_loss']:,.2f}")
        print(f"  Largest Win:     ₹{stats['largest_win']:,.2f}")
        print(f"  Largest Loss:    ₹{stats['largest_loss']:,.2f}")
        
        print("\n📊 RISK METRICS")
        print("-"*70)
        print(f"  Profit Factor:   {stats['profit_factor']}")
        print(f"  Risk/Reward:     {stats['risk_reward_ratio']}")
        print(f"  Expectancy:      ₹{stats['expectancy']:,.2f}")
        print(f"  Max Drawdown:    ₹{stats['max_drawdown']:,.2f} ({stats['max_drawdown_pct']}%)")
        print(f"  P&L Std Dev:     ₹{stats['pnl_std_dev']:,.2f}")
        
        print("\n📉 RISK-ADJUSTED RETURNS")
        print("-"*70)
        print(f"  Sharpe Ratio:    {stats['sharpe_ratio']}")
        print(f"  Sortino Ratio:   {stats['sortino_ratio']}")
        print(f"  Calmar Ratio:    {stats['calmar_ratio']}")
        
        print("\n⏱️ TIMING")
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
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Save detailed CSV
            csv_filename = os.path.join(self.reports_dir, f"backtest_{timestamp}.csv")
            trades_df.to_csv(csv_filename, index=False)
            self.logger.info(f"Detailed trade log saved to: {csv_filename}")
            
            # Save summary JSON
            json_filename = os.path.join(self.reports_dir, f"backtest_{timestamp}_summary.json")
            with open(json_filename, 'w') as f:
                json.dump(report_data, f, indent=2, default=str)
            self.logger.info(f"Summary report saved to: {json_filename}")
            
            # Save human-readable text report
            txt_filename = os.path.join(self.reports_dir, f"backtest_{timestamp}_report.txt")
            self._save_text_report(txt_filename, report_data, stats)
            self.logger.info(f"Text report saved to: {txt_filename}")
            
            print(f"\n📁 Reports saved to '{self.reports_dir}' directory")
            print(f"   - CSV:  {csv_filename}")
            print(f"   - JSON: {json_filename}")
            print(f"   - TXT:  {txt_filename}\n")
        
        return report_data

    def _save_text_report(self, filename, report_data, stats):
        """Save comprehensive text report"""
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("="*80 + "\n")
            f.write(" BACKTEST PERFORMANCE REPORT\n")
            f.write("="*80 + "\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*80 + "\n\n")
            
            # Config section
            if self.config:
                f.write("STRATEGY PARAMETERS\n")
                f.write("-"*80 + "\n")
                if 'backtest' in self.config:
                    bt = self.config['backtest']
                    f.write(f"Period:            {bt.get('start_date', 'N/A')} to {bt.get('end_date', 'N/A')}\n")
                if 'strategy' in self.config:
                    st = self.config['strategy']
                    f.write(f"RSI Period:        {st.get('rsi', {}).get('period', 'N/A')}\n")
                    f.write(f"RSI Threshold:     {st.get('rsi', {}).get('threshold', 'N/A')}\n")
                    f.write(f"Exit Mode:         {st.get('exit_mode', 'N/A')}\n")
                    f.write(f"Lots/Trade:        {st.get('lots_per_trade', 'N/A')}\n")
                if 'capital' in self.config:
                    f.write(f"Initial Capital:   ₹{self.config['capital'].get('initial', 0):,}\n")
                f.write("\n")
            
            # Statistics
            f.write("PERFORMANCE SUMMARY\n")
            f.write("-"*80 + "\n")
            f.write(f"Total Trades:      {stats['total_trades']}\n")
            f.write(f"Winning Trades:    {stats['winning_trades']}\n")
            f.write(f"Losing Trades:     {stats['losing_trades']}\n")
            f.write(f"Win Rate:          {stats['win_rate']}%\n")
            f.write(f"\n")
            f.write(f"Net P&L:           ₹{stats['total_pnl']:,.2f}\n")
            f.write(f"Avg P&L/Trade:     ₹{stats['avg_pnl_per_trade']:,.2f}\n")
            f.write(f"Avg Win:           ₹{stats['avg_win']:,.2f}\n")
            f.write(f"Avg Loss:          ₹{stats['avg_loss']:,.2f}\n")
            f.write(f"Largest Win:       ₹{stats['largest_win']:,.2f}\n")
            f.write(f"Largest Loss:      ₹{stats['largest_loss']:,.2f}\n")
            f.write(f"\n")
            f.write(f"Profit Factor:     {stats['profit_factor']}\n")
            f.write(f"Risk/Reward:       {stats['risk_reward_ratio']}\n")
            f.write(f"Expectancy:        ₹{stats['expectancy']:,.2f}\n")
            f.write(f"Max Drawdown:      ₹{stats['max_drawdown']:,.2f} ({stats['max_drawdown_pct']}%)\n")
            f.write(f"\n")
            f.write(f"Sharpe Ratio:      {stats['sharpe_ratio']}\n")
            f.write(f"Sortino Ratio:     {stats['sortino_ratio']}\n")
            f.write(f"Calmar Ratio:      {stats['calmar_ratio']}\n")
            f.write(f"\n")
            f.write(f"Max Win Streak:    {stats['max_win_streak']}\n")
            f.write(f"Max Loss Streak:   {stats['max_loss_streak']}\n")
            f.write(f"Avg Holding Time:  {stats['avg_holding_mins']} mins\n")
            f.write("\n" + "="*80 + "\n\n")
            
            # Trade-by-trade details
            f.write("TRADE-BY-TRADE DETAILS\n")
            f.write("="*80 + "\n\n")
            
            for idx, trade in enumerate(report_data['trades'], 1):
                # Calculate lot details
                qty = trade['qty']
                underlying = 'NIFTY'
                if 'BANKNIFTY' in trade['symbol']:
                    underlying = 'BANKNIFTY'
                elif 'SENSEX' in trade['symbol']:
                    underlying = 'SENSEX'
                
                # Determine lot size based on year
                try:
                    trade_year = pd.to_datetime(trade['entry_time']).year
                except:
                    trade_year = 2026
                    
                if underlying == 'NIFTY':
                    lot_size = 75 if trade_year <= 2025 else 65
                elif underlying == 'BANKNIFTY':
                    lot_size = 35 if trade_year <= 2025 else 30
                else:
                    lot_size = 20
                
                lots = qty // lot_size if lot_size > 0 else 0
                
                f.write(f"Trade #{idx}\n")
                f.write("-"*80 + "\n")
                f.write(f"  Symbol:        {trade['symbol']}\n")
                f.write(f"  Entry Time:    {trade['entry_time']}\n")
                f.write(f"  Entry Price:   ₹{trade['entry_price']:.2f}\n")
                f.write(f"  Exit Time:     {trade['exit_time']}\n")
                f.write(f"  Exit Price:    ₹{trade['exit_price']:.2f}\n")
                f.write(f"  Quantity:      {qty} ({lots} lots × {lot_size})\n")
                f.write(f"  Exit Reason:   {trade.get('reason', 'UNKNOWN')}\n")
                f.write(f"  Gross P&L:     ₹{trade['pnl_gross']:.2f}\n")
                f.write(f"  Charges:       ₹{trade['charges']:.2f}\n")
                f.write(f"  Net P&L:       ₹{trade['pnl_net']:.2f}\n")
                f.write("\n")
            
            f.write("="*80 + "\n")
            f.write("END OF REPORT\n")
            f.write("="*80 + "\n")
