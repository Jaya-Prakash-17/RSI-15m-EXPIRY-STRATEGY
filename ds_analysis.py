import json
import pandas as pd
import numpy as np

import glob
import os

filepaths = glob.glob('reports/*_summary.json')
all_trades = []
for filepath in filepaths:
    with open(filepath, 'r') as f:
        data = json.load(f)
        all_trades.extend(data['trades'])

df = pd.DataFrame(all_trades)
df['entry_time'] = pd.to_datetime(df['entry_time'])
df['year'] = df['entry_time'].dt.year
df['month'] = df['entry_time'].dt.month

print("="*60)
print(f"Data Scientist Report: Statistical Validation 2020-2025")
print("="*60)
print(f"Total Trades: {len(df)}")
print(f"Total Net PnL: Rs. {df['pnl_net'].sum():,.2f}")
print(f"Win Rate: {len(df[df['pnl_net'] > 0]) / len(df) * 100:.2f}%")

print("\n--- 1. YEARLY REGIME ANALYSIS ---")
yearly = df.groupby('year').agg(
    trades=('pnl_net', 'count'),
    net_pnl=('pnl_net', 'sum'),
    win_rate=('pnl_net', lambda x: (x > 0).mean() * 100),
    avg_win=('pnl_net', lambda x: x[x>0].mean() if len(x[x>0]) else 0),
    avg_loss=('pnl_net', lambda x: x[x<0].mean() if len(x[x<0]) else 0),
    max_dd=('pnl_net', lambda x: x.min())
).round(2)

yearly['profit_factor'] = abs(yearly['avg_win'] * yearly['win_rate'] / (yearly['avg_loss'] * (100 - yearly['win_rate'])))
print(yearly.to_string())

print("\n--- 2. PROFITABILITY BY UNDERLYING ---")
underlying = df.groupby('underlying').agg(
    trades=('pnl_net', 'count'),
    net_pnl=('pnl_net', 'sum'),
    win_rate=('pnl_net', lambda x: (x > 0).mean() * 100),
    profit_factor=('pnl_net', lambda x: abs(x[x>0].sum() / x[x<0].sum()) if x[x<0].sum() != 0 else np.inf)
).round(2)
print(underlying.to_string())

print("\n--- 3. WIN STREAKS AND DRAWDOWN DYNAMICS ---")
df['is_win'] = df['pnl_net'] > 0
# Calculate streaks
streaks = df['is_win'].groupby((df['is_win'] != df['is_win'].shift()).cumsum()).count()
win_streaks = streaks[df['is_win'].groupby((df['is_win'] != df['is_win'].shift()).cumsum()).first() == True]
loss_streaks = streaks[df['is_win'].groupby((df['is_win'] != df['is_win'].shift()).cumsum()).first() == False]

print(f"Max Win Streak: {win_streaks.max() if not win_streaks.empty else 0}")
print(f"Max Losing Streak: {loss_streaks.max() if not loss_streaks.empty else 0}")
print(f"Average Win Streak Length: {win_streaks.mean():.1f}")
print(f"Average Losing Streak Length: {loss_streaks.mean():.1f}")

df['cumulative_pnl'] = df['pnl_net'].cumsum()
df['running_max'] = df['cumulative_pnl'].cummax()
df['drawdown'] = df['cumulative_pnl'] - df['running_max']
max_dd = df['drawdown'].min()
print(f"Max Absolute Drawdown: Rs. {max_dd:,.2f}")

print("\n--- 4. HOLDING PERIOD INSIGHTS ---")
df['duration_cat'] = pd.cut(df['duration'], bins=[0, 15, 30, 60, 120, 240, 500], labels=['0-15m', '15-30m', '30-60m', '1-2h', '2-4h', '4h+'])
holding = df.groupby('duration_cat').agg(
    trades=('pnl_net', 'count'),
    win_rate=('pnl_net', lambda x: (x > 0).mean() * 100),
    net_pnl=('pnl_net', 'sum')
).round(2)
print(holding.to_string())

print("\n--- 5. EXIT REASON DISTRIBUTION ---")
reason = df.groupby('reason').agg(
    count=('pnl_net', 'count'),
    avg_pnl=('pnl_net', 'mean'),
    total_pnl=('pnl_net', 'sum')
).round(2)
print(reason.to_string())
