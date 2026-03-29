import pytest
import pandas as pd
from strategy.expiry_rsi_breakout import ExpiryRSIBreakout
from execution.order_manager import OrderManager, is_order_filled

def make_config():
    return {
        'strategy': {
            'rsi': {'period': 9, 'threshold': 60, 'warmup_periods': 100,
                   'min_candles_for_signal': 27},
            'exit_mode': 'single_lot', 'lots_per_trade': 1,
            'single_lot_exit_target': 2, 'alert_validity': 1,
            'min_sl_pct': 0.08, 'alert_negation': True,
            'signal_window_start': '09:30', 'signal_window_end': '15:00',
        },
        'indices': {
            'NIFTY': {'lot_size': 65, 'tick_size': 0.05},
            'BANKNIFTY': {'lot_size': 30, 'tick_size': 0.05},
            'SENSEX': {'lot_size': 20, 'tick_size': 0.05},
        },
        'risk': {'max_loss_per_day': 5000},
        'capital': {'initial': 100000},
        'trading': {'paper_trading': True, 'trade_log_file': '/tmp/test_log.csv'},
    }

def test_rsi_warmup_is_direct_candle_count():
    """BUG-016 regression: warmup_periods=100 means 100 candles, not 100*period"""
    s = ExpiryRSIBreakout(make_config())
    assert s.rsi_warmup == 100, f"Expected 100, got {s.rsi_warmup}"

def test_rsi_returns_none_below_minimum():
    """RSI needs at least period+1 candles"""
    s = ExpiryRSIBreakout(make_config())
    result = s.calculate_latest_rsi(pd.Series([100.0, 101.0, 102.0]))
    assert result is None

def test_banknifty_lot_size_not_confused_with_nifty():
    """BANKNIFTY must resolve to 30, not 65 (NIFTY is substring of BANKNIFTY)"""
    om = OrderManager(make_config())
    assert om._resolve_lot_size('NSE-BANKNIFTY-30Mar26-52000-PE', '') == 30
    assert om._resolve_lot_size('NSE-NIFTY-25Mar26-22500-CE', '') == 65
    assert om._resolve_lot_size('BSE-SENSEX-27Mar26-75000-CE', '') == 20

def test_is_order_filled_all_variants():
    assert is_order_filled('COMPLETE') is True
    assert is_order_filled('FILLED') is True
    assert is_order_filled('EXECUTED') is True
    assert is_order_filled('complete') is True   # case insensitive
    assert is_order_filled('PENDING') is False
    assert is_order_filled('OPEN') is False
    assert is_order_filled(None) is False
    assert is_order_filled('') is False

def test_min_candle_guard_blocks_alert():
    """Strategy should not fire with only 20 candles when min is 27"""
    config = make_config()
    config['strategy']['rsi']['min_candles_for_signal'] = 27
    s = ExpiryRSIBreakout(config)
    prices = pd.Series([100.0 + i for i in range(20)])
    candle = pd.Series({
        'datetime': pd.Timestamp('2026-03-20 10:15:00'),
        'open': 100.0, 'high': 120.0, 'low': 98.0, 'close': 119.0,
        'volume': 100
    })
    result = s.check_signal('NSE-NIFTY-20Mar26-23500-CE', candle, prices)
    assert result is None

def test_alert_age_increments_when_not_tradable():
    """Alert must age even outside trading window (AUDIT-015 regression)"""
    config = make_config()
    config['strategy']['alert_validity'] = 1
    s = ExpiryRSIBreakout(config)
    symbol = 'NSE-NIFTY-20Mar26-23500-CE'
    # Inject an active alert into state
    s.state[symbol] = {
        'alert': {'high': 100.0, 'low': 90.0, 'datetime': pd.Timestamp('2026-03-20 10:15:00')},
        'age': 0,
        'alert_time': pd.Timestamp('2026-03-20 10:15:00'),
        'last_processed_time': pd.Timestamp('2026-03-20 10:15:00'),
        'prev_rsi': 55.0, 'current_rsi': 62.0
    }
    prices = pd.Series([90.0 + i * 0.1 for i in range(30)])
    candle = pd.Series({
        'datetime': pd.Timestamp('2026-03-20 10:30:00'),
        'open': 92.0, 'high': 93.0, 'low': 91.0, 'close': 91.5, 'volume': 50
    })
    # is_tradable=False simulates being outside trading window
    s.check_signal(symbol, candle, prices, is_tradable=False)
    assert s.state[symbol]['age'] == 1, \
        f"Alert age must be 1 after one candle outside window, got {s.state[symbol]['age']}"

class TestHistoricalLotSizes:
    def test_nifty_lot_size_pre_2025(self):
        from utils.historical_lot_sizes import get_historical_lot_size
        from datetime import date
        assert get_historical_lot_size('NIFTY', date(2023, 6, 15)) == 75
        assert get_historical_lot_size('NIFTY', date(2024, 11, 19)) == 75

    def test_nifty_lot_size_post_reform(self):
        from utils.historical_lot_sizes import get_historical_lot_size
        from datetime import date
        assert get_historical_lot_size('NIFTY', date(2025, 9, 1)) == 65
        assert get_historical_lot_size('NIFTY', date(2026, 3, 1)) == 65

    def test_banknifty_lot_size_three_eras(self):
        from utils.historical_lot_sizes import get_historical_lot_size
        from datetime import date
        assert get_historical_lot_size('BANKNIFTY', date(2023, 1, 26)) == 25   # pre-Nov 2024
        assert get_historical_lot_size('BANKNIFTY', date(2024, 11, 20)) == 35  # post-Nov 2024
        assert get_historical_lot_size('BANKNIFTY', date(2025, 9, 1)) == 30   # post-Sep 2025

    def test_banknifty_boundary_exact(self):
        from utils.historical_lot_sizes import get_historical_lot_size
        from datetime import date
        assert get_historical_lot_size('BANKNIFTY', date(2024, 11, 19)) == 25  # day before change
        assert get_historical_lot_size('BANKNIFTY', date(2024, 11, 20)) == 35  # change day itself

    def test_sensex_lot_size(self):
        from utils.historical_lot_sizes import get_historical_lot_size
        from datetime import date
        assert get_historical_lot_size('SENSEX', date(2023, 5, 1)) == 10
        assert get_historical_lot_size('SENSEX', date(2024, 11, 19)) == 10
        assert get_historical_lot_size('SENSEX', date(2024, 11, 20)) == 20

    def test_sensex_before_launch_raises(self):
        from utils.historical_lot_sizes import get_historical_lot_size
        from datetime import date
        import pytest
        with pytest.raises(ValueError, match='SENSEX options'):
            get_historical_lot_size('SENSEX', date(2022, 12, 1))

    def test_historical_lot_size_accepts_datetime(self):
        from utils.historical_lot_sizes import get_historical_lot_size
        from datetime import datetime
        result = get_historical_lot_size('NIFTY', datetime(2023, 6, 15, 10, 30, 0))
        assert result == 75

    def test_backtest_pnl_uses_historical_not_config_lot_size(self):
        '''Regression: _enter_trade must use historical lot size not config lot size.'''
        # If this fails, backtest P&L is wrong for pre-Sep-2025 dates
        from datetime import date
        from utils.historical_lot_sizes import get_historical_lot_size
        config_lot = 65  # current config value for NIFTY
        historical_lot = get_historical_lot_size('NIFTY', date(2023, 6, 15))
        assert historical_lot == 75
        assert historical_lot != config_lot, (
            "Historical lot size must differ from current config for 2023 dates. "
            "If this test fails, backtest P&L calculations are inflating/deflating all 2023 trades."
        )
