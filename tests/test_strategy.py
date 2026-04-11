import pytest
import pandas as pd
import numpy as np
from strategy.expiry_rsi_breakout import ExpiryRSIBreakout
from datetime import datetime, timedelta

@pytest.fixture
def config():
    return {
        'strategy': {
            'rsi': {'period': 14, 'threshold': 60, 'warmup_periods': 100},
            'alert_validity': 2,
            'alert_negation': True,
            'lots_per_trade': 3,
            'min_sl_pct': 0.08,
            'safe_sl_mode': True,
            'safe_sl_max_loss': 5000
        },
        'indices': {
            'NIFTY': {'lot_size': 75, 'tick_size': 0.05},
            'BANKNIFTY': {'lot_size': 15, 'tick_size': 0.05}
        }
    }

def test_rsi_parity(config):
    strategy = ExpiryRSIBreakout(config)

    # Generate 150 random close prices
    prices = pd.Series(100 + np.cumsum(np.random.randn(150)), name='close')
    prices.index = pd.date_range(start='2026-01-01', periods=150, freq='15min')

    # Calculate via single method
    single_res = strategy.calculate_latest_rsi(prices, return_prev=True)

    # Calculate via batch method
    batch_res = strategy.batch_calculate_rsi({'TEST': prices})

    assert single_res[0] == pytest.approx(batch_res['TEST'][0], abs=1e-6)
    assert single_res[1] == pytest.approx(batch_res['TEST'][1], abs=1e-6)

def test_alert_to_entry_flow(config):
    strategy = ExpiryRSIBreakout(config)
    symbol = "NSE-NIFTY-TEST"

    # 1. Warmup history (110 candles choppy/flat)
    history = []
    curr = 100.0
    for i in range(110):
        # alternate small gains and losses to keep RSI around 50
        curr += 0.5 if i % 2 == 0 else -0.5
        history.append(curr)

    # Add a breakout sequence
    history.extend([110.0, 120.0, 130.0, 140.0, 150.0])

    opens = [h - 1.0 for h in history]  # Ensure green candle
    highs = [h + 2.0 for h in history]
    lows = [h - 2.0 for h in history]

    price_history = pd.DataFrame({
        'open': opens,
        'high': highs,
        'low': lows,
        'close': history,
        'datetime': [datetime(2026, 1, 1, 10, 0) + timedelta(minutes=15*i) for i in range(len(history))]
    })

    # Loop through and feed candles
    alert_triggered = False
    entry_triggered = False

    for i in range(100, len(price_history)):
        row = price_history.iloc[i]
        hist = price_history.iloc[:i+1]['close']

        signal = strategy.check_signal(symbol, row, price_history=hist)

        if signal and signal['action'] == 'ALERT':
            alert_triggered = True
            # Simulate a breakout in the next candle
            if i + 1 < len(price_history):
                price_history.at[i+1, 'high'] = row['high'] + 10

        if signal and signal['action'] == 'ENTRY':
            entry_triggered = True
            break

    assert alert_triggered, "Alert should have triggered"
    assert entry_triggered, "Entry should have triggered on the high break"

def test_safe_sl_cap(config):
    strategy = ExpiryRSIBreakout(config)
    symbol = "NSE-NIFTY-TEST" # lot_size 75

    entry_price = 200
    alert_low = 100
    # Raw SL Dist = 200 - 100 + 1 = 101
    # Max Loss = 101 * 3 lots * 75 units = 22,725
    # Max allowed loss is 5000.
    # Max dist = 5000 / (3 * 75) = 22.22

    sl, is_safe, raw = strategy._calculate_effective_sl(symbol, entry_price, alert_low)

    assert is_safe
    assert sl > alert_low  # SL should be moved UP from the candle low to cap risk
    assert (entry_price - sl) * (3 * 75) <= 5000 + 1 # within tolerance
