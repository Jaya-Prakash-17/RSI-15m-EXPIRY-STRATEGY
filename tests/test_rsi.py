# tests/test_rsi.py
import pytest
import pandas as pd
import numpy as np
from strategy.expiry_rsi_breakout import ExpiryRSIBreakout

def test_wilders_rsi_fixed_data():
    """
    Validate Wilder's RSI against a hand-calculated dataset.
    RSI Period = 14.
    """
    config = {
        'strategy': {
            'rsi': {'period': 14, 'threshold': 60, 'warmup_periods': 100},
            'alert_validity': 1,
            'signal_window_start': '09:15',
            'signal_window_end': '15:30'
        },
        'indices': {'NIFTY': {'lot_size': 50, 'tick_size': 0.05}}
    }
    strat = ExpiryRSIBreakout(config)

    # Price series with 15 elements (14 changes)
    # Gains: 2 (x9) = 18. Avg = 18/14 = 1.2857
    # Losses: 1 (x5) = 5. Avg = 5/14 = 0.3571
    # RS = 1.2857 / 0.3571 = 3.6
    # RSI = 100 - (100 / (1 + 3.6)) = 78.26
    prices = [
        100, 102, 101, 103, 105, 104, 106, 108,
        107, 109, 111, 110, 112, 114, 113
    ]

    rsi_vals = strat.calculate_wilder_rsi(prices)

    # Value at index 13 is the first RSI value (seed)
    # print(f"DEBUG: RSI at index 13 = {rsi_vals[13]}")
    assert not np.isnan(rsi_vals[13])
    assert round(rsi_vals[13], 2) == 78.26

def test_rsi_smoothing_convergence():
    """
    Validate that Wilder's smoothing converges correctly over a longer series.
    The iterative approach (avg*13 + current)/14 must match the recursive loop.
    """
    n = 14
    config = {
        'strategy': {'rsi': {'period': n, 'threshold': 60}, 'alert_validity': 1},
        'indices': {'NIFTY': {'lot_size': 50, 'tick_size': 0.05}}
    }
    strat = ExpiryRSIBreakout(config)

    # 50 candles to allow smoothing to settle
    prices = [100 + i + (5 if i % 2 == 0 else -5) for i in range(50)]
    rsi_vals = strat.calculate_wilder_rsi(prices)

    # Verify no EWM bias (re-calculating the last step manually)
    p_last = prices[-1]
    p_prev = prices[-2]
    change = p_last - p_prev
    gain = max(0, change)
    loss = max(0, -change)

    # We need internal avg_gain/avg_loss from previous step to verify the current one
    # calculate_wilder_rsi returns components if asked
    _, _, _, avg_g, avg_l = strat.calculate_wilder_rsi(prices, return_components=True)

    expected_g = (avg_g[-2] * (n-1) + gain) / n
    expected_l = (avg_l[-2] * (n-1) + loss) / n

    assert round(avg_g[-1], 6) == round(expected_g, 6)
    assert round(avg_l[-1], 6) == round(expected_l, 6)

    print(f"Wilder's Convergence Validated: RSI={rsi_vals[-1]:.2f}")

if __name__ == "__main__":
    # Run tests using pytest style discovery but callable as script
    test_wilders_rsi_fixed_data()
    test_rsi_smoothing_convergence()
    print("All RSI tests passed!")
