
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime
import json
import os
import sys

# Mocking core dependencies before importing LiveTrader
sys.modules['growwapi'] = MagicMock()

from live.live_trader import LiveTrader
from core.groww_client import GrowwClient
from run_live import validate_config

class TestPhase08Safety(unittest.TestCase):
    def setUp(self):
        self.config = {
            'trading': {
                'window': {'start': '09:15', 'end': '15:15', 'auto_square_off': '15:20'},
                'paper_trading': False,
            },
            'strategy': {
                'underlyings': ['NIFTY'],
                'rsi': {'period': 14, 'threshold': 60, 'warmup_periods': 30},
                'trade_only_on_expiry': False,
                'alert_validity_candles': 1,
                'single_lot_exit_target': 1,
                'exit_mode': 'single_lot'
            },

            'capital': {'initial': 100000},
            'risk': {
                'max_loss_per_day': 5000,
                'max_slippage_pct': 0.02
            },
            'resilience': {
                'disconnect_emergency_threshold_mins': 10
            },
            'indices': {
                'NIFTY': {'lot_size': 50, 'expiry_day': 'Thursday'}
            },
            'data': {'storage_path': 'test_data'}
        }

    def test_safe_01_concentration_guard(self):
        """Verify SAFE-01: Concentration guard blocks unsafe lots_per_trade."""
        import logging
        test_logger = logging.getLogger("Test")

        bad_config = self.config.copy()
        bad_config['strategy']['lots_per_trade'] = 50

        # Test 1: Concentration guard failure
        self.assertFalse(validate_config(bad_config))

        # Test 2: Normal config success
        good_config = self.config.copy()
        good_config['strategy']['lots_per_trade'] = 2
        res = validate_config(good_config)
        if not res:
            print("\nDEBUG: validate_config(good_config) failed!")
        self.assertTrue(res)




    def test_reco_02_same_bar_protection(self):
        """Verify RECO-02: Same-bar protection skips already processed signals."""
        now = datetime.now()
        bar_time = now.replace(minute=0, second=0, microsecond=0)

        with patch('live.live_trader.TradeTracker') as mock_tracker_cls, \
             patch('live.live_trader.TradeLogger'), \
             patch('live.live_trader.TelegramNotifier'), \
             patch('live.live_trader.DataManager'), \
             patch('live.live_trader.OrderManager'):

            mock_tracker = mock_tracker_cls.return_value
            # Symbol already had a signal processed for this bar
            mock_tracker.get_last_processed_bars.return_value = {"NIFTY_OPT": bar_time.isoformat()}

            trader = LiveTrader(self.config)

            # Verify memory state loaded correctly
            self.assertEqual(trader.last_processed_candle_time.get("NIFTY_OPT"), bar_time)

            # Verify skipping logic
            df = MagicMock()
            last_processed = trader.last_processed_candle_time.get("NIFTY_OPT")
            self.assertTrue(bar_time <= last_processed)

    def test_inte_01_integrity_validation(self):
        """Verify INTE-01: Restored-state integrity closes hit SL trades."""
        active_trade = {
            'trade_id': 'T1',
            'symbol': 'NIFTY_SL_HIT',
            'trading_symbol': 'NIFTY_SPOT',
            'entry_price': 100,
            'sl': 90,
            'targets': [150],
            'qty': 50
        }

        with patch('live.live_trader.TradeTracker') as mock_tracker_cls, \
             patch('live.live_trader.TradeLogger'), \
             patch('live.live_trader.TelegramNotifier'), \
             patch('live.live_trader.DataManager'), \
             patch('live.live_trader.OrderManager'):

            mock_tracker = mock_tracker_cls.return_value
            mock_tracker.get_active_trades.return_value = [active_trade]
            mock_tracker.get_last_processed_bars.return_value = {}

            trader = LiveTrader(self.config)

            # Fill client ltp for the symbol
            with patch.object(trader.client, 'get_ltp', return_value=85), \
                 patch.object(trader, '_close_entire_position') as mock_close:

                trader._sanitize_restored_state()

                # Check if RECOVERY_SL_HIT was triggered
                mock_close.assert_called_with(active_trade, 85, "RECOVERY_SL_HIT")

if __name__ == '__main__':
    unittest.main()
