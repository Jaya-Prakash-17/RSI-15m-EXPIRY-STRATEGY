import yaml
import pandas as pd
import logging
import sys
import copy
import multiprocessing as mp
from data.data_manager import DataManager
from backtest.intraday_engine import IntradayEngine
from reporting.performance import PerformanceReporter

def run_backtest_instance(params):
    period, threshold, target_idx, config_base = params

    config = copy.deepcopy(config_base)
    config['strategy']['rsi']['period'] = period
    config['strategy']['rsi']['threshold'] = threshold
    config['strategy']['single_lot_exit_target'] = target_idx

    # Run for 2024 as representative sample for optimization
    start_date = pd.to_datetime('2024-01-01')
    end_date = pd.to_datetime('2025-01-01')

    dm = DataManager(config)
    engine = IntradayEngine(dm, config)
    trades_df = engine.run(start_date, end_date)

    if trades_df.empty:
        return {
            'period': period, 'threshold': threshold, 'target': target_idx,
            'pnl': 0, 'drawdown': 0, 'win_rate': 0, 'trades': 0
        }

    # Calculate metrics
    net_pnl = trades_df['pnl'].sum()

    # Simple drawdown (on trade cumulative pnl)
    cum_pnl = trades_df['pnl'].cumsum()
    running_max = cum_pnl.cummax()
    drawdown = (running_max - cum_pnl).max()

    wins = (trades_df['pnl'] > 0).sum()
    win_rate = wins / len(trades_df)

    return {
        'period': period,
        'threshold': threshold,
        'target': target_idx,
        'pnl': net_pnl,
        'drawdown': drawdown,
        'win_rate': win_rate,
        'trades': len(trades_df)
    }

def main():
    # Setup minimal logging to avoid flooding
    logging.getLogger("BacktestEngine").setLevel(logging.WARNING)
    logging.getLogger("DataManager").setLevel(logging.WARNING)

    with open("config.yaml", "r") as f:
        config_base = yaml.safe_load(f)

    periods = [9, 11, 14]
    thresholds = [55, 60, 65]
    targets = [1, 2, 3] # TP1, TP2, TP3

    tasks = []
    for p in periods:
        for t in thresholds:
            for tgt in targets:
                tasks.append((p, t, tgt, config_base))

    print(f"Starting Grid Search with {len(tasks)} combinations...")

    with mp.Pool(processes=mp.cpu_count()) as pool:
        results = pool.map(run_backtest_instance, tasks)

    res_df = pd.DataFrame(results)
    res_df = res_df.sort_values('pnl', ascending=False)

    print("\n" + "="*80)
    print("BACKTEST OPTIMIZATION RESULTS (2023-2024)")
    print("="*80)
    print(res_df.to_string(index=False))

    best = res_df.iloc[0]
    print("\n" + "="*80)
    print(f"SUGGESTED OPTIMAL PARAMETERS:")
    print(f"RSI Period:    {best['period']}")
    print(f"RSI Threshold: {best['threshold']}")
    print(f"TP Target:     TP{int(best['target'])}")
    print(f"Expected PnL (2-yr): Rs.{best['pnl']:.2f}")
    print(f"Max DD (2-yr):       Rs.{best['drawdown']:.2f}")
    print("="*80)

if __name__ == "__main__":
    main()
