#!/usr/bin/env python3
"""
V16-P-02: Out-of-Sample Validation Runner
Runs backtests for individual years (2022-2025) using the Python backtest engine
directly — no subprocess, no config.yaml mutation, no API calls.

Runs OOS using production config.yaml by default.
Use --lots 1 flag for a single-lot comparison run.

Usage: python scripts/run_oos_validation.py
       python scripts/run_oos_validation.py --lots 1 --exit-mode single_lot
"""
import sys
import os
import argparse
import copy
import yaml
import logging
import time
import pandas as pd

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.data_manager import DataManager
from backtest.intraday_engine import IntradayEngine
from reporting.performance import PerformanceReporter

DEFAULT_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
CONFIG_FILE = 'config.yaml'


def load_base_config():
    """Load the production config.yaml once."""
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


def make_year_config(base_config, year, lots_override=None, exit_mode_override=None):
    """Create an in-memory config override for a specific year.
    Never touches the config.yaml file on disk."""
    cfg = copy.deepcopy(base_config)
    cfg['backtest']['start_date'] = f'{year}-01-01'
    cfg['backtest']['end_date'] = f'{year}-12-31'
    cfg['backtest']['offline_mode'] = False  # Smart fallback handles it

    if lots_override is not None:
        cfg['strategy']['lots_per_trade'] = lots_override
    if exit_mode_override is not None:
        cfg['strategy']['exit_mode'] = exit_mode_override

    return cfg


def run_single_year(base_config, year, logger, lots_override=None, exit_mode_override=None):
    """Run a full backtest for one year using the in-process engine.
    Returns (year, trades_df, report_data, elapsed_seconds)."""
    cfg = make_year_config(base_config, year, lots_override, exit_mode_override)
    start_date = pd.to_datetime(cfg['backtest']['start_date'])
    end_date = pd.to_datetime(cfg['backtest']['end_date'])

    logger.info(f"{'='*60}")
    logger.info(f"  OOS BACKTEST: {year}")
    logger.info(f"  Config: lots={cfg['strategy'].get('lots_per_trade', 'N/A')}, "
                f"mode={cfg['strategy'].get('exit_mode', 'N/A')}, "
                f"target={cfg['strategy'].get('single_lot_exit_target', 'N/A')}")
    logger.info(f"{'='*60}")

    t0 = time.time()

    dm = DataManager(cfg)
    engine = IntradayEngine(dm, cfg)
    reporter = PerformanceReporter(cfg)

    trades_df = engine.run(start_date, end_date)
    engine.print_diagnostic_summary()

    report_data = None
    if not trades_df.empty:
        report_data = reporter.generate_report(trades_df)
        logger.info(f"  {year}: {len(trades_df)} trades completed")
    else:
        logger.warning(f"  {year}: ZERO trades — check data availability")

    elapsed = time.time() - t0
    logger.info(f"  {year}: completed in {elapsed:.1f}s")

    return year, trades_df, report_data, elapsed


def run_comparison(logger):
    """Run the compare_years analysis on generated reports."""
    logger.info(f"\n{'='*60}")
    logger.info("  RUNNING YEAR-OVER-YEAR COMPARISON")
    logger.info(f"{'='*60}")
    try:
        # Import and run directly instead of subprocess
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        from compare_years import load_summaries, print_table
        results = load_summaries('reports/')
        print_table(results)
    except ImportError:
        # Fallback: run as script
        import subprocess
        subprocess.run(
            [sys.executable, 'scripts/compare_years.py', 'reports/'],
            timeout=30
        )


def setup_logging():
    """Configure logging for OOS validation."""
    log_file = 'oos_validation.log'
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, mode='w'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger("OOSValidation")


def main():
    logger = setup_logging()

    parser = argparse.ArgumentParser(description="Run Out-of-Sample Validation")
    parser.add_argument('years', nargs='*', type=int, default=DEFAULT_YEARS,
                        help='Specific years to backtest (e.g., 2023 2024)')
    parser.add_argument('--lots', type=int, default=None,
                        help='Override lots_per_trade for comparison (default: use config.yaml)')
    parser.add_argument('--exit-mode', default=None,
                        help='Override exit_mode (default: use config.yaml)')

    args = parser.parse_args()
    years = args.years

    logger.info(f"OOS Validation: years={years}")
    logger.info(f"Config file: {os.path.abspath(CONFIG_FILE)} (NOT modified)")

    base_config = load_base_config()
    results = {}
    total_t0 = time.time()

    for year in years:
        try:
            yr, trades_df, report_data, elapsed = run_single_year(
                base_config, year, logger, args.lots, args.exit_mode
            )
            results[yr] = {
                'trades': len(trades_df) if trades_df is not None else 0,
                'elapsed': elapsed,
                'report': report_data
            }
        except Exception as e:
            logger.error(f"  {year}: FAILED — {e}", exc_info=True)
            results[year] = {'trades': 0, 'elapsed': 0, 'report': None, 'error': str(e)}

    total_elapsed = time.time() - total_t0

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info(f"  OOS VALIDATION COMPLETE")
    logger.info(f"{'='*60}")
    for yr in sorted(results.keys()):
        r = results[yr]
        status = f"{r['trades']} trades in {r['elapsed']:.1f}s"
        if 'error' in r:
            status += f" [ERROR: {r['error']}]"
        logger.info(f"  {yr}: {status}")
    logger.info(f"  Total time: {total_elapsed:.1f}s")
    logger.info(f"  Config file was NOT modified during this run.")

    # Run comparison
    run_comparison(logger)


if __name__ == '__main__':
    main()
