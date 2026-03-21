# run_backtest.py
import yaml
import logging
import sys
import pandas as pd
from datetime import datetime
from data.data_manager import DataManager
from backtest.intraday_engine import IntradayEngine
from reporting.performance import PerformanceReporter

def setup_logging(log_file="backtest.log"):
    # Configure root logger
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, mode='w'), # Overwrite mode
            logging.StreamHandler(sys.stdout)
        ]
    )

def main():
    setup_logging()
    logger = logging.getLogger("BacktestRunner")
    
    # Load Config
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
        
    logger.info("Loaded configuration.")
    
    # Check Backtest Dates
    if 'backtest' not in config or 'start_date' not in config['backtest']:
        logger.error("Backtest dates not found in config.")
        sys.exit(1)
        
    try:
        start_date = pd.to_datetime(config['backtest']['start_date'])
        end_date = pd.to_datetime(config['backtest']['end_date'])
    except Exception as e:
        logger.error(f"Invalid date format: {e}")
        sys.exit(1)

    # Initialize Components
    dm = DataManager(config)
    engine = IntradayEngine(dm, config)
    reporter = PerformanceReporter(config)  # Pass config for enhanced reporting
    
    # Run Backtest
    trades_df = engine.run(start_date, end_date)
    
    # Sanity Checks
    if trades_df.empty:
        logger.warning("Backtest produced ZERO trades. Check data availability or strategy params.")
    else:
        logger.info(f"Backtest completed with {len(trades_df)} trades.")
    
    # Report
    reporter.generate_report(trades_df)

if __name__ == "__main__":
    main()
