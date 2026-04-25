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

class GapSpreadBacktester:
    def __init__(self, config_path="config.yaml"):
        # Load config from project root
        root_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg_abs_path = os.path.join(root_path, config_path)

        with open(cfg_abs_path, "r") as f:
            self.config = yaml.safe_load(f)

        if not os.path.isabs(self.config['data']['storage_path']):
            self.config['data']['storage_path'] = os.path.join(root_path, self.config['data']['storage_path'])

        self.dm = DataManager(self.config)
        self.reporter = PerformanceReporter(self.config)
        self.logger = logging.getLogger("GapSpreadBacktest")

    def find_previous_trading_day_close(self, current_date, underlying):
        # Look back up to 7 days
        for i in range(1, 8):
            prev_date = current_date - timedelta(days=i)
            if is_trading_day(prev_date):
                start_dt = datetime.combine(prev_date.date(), time(9, 15))
                end_dt = datetime.combine(prev_date.date(), time(15, 30))
                spot_df = self.dm.get_spot_candles(underlying, start_dt, end_dt)
                if spot_df.empty:
                    continue
                # Get the last candle of the day
                last_row = spot_df.iloc[-1]
                # Fallback to the hardcoded close if we aren't completely confident it's the 15:15 close,
                # but `.iloc[-1]` safely captures the last available EOD close.
                return last_row['close']
        return None

    def run(self, start_date_str, end_date_str):
        start_date = pd.to_datetime(start_date_str)
        end_date = pd.to_datetime(end_date_str)

        self.logger.info(f"Starting 5-year Gap Spread Backtest: {start_date.date()} to {end_date.date()}")

        trades = []
        current_capital = 500000

        current_date = start_date
        while current_date <= end_date:
            if is_trading_day(current_date):
                day_trades = self.process_day(current_date)
                if day_trades:
                    # In a spread, we log both legs separately but running capital reflects the net combined
                    net_day_pnl = sum([t['pnl'] for t in day_trades])
                    current_capital += net_day_pnl

                    for t in day_trades:
                        t['running_capital'] = current_capital
                        trades.append(t)

            current_date += timedelta(days=1)
            # Clear cache daily to save memory
            self.dm.clear_cache(clear_spot=True)

        return pd.DataFrame(trades)

    def process_day(self, date):
        underlying = 'NIFTY'

        expiry = get_expiry_for_date(underlying, date.date())
        if not expiry:
            return None

        start_dt = datetime.combine(date.date(), time(9, 15))
        end_dt = datetime.combine(date.date(), time(15, 30))

        spot_df = self.dm.get_spot_candles(underlying, start_dt, end_dt)
        if spot_df.empty:
            return None

        # 1. Evaluate gap
        prev_close = self.find_previous_trading_day_close(date, underlying)
        if not prev_close:
            return None

        open_row = spot_df[spot_df['datetime'] == start_dt]
        if open_row.empty:
            return None

        today_open = open_row['open'].iloc[0]

        if today_open >= prev_close:
            direction = "BULL_CALL"
        else:
            direction = "BEAR_PUT"

        # 2. Extract 9:45 spot
        entry_time = datetime.combine(date.date(), time(9, 45))
        exit_time = datetime.combine(date.date(), time(15, 15))

        entry_row = spot_df[spot_df['datetime'] == entry_time]
        if entry_row.empty:
            return None

        spot_price = entry_row['open'].iloc[0]
        atm_strike = round(spot_price / 50) * 50

        # 5 Strikes = 250 points
        if direction == "BULL_CALL":
            buy_strike = atm_strike
            buy_type = 'CE'
            sell_strike = atm_strike + 250
            sell_type = 'CE'
        else: # BEAR_PUT
            buy_strike = atm_strike
            buy_type = 'PE'
            sell_strike = atm_strike - 250
            sell_type = 'PE'

        lot_size = get_historical_lot_size(underlying, date.date())
        # EXACTLY 1 LOT
        lots = 1
        total_qty = lot_size * lots

        buy_symbol = self.dm.build_option_symbol(underlying, date, buy_strike, buy_type, use_historical=True)
        sell_symbol = self.dm.build_option_symbol(underlying, date, sell_strike, sell_type, use_historical=True)

        buy_df = self.dm.get_derivative_candles(underlying, buy_symbol, date.year, start_dt, end_dt)
        sell_df = self.dm.get_derivative_candles(underlying, sell_symbol, date.year, start_dt, end_dt)

        if buy_df.empty or sell_df.empty:
            return None

        # Get Entry rows
        buy_entry_row = buy_df[buy_df['datetime'] == entry_time]
        sell_entry_row = sell_df[sell_df['datetime'] == entry_time]

        if buy_entry_row.empty or sell_entry_row.empty:
            return None

        b_entry_price = buy_entry_row['open'].iloc[0]
        s_entry_price = sell_entry_row['open'].iloc[0]

        # Iterate over intraday candles from 10:00 to 15:15
        # 15m intervals
        times_to_check = pd.date_range(start=datetime.combine(date.date(), time(10, 0)),
                                       end=exit_time, freq='15min')

        final_exit_time = exit_time
        b_exit_price = None
        s_exit_price = None
        reason = "TIME_EXIT"
        actual_pnl = 0

        for t in times_to_check:
            # Check if data exists for this time
            b_t_row = buy_df[buy_df['datetime'] == t]
            s_t_row = sell_df[sell_df['datetime'] == t]

            if b_t_row.empty or s_t_row.empty:
                continue

            b_close = b_t_row['close'].iloc[0]
            s_close = s_t_row['close'].iloc[0]

            # PNL calculation at time t
            b_pnl = (b_close - b_entry_price) * total_qty
            s_pnl = (s_entry_price - s_close) * total_qty
            combined_pnl = b_pnl + s_pnl

            if combined_pnl <= -2000:
                final_exit_time = t
                b_exit_price = b_close
                s_exit_price = s_close
                reason = "SL_HIT"
                # Cap loss between 2k-2.2k -> Force combined PNL to -2100 to simulate exact SL fill + slip
                break

        # If loop finished without hitting SL, use exit_time prices
        if reason == "TIME_EXIT":
            b_x_row = buy_df[buy_df['datetime'] == exit_time]
            s_x_row = sell_df[sell_df['datetime'] == exit_time]

            if b_x_row.empty or s_x_row.empty:
                # If 15:15 data is completely missing, we have an incomplete day, abort
                return None

            b_exit_price = b_x_row['close'].iloc[0]
            s_exit_price = s_x_row['close'].iloc[0]

        b_pnl = (b_exit_price - b_entry_price) * total_qty
        s_pnl = (s_entry_price - s_exit_price) * total_qty

        # User requirement: Cap ANY loss above 2k at 2500.
        if (b_pnl + s_pnl) < -2000:
            b_pnl = -1250
            s_pnl = -1250
            reason = "APP_MAX_LOSS"

        # Cost base simulating margin rule: spreading 2.5L across the legs.
        # This will ensure "Capital Deployed" appears correctly in report stats.
        margin_per_leg = 250000 / 2

        # Override charges: flat 400 per day = 200 per leg
        flat_charge_per_leg = 200

        day_trades = []
        # Buy leg
        day_trades.append({
            'symbol': buy_symbol,
            'entry_time': entry_time,
            'exit_time': final_exit_time,
            'entry_price': b_entry_price,
            'exit_price': b_exit_price,
            'qty': total_qty,
            'pnl': b_pnl,
            'reason': reason,
            'underlying': underlying,
            'opt_type': buy_type,
            'override_charges': flat_charge_per_leg,
            'cost': margin_per_leg
        })

        # Sell leg
        day_trades.append({
            'symbol': sell_symbol,
            'entry_time': entry_time,
            'exit_time': final_exit_time,
            'entry_price': s_entry_price,
            'exit_price': s_exit_price,
            'qty': total_qty,
            'pnl': s_pnl,
            'reason': reason,
            'underlying': underlying,
            'opt_type': sell_type,
            'override_charges': flat_charge_per_leg,
            'cost': margin_per_leg
        })

        return day_trades

if __name__ == "__main__":
    setup_logging()

    tester = GapSpreadBacktester()
    tester.config['capital']['initial'] = 500000
    tester.reporter.config['capital']['initial'] = 500000

    start = tester.config.get('backtest', {}).get('start_date', "2020-01-01")
    end = tester.config.get('backtest', {}).get('end_date', "2025-12-31")

    df = tester.run(start, end)

    if not df.empty:
        print(f"\nBacktest completed with {len(df)} trades.")
        report_data = tester.reporter.generate_report(df, custom_prefix="GAP_SPREAD_NIFTY_5Yr")
    else:
        print("No trades found in the specified period.")
