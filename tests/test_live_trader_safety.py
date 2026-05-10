import pytest
from unittest.mock import MagicMock, patch
from live.live_trader import LiveTrader
import datetime

import yaml
import os

@pytest.fixture
def mock_config():
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    config['trading']['paper_trading'] = True
    config['risk']['slippage_abort_pct'] = 0.04
    config['risk']['slippage_abort_min_points'] = 5
    return config

@pytest.fixture
def trader(mock_config):
    with patch('live.live_trader.GrowwClient'), \
         patch('live.live_trader.DataManager'), \
         patch('live.live_trader.TelegramNotifier'), \
         patch('live.live_trader.OrderManager'), \
         patch('live.live_trader.TradeTracker'), \
         patch('live.live_trader.TradeLogger'):
        t = LiveTrader(mock_config)
        t.strategy = MagicMock()
        t.om = MagicMock()
        t.client = MagicMock()
        t.candle_builder = MagicMock()
        return t

def test_inverted_sl_abort(trader):
    # Setup pending trade
    pending = {
        'order_id': '123',
        'underlying': 'NIFTY',
        'qty': 50,
        'trading_symbol': 'NSE-NIFTY-OPT',
        'original_symbol': 'NSE-NIFTY-OPT',
        'trigger_price': 100.0,
        'signal': {
            'sl': 110.0, # SL > fill_price
            'targets': [120.0]
        }
    }

    trader._activate_trade_from_pending(pending, fill_price=105.0)

    # Assert
    trader.om.place_exit_order.assert_called_once_with('NSE-NIFTY-OPT', 50, 'NSE-NIFTY-OPT', "INVERTED_SL_ABORT")
    trader.strategy.consume_alert.assert_called_once_with('NSE-NIFTY-OPT')

def test_circuit_breaker_continuity(trader):
    # Setup
    trader.underlyings = ['NIFTY']
    trader.tracked_options = {'NIFTY': {'OPT1': {}}}

    # Mock batch ltp
    trader.client.get_batch_ltp.return_value = {'OPT1': 100.0}

    # Mock candle builder
    trader.candle_builder.feed.return_value = {'datetime': datetime.datetime.now()}
    trader.candle_builder.missed_candles.return_value = 2 # gap >= 30m

    trader._poll_option_ltps()

    # Assert per-symbol circuit breaker activated
    assert hasattr(trader, 'circuit_breaker_active_symbols')
    assert 'OPT1' in trader.circuit_breaker_active_symbols

def test_partial_fill_activation(trader):
    # Setup
    pending = {
        'order_id': '123',
        'qty': 50,
        'trigger_price': 100.0,
        'symbol': 'OPT1'
    }
    trader.pending_entries = {'OPT1': pending}

    # LIVE mode
    trader.paper_trading = False

    # Mock OrderManager.check_order_fill
    trader.om.check_order_fill.return_value = {
        'status': 'PARTIALLY_FILLED',
        'filled_qty': 25,
        'fill_price': 102.0
    }

    with patch.object(trader, '_activate_trade_from_pending') as mock_activate:
        trader._monitor_pending_entries()

        # Assert _activate_trade_from_pending called with override_qty=25
        mock_activate.assert_called_once()
        args, kwargs = mock_activate.call_args
        assert kwargs.get('override_qty') == 25
        assert kwargs.get('fill_price') == 102.0

        # Assert remainder is cancelled
        # We check it's removed from pending_entries because _monitor_pending_entries
        # removes it after activation and cancel call.
        assert 'OPT1' not in trader.pending_entries

def test_timeout_cancel_failure_keeps_pending_entry(trader):
    # Setup: 31 seconds ago (timeout > 30s)
    from live.live_trader import _ist_now
    now = _ist_now()
    placed_at = now - datetime.timedelta(seconds=31)

    pending = {
        'order_id': '123',
        'qty': 50,
        'trigger_price': 100.0,
        'symbol': 'OPT1',
        'placed_at': placed_at
    }
    trader.pending_entries = {'OPT1': pending}
    trader.paper_trading = False

    # Mock cancel_order to fail
    trader.om.cancel_order.return_value = False

    # Mock status to be OPEN
    trader.om.check_order_fill.return_value = {
        'status': 'OPEN',
        'filled_qty': 0,
        'fill_price': 0.0
    }

    trader._monitor_pending_entries()

    # Assert symbol still in pending_entries
    assert 'OPT1' in trader.pending_entries
    trader.telegram._send_to_owner.assert_any_call(
        "🚨 <b>Timeout Cancel Failed</b>\n"
        "Symbol: <code>OPT1</code>\nOrder: 123\n"
        "SL-M order may still be live. Check Groww NOW."
    )

def test_partial_fill_activates_and_cancels_remainder(trader):
    # Setup
    pending = {
        'order_id': '123',
        'qty': 50,
        'trigger_price': 100.0,
        'symbol': 'OPT1'
    }
    trader.pending_entries = {'OPT1': pending}
    trader.paper_trading = False

    # Mock partial fill
    trader.om.check_order_fill.return_value = {
        'status': 'PARTIALLY_FILLED',
        'filled_qty': 25,
        'fill_price': 102.0
    }

    with patch.object(trader, '_activate_trade_from_pending') as mock_activate, \
         patch.object(trader, '_cancel_with_retry') as mock_cancel:
        trader._monitor_pending_entries()

        # Assert activation with override_qty=25
        mock_activate.assert_called_once()
        _, kwargs = mock_activate.call_args
        assert kwargs.get('override_qty') == 25

        # Assert cancel called for remainder
        mock_cancel.assert_called_once_with('123', context="Cancel partial fill remainder for OPT1")

        # Assert removed from pending
        assert 'OPT1' not in trader.pending_entries

def test_cancel_with_retry_exhaustion_sends_critical_alert(trader):
    # Mock cancel_order to succeed but status stays OPEN
    trader.om.cancel_order.return_value = True
    trader.client.get_order_status.return_value = {
        'status': 'OPEN'
    }

    result = trader._cancel_with_retry('123', context="Test")

    # Assert failure after retries
    assert result is False
    trader.telegram._send_to_owner.assert_any_call(
        f"🚨 <b>CRITICAL: Cancel Failed</b>\n"
        f"Order: <code>123</code>\n"
        f"Context: Test\n"
        f"Order may still be LIVE after 3 retries.\n"
        f"<b>CHECK GROWW APP NOW.</b>"
    )
