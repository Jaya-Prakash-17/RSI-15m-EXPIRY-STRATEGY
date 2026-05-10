import pytest
from unittest.mock import MagicMock, patch
import datetime
import os
import yaml
from execution.order_manager import OrderManager
from core.groww_client import GrowwClient
from live.live_trader import LiveTrader

@pytest.fixture
def mock_config():
    return {
        'trading': {
            'paper_trading': False,
            'window': {'start': '09:15', 'end': '15:15', 'auto_square_off': '15:25'}
        },
        'risk': {
            'slippage_abort_pct': 0.04,
            'slippage_abort_min_points': 2,
            'max_slippage_pct': 0.02,
            'max_consecutive_losses': 3,
            'max_loss_per_day': 6000
        },
        'indices': {
            'NIFTY': {'tick_size': 0.05}
        },
        'strategy': {
            'rsi': {'period': 14},
            'gap_recalc_pct': 0.02,
            'trade_only_on_expiry': True
        }
    }

@pytest.fixture
def om(mock_config):
    client = MagicMock()
    return OrderManager(mock_config, client=client)

# PROMPT 2: check_order_fill schema consistency
def test_check_order_fill_complete_schema(om):
    om.client.get_order_status.return_value = {
        'status': 'COMPLETE',
        'fill_price': 100.5,
        'filled_quantity': 50
    }
    res = om.check_order_fill('123', 'OPT1')
    assert res == {'status': 'COMPLETE', 'fill_price': 100.5, 'filled_qty': 50}

def test_check_order_fill_partial_schema(om):
    om.client.get_order_status.return_value = {
        'status': 'PARTIALLY_FILLED',
        'avg_price': 102.0,
        'filled_qty': 25
    }
    res = om.check_order_fill('123', 'OPT1')
    assert res == {'status': 'PARTIALLY_FILLED', 'fill_price': 102.0, 'filled_qty': 25}

def test_check_order_fill_cancelled_schema(om):
    om.client.get_order_status.return_value = {
        'status': 'CANCELLED'
    }
    res = om.check_order_fill('123', 'OPT1')
    assert res == {'status': 'CANCELLED', 'fill_price': 0.0, 'filled_qty': 0}

def test_check_order_fill_unknown_status_schema(om):
    om.client.get_order_status.return_value = {
        'status': 'SOMETHING_NEW',
        'unusual_key': 10
    }
    res = om.check_order_fill('123', 'OPT1')
    assert res == {'status': 'SOMETHING_NEW', 'fill_price': 0.0, 'filled_qty': 0}

# PROMPT 4: slippage_abort_min_points logic
def test_slippage_abort_cheap_option(mock_config):
    # Setup LiveTrader with new default = 2
    with patch('live.live_trader.GrowwClient'), \
         patch('live.live_trader.DataManager'), \
         patch('live.live_trader.TelegramNotifier'), \
         patch('live.live_trader.OrderManager'), \
         patch('live.live_trader.TradeTracker'), \
         patch('live.live_trader.TradeLogger'), \
         patch('live.live_trader.ExpiryRSIBreakout'):

        trader = LiveTrader(mock_config)
        trader.slippage_abort_min_points = 2
        trader.slippage_abort_pct = 0.04
        trader.strategy = MagicMock()

        pending = {
            'order_id': '123',
            'underlying': 'NIFTY',
            'qty': 50,
            'trading_symbol': 'OPT1',
            'trigger_price': 20.0, # Cheap option
            'signal': {'sl': 15.0, 'targets': [25.0]}
        }

        # Test case: gap_pct=0.05 (>4%), gap_points=1.5 (<old 5, >new 0?)
        # Wait, if gap_points is 1.5, it is < 2 (new default).
        # So it should NOT abort with default 2.

        # Let's try gap_points = 2.1 ( > 2)
        fill_price = 22.1 # gap_points = 2.1, gap_pct = 2.1/20 = 10.5%

        with patch.object(trader, '_save_strategy_state'):
            trader._activate_trade_from_pending(pending, fill_price=fill_price)

            # Should abort with default 2
            trader.om.place_exit_order.assert_called_with('OPT1', 50, 'OPT1', "GAP_FILL_ABORT")

        # Reset and test with default 5
        trader.om.place_exit_order.reset_mock()
        trader.slippage_abort_min_points = 5

        trader._activate_trade_from_pending(pending, fill_price=fill_price)
        # Should NOT abort with default 5 because gap_points (2.1) < 5
        # It might recal instead
        trader.om.place_exit_order.assert_not_called()

# PROMPT 6: last_success_at update
def test_last_success_at_updates_on_success():
    client = GrowwClient(api_key="test", api_secret="test")
    # Mock _authenticate to avoid real calls
    client._authenticate = MagicMock()
    client.client = MagicMock()

    initial_time = client.last_success_at

    # Mock successful get_ltp
    client.client.get_ltp.return_value = {'NSE_NIFTY': 22000.0}

    import time
    time.sleep(0.1)

    client.get_ltp('NIFTY')

    assert client.last_success_at > initial_time
