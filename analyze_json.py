import json
import pandas as pd

def analyze():
    with open('reports/RSI-15m_2020-2025_P11_TH60_SINGLE_T3_200k_20260426_0156_summary.json', 'r') as f:
        data = json.load(f)

    trades = data.get('trades', [])
    print(f"Total trades: {len(trades)}")

    # 1. Trades per year and index
    df = pd.DataFrame(trades)
    df['year'] = pd.to_datetime(df['entry_time']).dt.year
    df['date'] = pd.to_datetime(df['entry_time']).dt.date

    trades_per_year = df.groupby('year').size()
    print("\nTrades per year:")
    print(trades_per_year)

    trades_per_index = df.groupby('underlying').size()
    print("\nTrades per index:")
    print(trades_per_index)

    unique_days = df['date'].nunique()
    print(f"\nUnique trading days: {unique_days}")
    print(f"Average trades per trading day: {len(trades)/unique_days:.2f}")

    # 2. Performance by Index
    print("\nPerformance by Index (Net PnL):")
    perf = df.groupby('underlying')['pnl_net'].sum()
    print(perf)

    win_rate = df.groupby('underlying').apply(lambda x: (x['pnl_net'] > 0).mean() * 100)
    print("\nWin Rate by Index (%):")
    print(win_rate)

if __name__ == '__main__':
    analyze()
