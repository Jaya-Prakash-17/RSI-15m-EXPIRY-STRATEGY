import os
import sys
import pandas as pd
import yaml
import logging
from datetime import datetime, time, timedelta

# Add parent directory to path to import local modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.data_manager import DataManager
from reporting.performance import PerformanceReporter
from utils.historical_lot_sizes import get_historical_lot_size
from utils.expiry_calendar import get_expiry_for_date
from utils.nse_calendar import is_trading_day

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

class StrangleBacktester:
    def __init__(self, config_path="config.yaml"):
        # Load config from the project root (up one level from this script's directory)
        root_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg_abs_path = os.path.join(root_path, config_path)

        with open(cfg_abs_path, "r") as f:
            self.config = yaml.safe_load(f)

        # Ensure base path for data is absolute
        if not os.path.isabs(self.config['data']['storage_path']):
            self.config['data']['storage_path'] = os.path.join(root_path, self.config['data']['storage_path'])

        self.dm = DataManager(self.config)
        self.reporter = PerformanceReporter(self.config)
        self.logger = logging.getLogger("StrangleBacktest")

    def run(self, start_date_str, end_date_str):
        start_date = pd.to_datetime(start_date_str)
        end_date = pd.to_datetime(end_date_str)

        self.logger.info(f"Starting 5-year Strangle Backtest: {start_date.date()} to {end_date.date()}")

        trades = []
        current_capital = self.config['capital']['initial']

        current_date = start_date
        while current_date <= end_date:
            if is_trading_day(current_date):
                # self.logger.info(f"Processing {current_date.date()}...")
                day_trades = self.process_day(current_date)
                if day_trades:
                    for t in day_trades:
                        current_capital += t['pnl']
                        t['running_capital'] = current_capital
                        trades.append(t)

            current_date += timedelta(days=1)
            # Clear cache daily to save memory
            self.dm.clear_cache(clear_spot=True)

        return pd.DataFrame(trades)

    def process_day(self, date):
        underlying = 'NIFTY'

        # 1. Get Expiry for this trading day
        expiry = get_expiry_for_date(underlying, date.date())
        if not expiry:
            return None

        # 2. Get Spot at 9:45
        # Fetch data for the day
        start_dt = datetime.combine(date.date(), time(9, 15))
        end_dt = datetime.combine(date.date(), time(15, 30))

        # Load spot data (DataManager handles range filtering)
        spot_df = self.dm.get_spot_candles(underlying, start_dt, end_dt)
        if spot_df.empty:
            return None

        # Get 9:45 AM candle. We look for the candle that OPENS at 9:45
        entry_time = datetime.combine(date.date(), time(9, 45))
        exit_time = datetime.combine(date.date(), time(15, 15))

        entry_row = spot_df[spot_df['datetime'] == entry_time]
        if entry_row.empty:
            # Fallback to nearest if 15m candle might be labeled differently
            # but usually it's exact 9:45:00
            return None

        spot_price = entry_row['open'].iloc[0]

        # 3. Determine Strikes (500 pts away from spot)
        # NIFTY strike step is 50
        at_strike = round(spot_price / 50) * 50
        ce_strike = int(at_strike + 500)
        pe_strike = int(at_strike - 500)

        # 4. Get Lot Size
        lot_size = get_historical_lot_size(underlying, date.date())
        lots = self.config['strategy'].get('lots_per_trade', 1)
        total_qty = lot_size * lots

        day_trades = []

        for strike, opt_type in [(ce_strike, 'CE'), (pe_strike, 'PE')]:
            # Build historical symbol
            symbol = self.dm.build_option_symbol(underlying, date, strike, opt_type, use_historical=True)

            # Load option data
            opt_df = self.dm.get_derivative_candles(underlying, symbol, date.year, start_dt, end_dt)
            if opt_df.empty:
                # self.logger.warning(f"No data for {symbol} on {date.date()}")
                continue

            e_row = opt_df[opt_df['datetime'] == entry_time]
            x_row = opt_df[opt_df['datetime'] == exit_time]

            if e_row.empty or x_row.empty:
                continue

            e_price = e_row['open'].iloc[0]
            x_price = x_row['close'].iloc[0] # Exit at 3:15 close

            # Short position: Profit = (Entry - Exit) * Qty
            pnl = (e_price - x_price) * total_qty

            day_trades.append({
                'symbol': symbol,
                'entry_time': entry_time,
                'exit_time': exit_time,
                'entry_price': e_price,
                'exit_price': x_price,
                'qty': total_qty,
                'pnl': pnl,
                'reason': 'TIME_EXIT',
                'underlying': underlying,
                'opt_type': opt_type
            })

        return day_trades

if __name__ == "__main__":
    setup_logging()

    # Initialize with default config
    tester = StrangleBacktester()

    # 5 Year Range
    start = "2020-01-01"
    end = "2025-12-31"

    # Check if we should override from config for flexibility
    start = tester.config.get('backtest', {}).get('start_date', start)
    end = tester.config.get('backtest', {}).get('end_date', end)

    df = tester.run(start, end)

    if not df.empty:
        print(f"\nBacktest completed with {len(df)} trades.")
        # Generate Report using global config's metrics
        report_data = tester.reporter.generate_report(df, custom_prefix="STRANGLE_NIFTY_5Yr")

        # Move the summary to a specific location if needed,
        # but the reporter already saves to /reports.
    else:
        print("No trades found in the specified period.")
