import pytest
import os
import json
import yaml
import pandas as pd
from unittest.mock import MagicMock, patch
from live.live_trader import LiveTrader
from datetime import datetime, timedelta

@pytest.fixture
def test_config(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()
    return {
        'trading': {
            'paper_trading': False,
            'order_poll_interval_seconds': 1,
            'window': {
                'start': '09:15',
                'end': '15:30',
                'auto_square_off': '15:15'
            },
            'symbol_parse_mode': 'strict'
        },
        'strategy': {
            'rsi': {'period': 14, 'threshold': 60, 'warmup_periods': 100},
            'alert_validity': 2,
            'lots_per_trade': 1,
            'exit_mode': 'single_lot',
            'single_lot_exit_target': 2,
            'signal_window_start': '00:00',
            'signal_window_end': '23:59'
        },
        'indices': {
            'NIFTY': {
                'lot_size': 1,
                'tick_size': 0.05,
                'spot_symbol': 'NSE_NIFTY',
                'expiry_offset_days': 0
            }
        },
        'risk': {'max_loss_per_day': 10000},
        'data': {'storage_path': str(tmp_path / "data")},
        'logging': {'trade_log_path': str(tmp_path / "logs")}
    }

def test_full_trade_lifecycle(test_config, tmp_path):
    # Setup mocks
    mock_client = MagicMock()

    # 1. Warmup spot candles
    now = datetime.now()
    history = []
    # Flat start
    for i in range(110):
        val = 100.0 + (0.1 if i % 2 == 0 else -0.1)
        history.append({
            'datetime': now - timedelta(minutes=15*(150-i)),
            'open': val-1, 'high': val+0.5, 'low': val-2, 'close': val, 'volume': 1000
        })
    # Sharp rise
    for i in range(110, 150):
        val = 100.0 + (i - 110) * 5.0
        history.append({
            'datetime': now - timedelta(minutes=15*(150-i)),
            'open': val-4, 'high': val+2, 'low': val-5, 'close': val, 'volume': 1000
        })
    spot_df = pd.DataFrame(history)
    spot_df.set_index('datetime', inplace=True)

    mock_client.get_historical_candles.return_value = spot_df
    mock_client.get_ltp.return_value = 150.0
    mock_client.place_order.return_value = {'groww_order_id': 'ENTRY_123', 'status': 'SUCCESS'}
    mock_client.get_order_status.return_value = {
        'status': 'COMPLETE', 'fill_price': 150.0, 'filled_quantity': 1
    }
    mock_client.get_balance.return_value = 100000

    # Mock Telegram to avoid network calls
    with patch('live.live_trader.GrowwClient', return_value=mock_client), \
         patch('live.live_trader.TelegramNotifier'), \
         patch('live.live_trader.TradeTracker') as mock_tracker_cls:

        # Setup tracker mock
        mock_tracker = mock_tracker_cls.return_value
        mock_tracker.get_active_trades.return_value = []
        mock_tracker.add_active_trade.return_value = "BOT_123"

        trader = LiveTrader(test_config)
        trader.tracker = mock_tracker
        trader.underlyings = ['NIFTY']
        trader.spot_symbols = {'NIFTY': 'NSE_NIFTY'}
        trader.expiry_dates = {'NIFTY': datetime.now().date()}
        trader._is_inside_trading_window = MagicMock(return_value=True)

        # 1. Detect Alert
        trader._update_option_universe()

        # Manually trigger signal logic
        # We need a candle where prev_rsi < 60 and curr_rsi >= 60
        trader._process_strategy_logic()

        assert len(trader.pending_entries) > 0, "Should have a pending entry after Alert"
        print("Success: Alert created.")

        # 2. Simulate Entry Fill
        trader._monitor_pending_entries()

        # Verify activation
        assert len(trader.active_orders) > 0
        mock_tracker.add_active_trade.assert_called()
        print("Success: Trade Activated.")
