
import sys
import os
import logging

import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time as datetime_time

from unittest.mock import MagicMock, patch
import yaml

# Mock imports before loading LiveTrader
sys.modules['core.groww_client'] = MagicMock()
sys.modules['utils.telegram_notifier'] = MagicMock()

from live.live_trader import LiveTrader

def test_multi_index_priority():
    print("\n[VERIFY] Testing Multi-Index Priority Allocation (NIFTY > SENSEX > BANKNIFTY)")

    with open('config.yaml', 'r') as f:
        config = yaml.safe_load(f)

    # Force test parameters
    config['trading']['paper_trading'] = True
    config['risk']['max_total_premium_deployed'] = 100000

    with patch('live.live_trader.DataManager') as MockDM:
        with patch('live.live_trader.OrderManager') as MockOM:
            with patch('live.live_trader.TradeTracker') as MockTracker:
                trader = LiveTrader(config)
                # Enable logging to see why it fails
                logging.basicConfig(level=logging.INFO)
                trader.logger.addHandler(logging.StreamHandler(sys.stdout))

                trader.underlyings = ['BANKNIFTY', 'NIFTY', 'SENSEX']

                trader.spot_symbols = {u: u for u in trader.underlyings}
                trader.expiry_dates = {u: datetime.now().date() for u in trader.underlyings}
                trader.tracked_options = {u: {f"{u}-2050-01-01-20000-CE": pd.DataFrame()} for u in trader.underlyings}
                trader.start_time = datetime_time(0, 0)
                trader.end_time = datetime_time(23, 59)
                trader.sq_off_time = datetime_time(23, 59)

                # Mock DataManager results for concurrent fetch
                mock_df = pd.DataFrame({
                    'datetime': [datetime.now()],
                    'close': [20000],
                    'open': [19900], 'high': [20100], 'low': [19800], 'volume': [1000]
                })
                trader.dm.get_spot_candles.return_value = mock_df

                # Mock _get_latest_candle to bypass time checks
                trader._get_latest_candle = MagicMock(return_value=mock_df.iloc[0].to_dict())

                # Mock Strategy Alert Candidates
                trader.strategy.check_signal = MagicMock()
                trader.strategy.batch_calculate_rsi = MagicMock(return_value={f"{u}-2050-01-01-20000-CE": (70, 65) for u in trader.underlyings})

                # Mock candle builder for local data
                trader.candle_builder.get_closed_df = MagicMock(return_value=mock_df)

                placement_order = []


                def mock_place_order(best):
                    placement_order.append(best['underlying'])
                    # Populate pending_entries so the correlation check catches it
                    trader.pending_entries[best['symbol']] = {
                        'underlying': best['underlying'],
                        'opt_type': best['opt_type']
                    }
                    print(f" -> Placed order for: {best['underlying']}")


                trader._place_pending_entry = MagicMock(side_effect=mock_place_order)
                trader.tracker.get_active_trades_for_index.return_value = []
                trader.tracker.get_pending_for_index.return_value = []

                # Let's mock _get_warmup_start_time
                trader._get_warmup_start_time = MagicMock(return_value=datetime.now())

                print("Step 1: Testing discovery priority sorting...")
                with patch('utils.expiry_calendar.is_expiry_day', return_value=True):
                    trader.dm.get_expiries.return_value = [datetime.now().strftime("%Y-%m-%d")]
                    indices = trader._get_tradeable_indices()
                    print(f"Indices discovered (ordered): {indices}")
                    assert indices == ['NIFTY', 'SENSEX', 'BANKNIFTY'], f"Priority Sort Failed: {indices}"
                    print("\nStep 2: Testing Parallel Spot Fetch logic...")
                with patch.object(trader.logger, 'error') as mock_log_err:
                    trader._process_strategy_logic()
                    print(f"DM.get_spot_candles calls: {trader.dm.get_spot_candles.call_count}")
                    assert trader.dm.get_spot_candles.call_count >= 3
                    print("Parallel spot fetch verified.")

                print("\nStep 3: Testing Deterministic Priority + Correlation Limit...")
                # Reset mocks and caches
                trader._place_pending_entry.reset_mock()
                trader.last_processed_candle_time = {}
                trader.pending_entries = {}

                # RESET the strategy mock so it starts fresh for this test pass

                trader.strategy.check_signal = MagicMock(side_effect=[

                    # NIFTY-OPT
                    {'action': 'ALERT', 'price': 100, 'sl': 80, 'targets': [150], 'opt_type': 'CE'},
                    # SENSEX-OPT
                    {'action': 'ALERT', 'price': 200, 'sl': 160, 'targets': [300], 'opt_type': 'CE'},
                    # BANKNIFTY-OPT
                    {'action': 'ALERT', 'price': 300, 'sl': 240, 'targets': [450], 'opt_type': 'CE'},
                    # Padding
                    None, None, None, None, None, None
                ])
                placement_order = []




                # We need to bypass the _process_strategy_logic signal loop to inject our candidates
                # or just mock the results bit

                # Set correlation limit to 1
                trader.config['strategy']['max_correlated_positions'] = 1
                trader.tracker.get_active_trades.return_value = [] # Start fresh

                # Simulate the parallel results
                trader._process_strategy_logic()

                print(f"Placement order: {placement_order}")
                # Expect ONLY NIFTY to be placed because correlation limit is 1
                assert len(placement_order) == 1, f"Should only place 1 trade, placed {len(placement_order)}"
                assert placement_order[0] == 'NIFTY', f"Expected NIFTY first, got {placement_order[0]}"
                print("[SUCCESS] Deterministic Priority + Correlation Limit verified.")


if __name__ == "__main__":
    try:
        test_multi_index_priority()
        print("\nALL MULTI-INDEX VERIFICATION TESTS PASSED")
    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
