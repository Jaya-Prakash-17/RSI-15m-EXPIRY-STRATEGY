
import yaml
import json
import os
import subprocess
import pandas as pd
from datetime import datetime
import itertools
import shutil

CONFIG_PATH = 'config.yaml'
BACKUP_PATH = 'config.yaml.bak'
RESULTS_DIR = 'reports/oos_optimization'
SUMMARY_DIR = 'reports'

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)

def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

def run_backtest(start='2020-01-01', end='2025-12-31'):
    print(f"Running backtest from {start} to {end}...")
    cmd = [
        "python", "run_backtest.py"
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"Error running backtest: Return code {result.returncode}")
        return None

    files = [f for f in os.listdir(SUMMARY_DIR) if f.endswith('_summary.json')]
    if not files:
        print("No summary JSON files found in reports/")
        return None

    latest_file = max([os.path.join(SUMMARY_DIR, f) for f in files], key=os.path.getmtime)
    print(f"Latest summary file found: {latest_file}")
    with open(latest_file, 'r') as f:
        return json.load(f)

def run_optimization():
    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)

    shutil.copy(CONFIG_PATH, BACKUP_PATH)

    results = []
    run_list = [(11, 2), (14, 3)]

    try:
        for i, values in enumerate(run_list):
            params = {'rsi_period': values[0], 'exit_target': values[1]}
            print(f"\n[Run {i+1}/{len(run_list)}] Testing Params: {params}")

            config = load_config()
            config['backtest']['start_date'] = '2020-01-01'
            config['backtest']['end_date'] = '2025-12-31'
            config['strategy']['rsi']['period'] = params['rsi_period']
            config['strategy']['rsi']['threshold'] = 60
            config['strategy']['single_lot_exit_target'] = params['exit_target']
            config['strategy']['safe_sl_max_loss'] = 6000
            config['strategy']['signal_window_end'] = '13:45'
            config['strategy']['signal_window_start'] = '10:00'

            save_config(config)

            summary = run_backtest()
            if summary:
                s = summary.get('summary', {})
                res = {
                    **params,
                    'total_pnl': s.get('total_pnl', 0),
                    'win_rate': s.get('win_rate', 0),
                    'max_drawdown': s.get('max_drawdown', 0),
                    'total_trades': s.get('total_trades', 0),
                    'profit_factor': s.get('profit_factor', 0),
                    'expectancy': s.get('expectancy', 0)
                }
                results.append(res)
                print(f"Result: PNL: {res['total_pnl']:.0f}, WR: {res['win_rate']:.1f}%, DD: {res['max_drawdown']:.0f}")

            df = pd.DataFrame(results)
            df.to_csv(os.path.join(RESULTS_DIR, 'oos_results_rolling.csv'), index=False)

    finally:
        shutil.copy(BACKUP_PATH, CONFIG_PATH)
        os.remove(BACKUP_PATH)

    df = pd.DataFrame(results)
    df = df.sort_values(by='total_pnl', ascending=False)
    df.to_csv(os.path.join(RESULTS_DIR, 'oos_results_final.csv'), index=False)

    print("\nOPTIMIZATION COMPLETE")
    print(df.to_string(index=False))

if __name__ == "__main__":
    run_optimization()
