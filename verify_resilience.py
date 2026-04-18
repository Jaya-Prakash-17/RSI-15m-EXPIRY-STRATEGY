
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
import time
import os
import sys

# Mocking core dependencies before importing LiveTrader
sys.modules['growwapi'] = MagicMock()

from live.live_trader import LiveTrader
from core.groww_client import GrowwClient

class TestPhase07Resilience(unittest.TestCase):
    def setUp(self):
        self.config = {
            'trading': {
                'window': {'start': '09:15', 'end': '15:15', 'auto_square_off': '15:20'},
                'paper_trading': False,
                'order_poll_interval_seconds': 1
            },
            'strategy': {
                'underlyings': ['NIFTY'],
                'rsi': {'period': 14, 'threshold': 60, 'warmup_periods': 30},
                'trade_only_on_expiry': False,
                'alert_validity_candles': 1
            },

            'capital': {'initial': 100000},
            'risk': {
                'max_loss_per_day': 5000,
                'max_slippage_pct': 0.02
            },
            'resilience': {
                'disconnect_emergency_threshold_mins': 0.1  # 6 seconds for test
            },
            'indices': {
                'NIFTY': {'lot_size': 50, 'expiry_day': 'Thursday'}
            },
            'data': {'storage_path': 'test_data'}
        }

        # Patching network-dependent initializations
        with patch('live.live_trader.TradeTracker'), \
             patch('live.live_trader.TradeLogger'), \
             patch('live.live_trader.TelegramNotifier'), \
             patch('live.live_trader.DataManager'), \
             patch('live.live_trader.OrderManager'), \
             patch('live.live_trader.GrowwClient._authenticate'):
            self.trader = LiveTrader(self.config)


    def test_netw_01_exponential_backoff(self):
        """Verify NETW-01: Exponential Backoff on 429 errors."""
        client = GrowwClient()
        mock_func = MagicMock()

        # Simulate 429 error 2 times, then success
        mock_func.side_effect = [Exception("429 Rate Limit"), Exception("429 Rate Limit"), "Success"]

        start_time = time.time()
        with patch('time.sleep'): # Don't actually sleep in tests
            result = client._safe_call(mock_func)

        self.assertEqual(result, "Success")
        self.assertEqual(mock_func.call_count, 3)
        self.assertGreater(client.last_success_at, datetime.now() - timedelta(seconds=1))

    def test_reco_01_reconnect_resync(self):
        """Verify RECO-01: Reconnect resync clears caches."""
        self.trader._ltp_cache['TEST'] = (100, datetime.now())
        self.trader._candle_cache['TEST'] = MagicMock()

        self.trader._reconnect_resync()

        self.assertEqual(len(self.trader._ltp_cache), 0)
        self.assertEqual(len(self.trader._candle_cache), 0)
        self.assertTrue(self.trader._is_reconnecting)

    def test_safe_02_emergency_flatten(self):
        """Verify SAFE-02: Emergency flatten fires MARKET orders on active trades."""
        # Setup an active trade
        active_trade = {
            'trade_id': 'T1',
            'symbol': 'NIFTY26APR24000CE',
            'remaining_qty': 50,
            'entry_price': 100
        }
        self.trader.tracker.get_active_trades.return_value = [active_trade]

        with patch.object(self.trader.client, 'place_order') as mock_place:
            self.trader._emergency_flatten()

            # Check if MARKET SELL was fired
            mock_place.assert_called_with(
                symbol='NIFTY26APR24000CE',
                qty=50,
                side='SELL',
                order_type='MARKET',
                product='MIS'
            )

        self.assertTrue(self.trader._emergency_halt_active)

    def test_slip_01_slippage_enforcement(self):
        """Verify SLIP-01: Slippage alert triggers on high slippage fill."""
        symbol = "NIFTY_OPT"
        pending = {
            'symbol': symbol,
            'trigger_price': 100.0,
            'qty': 50,
            'order_id': 'O1'
        }
        self.trader.pending_entries[symbol] = pending

        # Mock high slippage fill (105 which is 5% > 2% limit)
        mock_order_status = {
            'status': 'FILLED',
            'fill_price': 105.0,
            'filled_quantity': 50
        }

        with patch.object(self.trader.client, 'get_order_status', return_value=mock_order_status), \
             patch.object(self.trader.telegram, '_send') as mock_tg, \
             patch.object(self.trader, '_activate_trade_from_pending'):

            self.trader._monitor_pending_entries()

            # Check if high slippage alert was sent
            tg_calls = [call.args[0] for call in mock_tg.call_args_list]
            self.assertTrue(any("High Slippage" in c for c in tg_calls))

if __name__ == '__main__':
    unittest.main()
