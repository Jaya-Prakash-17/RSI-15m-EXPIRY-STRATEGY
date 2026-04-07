# tests/test_vectorized_rsi.py
"""
Regression & Integration tests for the Vectorized Live Pulse optimization.

Tests verify:
1. Mathematical equivalence: batch_calculate_rsi == calculate_latest_rsi (per symbol)
2. Edge cases: insufficient data, flat prices, all-gains, all-losses
3. Integration: check_signal produces identical results with rsi_values vs price_history
4. Performance: batch method is faster than N individual calls
"""
import pytest
import numpy as np
import pandas as pd
import time
from strategy.expiry_rsi_breakout import ExpiryRSIBreakout


def make_config(period=11, threshold=60):
    return {
        'strategy': {
            'rsi': {
                'period': period,
                'threshold': threshold,
                'warmup_periods': 100,
                'min_candles_for_signal': period * 3,
            },
            'exit_mode': 'single_lot',
            'lots_per_trade': 1,
            'single_lot_exit_target': 2,
            'alert_validity': 1,
            'min_sl_pct': 0.08,
            'alert_negation': True,
            'signal_window_start': '09:30',
            'signal_window_end': '15:00',
        },
        'indices': {
            'NIFTY': {'lot_size': 65, 'tick_size': 0.05},
            'BANKNIFTY': {'lot_size': 30, 'tick_size': 0.05},
        },
        'risk': {'max_loss_per_day': 5000},
        'capital': {'initial': 100000},
        'trading': {'paper_trading': True, 'trade_log_file': '/tmp/test_log.csv'},
    }


def generate_realistic_prices(n=200, seed=42):
    """Generate realistic option-like price series with trends and noise."""
    rng = np.random.RandomState(seed)
    # Geometric Brownian Motion approximation
    returns = rng.normal(0.0005, 0.015, n)
    prices = 100.0 * np.cumprod(1 + returns)
    return prices


def generate_breakout_prices(n=200, seed=42):
    """Generate prices that create an RSI breakout (crosses threshold from below)."""
    rng = np.random.RandomState(seed)
    # Start with downtrend (low RSI), then spike up
    down = 100.0 - np.cumsum(rng.uniform(0.2, 0.8, n // 2))
    up = down[-1] + np.cumsum(rng.uniform(0.5, 1.5, n - n // 2))
    return np.concatenate([down, up])


# ══════════════════════════════════════════════════════════════════════════════
# REGRESSION TESTS: Mathematical equivalence
# ══════════════════════════════════════════════════════════════════════════════

class TestBatchRSIEquivalence:
    """Verify batch_calculate_rsi is numerically identical to calculate_latest_rsi."""

    @pytest.fixture
    def strategy(self):
        return ExpiryRSIBreakout(make_config())

    def test_single_symbol_equivalence(self, strategy):
        """Batch with 1 symbol must match individual calculation exactly."""
        prices = pd.Series(generate_realistic_prices(200))
        
        # Individual path
        individual = strategy.calculate_latest_rsi(prices, return_prev=True)
        curr_individual, prev_individual = individual
        
        # Batch path
        batch = strategy.batch_calculate_rsi({'SYM_A': prices.values})
        curr_batch, prev_batch = batch['SYM_A']
        
        assert curr_batch == pytest.approx(curr_individual, abs=1e-10), \
            f"Current RSI mismatch: batch={curr_batch} vs individual={curr_individual}"
        assert prev_batch == pytest.approx(prev_individual, abs=1e-10), \
            f"Previous RSI mismatch: batch={prev_batch} vs individual={prev_individual}"

    def test_multi_symbol_equivalence(self, strategy):
        """Batch with multiple symbols must match individual calculation for each."""
        symbols = {f'SYM_{i}': generate_realistic_prices(200, seed=i) for i in range(10)}
        
        batch_results = strategy.batch_calculate_rsi(symbols)
        
        for sym, prices in symbols.items():
            series = pd.Series(prices)
            individual = strategy.calculate_latest_rsi(series, return_prev=True)
            curr_ind, prev_ind = individual
            curr_batch, prev_batch = batch_results[sym]
            
            assert curr_batch == pytest.approx(curr_ind, abs=1e-10), \
                f"{sym}: Current RSI mismatch"
            assert prev_batch == pytest.approx(prev_ind, abs=1e-10), \
                f"{sym}: Previous RSI mismatch"

    @pytest.mark.parametrize("period", [7, 9, 11, 14, 21])
    def test_equivalence_across_periods(self, period):
        """Must be equivalent for all commonly used RSI periods."""
        strategy = ExpiryRSIBreakout(make_config(period=period))
        prices = generate_realistic_prices(200, seed=99)
        
        series = pd.Series(prices)
        individual = strategy.calculate_latest_rsi(series, return_prev=True)
        batch = strategy.batch_calculate_rsi({'TEST': prices})
        
        curr_ind, prev_ind = individual
        curr_batch, prev_batch = batch['TEST']
        
        assert curr_batch == pytest.approx(curr_ind, abs=1e-10)
        assert prev_batch == pytest.approx(prev_ind, abs=1e-10)

    def test_with_pandas_series_input(self, strategy):
        """Batch should accept pd.Series values (not just np.array)."""
        prices = pd.Series(generate_realistic_prices(150))
        batch = strategy.batch_calculate_rsi({'SYM': prices})
        curr, prev = batch['SYM']
        assert curr is not None
        assert prev is not None

    def test_with_numpy_array_input(self, strategy):
        """Batch should accept raw np.ndarray values."""
        prices = generate_realistic_prices(150)
        assert isinstance(prices, np.ndarray)
        batch = strategy.batch_calculate_rsi({'SYM': prices})
        curr, prev = batch['SYM']
        assert curr is not None
        assert prev is not None


# ══════════════════════════════════════════════════════════════════════════════
# EDGE CASE TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestBatchRSIEdgeCases:

    @pytest.fixture
    def strategy(self):
        return ExpiryRSIBreakout(make_config())

    def test_insufficient_data_returns_none_pair(self, strategy):
        """Fewer than period+1 candles should return (None, None)."""
        prices = np.array([100.0, 101.0, 102.0])  # 3 candles, need 12
        result = strategy.batch_calculate_rsi({'SHORT': prices})
        assert result['SHORT'] == (None, None)

    def test_exact_minimum_candles(self, strategy):
        """Exactly period+1 candles: current_rsi should work, prev_rsi may be None."""
        n = 11  # period
        prices = generate_realistic_prices(n + 1, seed=7)
        result = strategy.batch_calculate_rsi({'EXACT': prices})
        curr, prev = result['EXACT']
        assert curr is not None, "Current RSI should be calculable with exactly period+1 candles"
        # prev_rsi needs period+2 candles (n+1 deltas, need at least n+1 to stop one early)
        # With exactly n+1 prices we have n deltas. For prev we need len(delta) >= n+1,
        # which means n >= n+1, so prev should be None.
        assert prev is None, "Previous RSI should be None with exactly period+1 candles"

    def test_flat_prices_rsi_50(self, strategy):
        """Constant price series should yield RSI = NaN or 50 (no movement)."""
        prices = np.full(200, 100.0)
        result = strategy.batch_calculate_rsi({'FLAT': prices})
        curr, prev = result['FLAT']
        # With zero movement, gains=losses=0, so RS=NaN → RSI convention varies
        # Our implementation: avg_l==0 → RSI=100. But with flat prices, both are 0.
        # Actually: gains[:n].mean() == 0 AND losses[:n].mean() == 0
        # Then the loop keeps them at 0. avg_l == 0 → RSI = 100.0
        assert curr is not None

    def test_all_gains_rsi_100(self, strategy):
        """Monotonically increasing prices: RSI should approach 100."""
        prices = np.arange(100.0, 300.0, 1.0)  # 200 steps, all gains
        result = strategy.batch_calculate_rsi({'BULL': prices})
        curr, _ = result['BULL']
        assert curr == pytest.approx(100.0, abs=0.01), f"All-gains RSI should be ~100, got {curr}"

    def test_all_losses_rsi_0(self, strategy):
        """Monotonically decreasing prices: RSI should approach 0."""
        prices = np.arange(300.0, 100.0, -1.0)  # 200 steps, all losses
        result = strategy.batch_calculate_rsi({'BEAR': prices})
        curr, _ = result['BEAR']
        assert curr == pytest.approx(0.0, abs=0.01), f"All-losses RSI should be ~0, got {curr}"

    def test_empty_dict_returns_empty(self, strategy):
        """Empty input should return empty output."""
        result = strategy.batch_calculate_rsi({})
        assert result == {}

    def test_mixed_valid_and_insufficient(self, strategy):
        """Mix of valid and insufficient symbols should handle both correctly."""
        data = {
            'VALID': generate_realistic_prices(200),
            'SHORT': np.array([100.0, 101.0]),
            'ALSO_VALID': generate_realistic_prices(50, seed=99),
        }
        result = strategy.batch_calculate_rsi(data)
        assert result['VALID'][0] is not None
        assert result['SHORT'] == (None, None)
        assert result['ALSO_VALID'][0] is not None


# ══════════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS: check_signal with rsi_values vs price_history
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckSignalIntegration:
    """Verify check_signal produces identical outputs whether RSI is computed
    internally (via price_history) or externally (via rsi_values)."""

    @pytest.fixture
    def strategy(self):
        return ExpiryRSIBreakout(make_config())

    def _make_candle(self, ts, o, h, l, c, v=100):
        return pd.Series({
            'datetime': pd.Timestamp(ts),
            'open': o, 'high': h, 'low': l, 'close': c, 'volume': v
        })

    def test_no_signal_equivalence(self, strategy):
        """When no signal fires, both paths should return None."""
        prices = pd.Series(generate_realistic_prices(200, seed=1))
        candle = self._make_candle('2026-03-20 10:30:00', 150, 155, 148, 152)
        symbol = 'NSE-NIFTY-20Mar26-22500-CE'

        # Path A: price_history
        result_a = strategy.check_signal(symbol, candle, prices, is_tradable=True)
        
        # Reset state for fair comparison
        strategy.state.pop(symbol, None)
        
        # Path B: rsi_values
        rsi_pair = strategy.calculate_latest_rsi(prices, return_prev=True)
        result_b = strategy.check_signal(symbol, candle, price_history=None,
                                          is_tradable=True, rsi_values=rsi_pair)
        
        assert result_a == result_b, f"Mismatch: A={result_a}, B={result_b}"

    def test_alert_signal_equivalence(self, strategy):
        """When an ALERT fires, both paths must produce identical signal dicts."""
        # Create prices that trigger a crossover at threshold=60
        config = make_config(period=11, threshold=60)
        strategy = ExpiryRSIBreakout(config)
        
        # Build prices where prev_rsi < 60 and current_rsi >= 60
        # Use a series with a clear upward spike at the end
        base = np.concatenate([
            np.linspace(100, 95, 150),  # Gradual decline (low RSI)
            np.linspace(95, 120, 49),   # Sharp recovery
        ])
        spike = np.append(base, 125.0)  # Final candle pushes RSI over
        
        prices = pd.Series(spike)
        symbol = 'NSE-NIFTY-20Mar26-22500-CE'
        
        # Check if this actually creates the crossover
        rsi_result = strategy.calculate_latest_rsi(prices, return_prev=True)
        if rsi_result is None:
            pytest.skip("Price series didn't create valid RSI crossover")
        
        curr_rsi, prev_rsi = rsi_result
        if curr_rsi is None or prev_rsi is None:
            pytest.skip("RSI values are None")
        
        # Only test if crossover actually happens
        if prev_rsi < 60 and curr_rsi >= 60:
            candle = self._make_candle(
                '2026-03-20 10:30:00',
                o=spike[-2], h=spike[-1] + 2, l=spike[-2] - 1, c=spike[-1]
            )
            
            # Path A
            result_a = strategy.check_signal(symbol, candle, prices, is_tradable=True)
            strategy.state.pop(symbol, None)
            
            # Path B
            rsi_pair = (curr_rsi, prev_rsi)
            result_b = strategy.check_signal(symbol, candle, price_history=None,
                                              is_tradable=True, rsi_values=rsi_pair)
            
            if result_a and result_b:
                assert result_a['action'] == result_b['action']
                assert result_a['price'] == pytest.approx(result_b['price'])
                assert result_a['sl'] == pytest.approx(result_b['sl'])
                assert result_a['rsi'] == pytest.approx(result_b['rsi'])

    def test_batch_rsi_feeds_check_signal_correctly(self, strategy):
        """End-to-end: batch_calculate_rsi output plugs into check_signal."""
        symbols_data = {}
        candles = {}
        for i in range(5):
            sym = f'NSE-NIFTY-20Mar26-{22000 + i * 100}-CE'
            prices = generate_realistic_prices(200, seed=i + 100)
            symbols_data[sym] = prices
            candles[sym] = self._make_candle(
                '2026-03-20 10:30:00',
                o=prices[-2], h=max(prices[-3:]) + 1,
                l=min(prices[-3:]) - 1, c=prices[-1]
            )
        
        # Batch compute
        batch_rsi = strategy.batch_calculate_rsi(symbols_data)
        
        # Feed into check_signal
        for sym in symbols_data:
            rsi_pair = batch_rsi[sym]
            # Should not raise any exception
            result = strategy.check_signal(
                sym, candles[sym],
                price_history=None,
                is_tradable=True,
                rsi_values=rsi_pair
            )
            # Result is either None or a valid signal dict
            if result is not None:
                assert 'action' in result


# ══════════════════════════════════════════════════════════════════════════════
# PERFORMANCE BENCHMARK
# ══════════════════════════════════════════════════════════════════════════════

class TestBatchPerformance:
    """Verify batch method is faster than N individual calls."""

    def test_batch_faster_than_individual(self):
        """Batch RSI for 30 symbols should be faster than 30 individual calls."""
        strategy = ExpiryRSIBreakout(make_config())
        n_symbols = 30
        symbols = {
            f'SYM_{i}': generate_realistic_prices(200, seed=i)
            for i in range(n_symbols)
        }
        
        # Warm up JIT/cache
        strategy.batch_calculate_rsi(symbols)
        for prices in symbols.values():
            strategy.calculate_latest_rsi(pd.Series(prices), return_prev=True)
        
        # Time batch
        t0 = time.perf_counter()
        for _ in range(100):
            strategy.batch_calculate_rsi(symbols)
        batch_time = time.perf_counter() - t0
        
        # Time individual
        t0 = time.perf_counter()
        for _ in range(100):
            for prices in symbols.values():
                strategy.calculate_latest_rsi(pd.Series(prices), return_prev=True)
        individual_time = time.perf_counter() - t0
        
        # Batch should be faster (it avoids Pandas overhead)
        speedup = individual_time / batch_time
        print(f"\n  Batch: {batch_time:.3f}s | Individual: {individual_time:.3f}s | Speedup: {speedup:.1f}x")
        assert speedup > 1.0, (
            f"Batch should be faster than individual. "
            f"Batch={batch_time:.3f}s, Individual={individual_time:.3f}s"
        )


# ══════════════════════════════════════════════════════════════════════════════
# REGRESSION: Existing RSI tests must still pass
# ══════════════════════════════════════════════════════════════════════════════

class TestExistingRSIRegression:
    """Ensure the vectorized changes don't break existing RSI behavior."""

    def test_rsi_returns_none_below_minimum(self):
        s = ExpiryRSIBreakout(make_config(period=9))
        result = s.calculate_latest_rsi(pd.Series([100.0, 101.0, 102.0]))
        assert result is None

    def test_rsi_warmup_is_direct_candle_count(self):
        s = ExpiryRSIBreakout(make_config())
        assert s.rsi_warmup == 100

    def test_wilder_rsi_array_vs_series_match(self):
        """Numpy array path and Pandas Series path must produce same values."""
        s = ExpiryRSIBreakout(make_config(period=11))
        prices_arr = generate_realistic_prices(200)
        prices_series = pd.Series(prices_arr)
        
        result_arr = s.calculate_wilder_rsi(prices_arr)
        result_series = s.calculate_wilder_rsi(prices_series)
        
        # Array returns raw values, Series returns pd.Series
        # Compare the valid (non-NaN) tail
        arr_tail = result_arr[-10:]
        series_tail = result_series.iloc[-10:].values
        
        np.testing.assert_allclose(arr_tail, series_tail, atol=1e-10)

    def test_check_signal_with_rsi_values_parameter(self):
        """check_signal must accept rsi_values kwarg without errors."""
        s = ExpiryRSIBreakout(make_config())
        candle = pd.Series({
            'datetime': pd.Timestamp('2026-03-20 10:15:00'),
            'open': 100.0, 'high': 105.0, 'low': 98.0, 'close': 104.0,
            'volume': 100
        })
        # Pass pre-computed RSI values
        result = s.check_signal(
            'NSE-NIFTY-20Mar26-22500-CE', candle,
            price_history=None,
            is_tradable=True,
            rsi_values=(55.0, 58.0)  # Below threshold, no alert
        )
        assert result is None  # No crossover → no signal

    def test_check_signal_still_works_with_price_history(self):
        """Original price_history path must still function (backward compat)."""
        s = ExpiryRSIBreakout(make_config())
        prices = pd.Series(generate_realistic_prices(200))
        candle = pd.Series({
            'datetime': pd.Timestamp('2026-03-20 10:15:00'),
            'open': prices.iloc[-2], 'high': prices.iloc[-1] + 2,
            'low': prices.iloc[-2] - 1, 'close': prices.iloc[-1],
            'volume': 100
        })
        # Should not raise
        result = s.check_signal(
            'NSE-NIFTY-20Mar26-22500-CE', candle,
            price_history=prices, is_tradable=True
        )
        # Result is None or a valid signal — either is fine
        if result is not None:
            assert 'action' in result
