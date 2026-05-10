# nifty_futures_rsi/run_backtest.py
"""
NIFTY Futures RSI-60 Breakout — Backtest Runner

Usage:
    python -m nifty_futures_rsi.run_backtest
    python nifty_futures_rsi/run_backtest.py
"""
import os
import sys
import yaml
import logging
import pandas as pd
from datetime import datetime
from pathlib import Path

# Ensure project root is on path
ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from data.data_manager import DataManager
from nifty_futures_rsi.engine import NiftyFuturesEngine
from reporting.performance import PerformanceReporter


def setup_logging(log_file="nifty_futures_rsi_backtest.log"):
    file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.WARNING)

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[file_handler, stream_handler]
    )


def main():
    setup_logging()
    logger = logging.getLogger("NiftyFuturesRSIRunner")

    # Load strategy-specific config
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    if not os.path.exists(config_path):
        logger.error(f"Config not found: {config_path}")
        sys.exit(1)

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    logger.info("Loaded NIFTY Futures RSI-60 configuration.")

    # Parse dates
    try:
        start_date = pd.to_datetime(config['backtest']['start_date'])
        end_date = pd.to_datetime(config['backtest']['end_date'])
    except Exception as e:
        logger.error(f"Invalid date format: {e}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f" NIFTY Futures RSI-60 Breakout Backtest")
    print(f" Period: {start_date.date()} to {end_date.date()}")
    print(f" Capital: Rs.{config['capital']['initial']:,}")
    print(f" RSI Period: {config['strategy']['rsi']['period']}")
    print(f" RSI Threshold: {config['strategy']['rsi']['threshold']}")
    print(f"{'='*60}\n")

    # Initialize components
    dm = DataManager(config)
    engine = NiftyFuturesEngine(dm, config)
    reporter = PerformanceReporter(config)

    # Run backtest
    trades_df = engine.run(start_date, end_date)

    # Print diagnostics
    engine.print_diagnostic_summary()

    # Generate report
    if trades_df.empty:
        logger.warning("Backtest produced ZERO trades.")
        print("\n[!] No trades generated. Check data availability and RSI parameters.")
    else:
        logger.info(f"Backtest completed with {len(trades_df)} trades.")
        print(f"\n[OK] Backtest completed with {len(trades_df)} trades.")

    # Use custom prefix for this strategy's reports
    reporter.generate_report(
        trades_df,
        save_to_file=True,
        custom_prefix=f"NIFTY-FUT-RSI60_{start_date.year}-{end_date.year}"
    )


if __name__ == "__main__":
    main()
