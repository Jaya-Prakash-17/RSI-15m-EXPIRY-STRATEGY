"""
Backtest Pre-flight Verification Script
Checks data availability, date ranges, and lot size logic before backtest.
"""
import os
import sys
import pandas as pd
import yaml
import glob
from datetime import date, datetime
import logging

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.historical_lot_sizes import get_historical_lot_size, _run_self_test
from utils.expiry_calendar import run_startup_assertions
from utils.nse_calendar import get_trading_days_count

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("PreFlight")

def check_backtest_data():
    logger.info("\n=== BACKTEST PRE-FLIGHT ===\n")
    
    # 1. Load config
    try:
        with open('config.yaml', 'r') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to load config.yaml: {e}")
        return False
        
    start_date = datetime.strptime(config['backtest']['start_date'], '%Y-%m-%d').date()
    end_date = datetime.strptime(config['backtest']['end_date'], '%Y-%m-%d').date()
    trading_days = get_trading_days_count(start_date, end_date)
    
    logger.info(f"Range: {start_date} to {end_date} ({trading_days} trading days)")
    
    overall_go = True
    
    # 2. Check each index
    base_path = config['data'].get('storage_path', 'data')
    
    for underlying in config['indices']:
        logger.info(f"\n{underlying}:")
        
        # Spot check
        spot_file = os.path.join(base_path, 'spot', f"{underlying}_15m.csv")
        if os.path.exists(spot_file):
            try:
                df = pd.read_csv(spot_file)
                df['datetime'] = pd.to_datetime(df['datetime'])
                min_t = df['datetime'].min().date()
                max_t = df['datetime'].max().date()
                
                status = "\u2705" if min_t <= start_date and max_t >= end_date else "\u26a0\ufe0f"
                logger.info(f"  Spot data: {min_t} to {max_t} {status}")
                if status == "\u26a0\ufe0f":
                    logger.warning(f"    Missing spot range: {start_date} to {min_t} or {max_t} to {end_date}")
            except Exception as e:
                logger.error(f"  Error reading spot file {spot_file}: {e}")
        else:
            logger.error(f"  Spot file MISSING: {spot_file} \u274c")
            overall_go = False
            
        # Derivatives check
        years = range(start_date.year, end_date.year + 1)
        for year in years:
            dir_path = os.path.join(base_path, 'derivatives', underlying, str(year))
            if os.path.exists(dir_path):
                files = glob.glob(os.path.join(dir_path, "*.csv"))
                logger.info(f"  Derivatives {year}: {len(files)} files \u2705")
            else:
                logger.warning(f"  Derivatives {year}: Directory not found \u274c")
                if underlying != 'SENSEX' or year >= 2023:
                    # SENSEX pre-2023 is okay to miss
                    pass 

        # Lot size check
        try:
            logger.info("  Lot size evolution:")
            dates_to_check = [start_date, end_date]
            # Add boundary dates if in range
            boundaries = [date(2024, 11, 20), date(2025, 9, 1)]
            for b in boundaries:
                if start_date <= b <= end_date:
                    dates_to_check.append(b)
            
            seen = set()
            for d in sorted(list(set(dates_to_check))):
                try:
                    lz = get_historical_lot_size(underlying, d)
                    logger.info(f"    {d}: {lz} \u2705")
                except ValueError as e:
                    if underlying == 'SENSEX' and d < date(2023, 5, 1):
                        logger.info(f"    {d}: N/A (pre-launch) \u2705")
                    else:
                        logger.warning(f"    {d}: {e} \u26a0\ufe0f")
        except Exception as e:
            logger.error(f"  Lot size lookup failed: {e}")

    # 3. Global checks
    logger.info("\nGlobal System Checks:")
    
    if start_date < date(2020, 1, 1):
        logger.warning(f"  \u26a0\ufe0f start_date {start_date} is before Jan 2020 (Groww API limit)")
    
    # 4. Run module tests
    try:
        _run_self_test()
        logger.info("  Lot size self-test: PASS \u2705")
    except Exception as e:
        logger.error(f"  Lot size self-test: FAIL \u274c ({e})")
        overall_go = False
        
    try:
        run_startup_assertions()
        logger.info("  Expiry calendar assertions: PASS \u2705")
    except Exception as e:
        logger.error(f"  Expiry calendar assertions: FAIL \u274c ({e})")
        overall_go = False
        
    # 5. Verdict
    verdict = "\u2705 GO" if overall_go else "\u274c NO-GO"
    logger.info(f"\n=== VERDICT: {verdict} ===")
    
    return overall_go

if __name__ == '__main__':
    check_backtest_data()
