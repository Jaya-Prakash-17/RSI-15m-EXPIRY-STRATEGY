# utils/trade_logger.py
"""
Trade Logger - Maintains audit trail of all trades in CSV format.
Supports both live and backtest modes for consistent logging.
"""
import os
import csv
import logging
from datetime import datetime
from threading import Lock

class TradeLogger:
    """
    Logs all trades to a CSV file for audit and analysis.
    Thread-safe implementation for live trading.
    """
    
    # CSV headers for trade log
    HEADERS = [
        'timestamp', 'trade_id', 'mode', 'symbol', 'trading_symbol', 
        'side', 'entry_time', 'entry_price', 'qty', 
        'exit_time', 'exit_price', 'sl', 'target', 
        'reason', 'pnl', 'pnl_if_sl_hit', 'max_loss_savings',
        'remaining_qty', 'partial_pnl', 'daily_pnl', 'capital'
    ]
    
    def __init__(self, config):
        self.logger = logging.getLogger("TradeLogger")
        self.config = config
        self.filepath = config['trading'].get('trade_log_file', 'logs/trade_log.csv')
        self.lock = Lock()
        self.mode = 'PAPER' if config['trading'].get('paper_trading', True) else 'LIVE'
        self._ensure_file_exists()
    
    def _ensure_file_exists(self):
        """Create log file with headers if it doesn't exist."""
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        
        if not os.path.exists(self.filepath):
            with open(self.filepath, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(self.HEADERS)
            self.logger.info(f"Created trade log file: {self.filepath}")
    
    def log_entry(self, trade, daily_pnl=0, capital=0):
        """Log trade entry."""
        with self.lock:
            row = {
                'timestamp': datetime.now().isoformat(),
                'trade_id': trade.get('trade_id', ''),
                'mode': self.mode,
                'symbol': trade.get('symbol', ''),
                'trading_symbol': trade.get('trading_symbol', ''),
                'side': 'BUY',
                'entry_time': trade.get('entry_time', ''),
                'entry_price': trade.get('entry_price', 0),
                'qty': trade.get('qty', 0),
                'exit_time': '',
                'exit_price': '',
                'sl': trade.get('sl', 0),
                'target': trade.get('targets', [0, 0, 0])[2] if trade.get('targets') else 0,
                'reason': 'ENTRY',
                'pnl': 0,
                'pnl_if_sl_hit': '',
                'max_loss_savings': '',
                'remaining_qty': trade.get('qty', 0),
                'partial_pnl': 0,
                'daily_pnl': daily_pnl,
                'capital': capital
            }
            self._write_row(row)
    
    def log_exit(self, trade, daily_pnl=0, capital=0, *legacy_args):
        """Log trade exit.

        Supports both `(trade, daily_pnl, capital)` and the older
        `(trade, exit_price, reason, daily_pnl[, capital])` call style.
        """
        with self.lock:
            exit_price = trade.get('exit_price', 0)
            exit_time = trade.get('exit_time', datetime.now().isoformat())
            reason = trade.get('reason', 'UNKNOWN')
            pnl = trade.get('pnl', 0)

            if isinstance(capital, str):
                exit_price = daily_pnl
                reason = capital
                daily_pnl = legacy_args[0] if legacy_args else 0
                capital = legacy_args[1] if len(legacy_args) > 1 else 0

                remaining_qty = trade.get('remaining_qty', trade.get('qty', 0))
                partial_pnl = trade.get('partial_pnl', 0)
                pnl = (exit_price - trade.get('entry_price', 0)) * remaining_qty + partial_pnl
                exit_time = datetime.now().isoformat()

            row = {
                'timestamp': datetime.now().isoformat(),
                'trade_id': trade.get('trade_id', ''),
                'mode': self.mode,
                'symbol': trade.get('symbol', ''),
                'trading_symbol': trade.get('trading_symbol', ''),
                'side': 'SELL',
                'entry_time': trade.get('entry_time', ''),
                'entry_price': trade.get('entry_price', 0),
                'qty': trade.get('qty', 0),
                'exit_time': exit_time,
                'exit_price': exit_price,
                'sl': trade.get('sl', 0),
                'target': trade.get('targets', [0, 0, 0])[2] if trade.get('targets') else 0,
                'reason': reason,
                'pnl': pnl,
                'pnl_if_sl_hit': trade.get('pnl_if_sl_hit', ''),
                'max_loss_savings': trade.get('max_loss_savings', ''),
                'remaining_qty': trade.get('remaining_qty', 0),
                'partial_pnl': trade.get('partial_pnl', 0),
                'daily_pnl': daily_pnl,
                'capital': capital
            }
            self._write_row(row)
            
            # Log MAX_LOSS comparison
            if reason == 'MAX_LOSS':
                self.logger.info(
                    f"MAX_LOSS EXIT: {trade.get('symbol')} | "
                    f"Actual PnL: ₹{pnl:.2f} | "
                    f"If SL hit: ₹{trade.get('pnl_if_sl_hit', 0):.2f} | "
                    f"Saved: ₹{trade.get('max_loss_savings', 0):.2f}"
                )
    
    def log_partial_exit(self, trade, exit_qty, exit_price, reason, partial_pnl, daily_pnl=0, capital=0):
        """Log partial exit."""
        with self.lock:
            row = {
                'timestamp': datetime.now().isoformat(),
                'trade_id': trade.get('trade_id', ''),
                'mode': self.mode,
                'symbol': trade.get('symbol', ''),
                'trading_symbol': trade.get('trading_symbol', ''),
                'side': 'PARTIAL_SELL',
                'entry_time': trade.get('entry_time', ''),
                'entry_price': trade.get('entry_price', 0),
                'qty': exit_qty,
                'exit_time': datetime.now().isoformat(),
                'exit_price': exit_price,
                'sl': trade.get('sl', 0),
                'target': exit_price,
                'reason': reason,
                'pnl': partial_pnl,
                'pnl_if_sl_hit': '',
                'max_loss_savings': '',
                'remaining_qty': trade.get('remaining_qty', 0),
                'partial_pnl': trade.get('partial_pnl', 0),
                'daily_pnl': daily_pnl,
                'capital': capital
            }
            self._write_row(row)
    
    def _write_row(self, row_dict):
        """Write a row to the CSV file."""
        try:
            with open(self.filepath, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=self.HEADERS)
                writer.writerow(row_dict)
        except Exception as e:
            self.logger.error(f"Failed to write trade log: {e}")


class BacktestTradeLogger(TradeLogger):
    """
    Trade logger for backtesting - logs all trades to a date-prefixed file.
    """
    
    def __init__(self, config, backtest_date=None):
        # Override filepath for backtest
        date_str = backtest_date or datetime.now().strftime("%Y%m%d")
        config = dict(config)  # Copy to avoid modifying original
        if 'trading' not in config:
            config['trading'] = {}
        config['trading']['trade_log_file'] = f"logs/backtest_trades_{date_str}.csv"
        config['trading']['paper_trading'] = True  # Backtest is always paper
        super().__init__(config)
        self.mode = 'BACKTEST'
