import json
import pandas as pd
import numpy as np
from scipy import stats
import os
import glob
from dateutil.relativedelta import relativedelta
from datetime import datetime

# Load the trades dataframe from a summary json file
def load_trades(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if 'trades' not in data:
        return pd.DataFrame()
    df = pd.DataFrame(data['trades'])
    if not df.empty:
        df['entry_time'] = pd.to_datetime(df['entry_time'])
    return df

def generate_rolling_windows(start_date, end_date, window_months=3, step_months=1):
    windows = []
    current_start = start_date
    while True:
        current_end = current_start + relativedelta(months=window_months) - relativedelta(days=1)
        if current_end > end_date:
            break
        windows.append((current_start, current_end))
        current_start += relativedelta(months=step_months)
    return windows

def calculate_max_drawdown(pnl_series):
    if len(pnl_series) == 0:
        return 0
    cumulative = np.cumsum(pnl_series)
    peak = np.maximum.accumulate(cumulative)
    drawdown = peak - cumulative
    max_dd = np.max(drawdown)
    return max_dd

def calculate_sharpe(pnl_series):
    if len(pnl_series) == 0 or np.std(pnl_series) == 0:
        return 0
    # Annualized sharpe roughly
    return (np.mean(pnl_series) / np.std(pnl_series)) * np.sqrt(252)

def calculate_metrics(df):
    if df.empty:
        return {'pnl': 0, 'win_rate': 0, 'trades': 0}
    pnl = df['pnl_net'].sum() if 'pnl_net' in df.columns else df['pnl'].sum()
    win_rate = (df['pnl_net' if 'pnl_net' in df.columns else 'pnl'] > 0).mean() * 100
    return {'pnl': pnl, 'win_rate': win_rate, 'trades': len(df)}

def main():
    print("--- Phase 2: SL Optimization & Hypothesis Testing ---")

    # We find the two summary JSONs in the reports folder
    # Assuming the older one is Safe SL (from user's previous run)
    # And the newer one is Normal SL (running currently)
    # Actually, we can just use the Safe SL dataset for ANOVA right now

    reports = sorted(glob.glob('reports/*_summary.json'))
    if len(reports) < 2:
        print("Need at least 2 reports (Safe SL and Normal SL) to run comparison.")
        return

    # Assuming older is Safe SL, newer is Normal SL
    safe_sl_file = reports[-2]
    normal_sl_file = reports[-1]

    print(f"Safe SL Report: {os.path.basename(safe_sl_file)}")
    print(f"Normal SL Report: {os.path.basename(normal_sl_file)}")

    df_safe = load_trades(safe_sl_file)
    df_normal = load_trades(normal_sl_file)
    print(f"Loaded {len(df_safe)} trades from Safe SL dataset.")
    print(f"Loaded {len(df_normal)} trades from Normal SL dataset.")

    # Generate 30+ random rolling windows
    start_date = datetime(2020, 1, 1)
    end_date = datetime(2025, 12, 31)

    all_windows = generate_rolling_windows(start_date, end_date, window_months=3, step_months=1)
    np.random.seed(42)
    sample_indices = np.random.choice(len(all_windows), size=30, replace=False)
    sampled_windows = [all_windows[i] for i in sample_indices]

    print(f"Extracted {len(sampled_windows)} rolling 3-month windows for analysis.")

    safe_returns = []
    normal_returns = []

    safe_win_rates = []
    normal_win_rates = []

    safe_max_dds = []
    normal_max_dds = []

    safe_sharpes = []
    normal_sharpes = []

    for w_start, w_end in sampled_windows:
        mask_safe = (df_safe['entry_time'] >= w_start) & (df_safe['entry_time'] <= w_end)
        w_df_safe = df_safe[mask_safe]

        if not w_df_safe.empty:
            pnl_series_safe = w_df_safe['pnl_net'].values
            safe_returns.append(np.sum(pnl_series_safe))
            safe_win_rates.append((pnl_series_safe > 0).mean() * 100)
            safe_max_dds.append(calculate_max_drawdown(pnl_series_safe))
            safe_sharpes.append(calculate_sharpe(pnl_series_safe))
        else:
            safe_returns.append(0)
            safe_win_rates.append(0)
            safe_max_dds.append(0)
            safe_sharpes.append(0)

        mask_normal = (df_normal['entry_time'] >= w_start) & (df_normal['entry_time'] <= w_end)
        w_df_normal = df_normal[mask_normal]

        if not w_df_normal.empty:
            pnl_series_normal = w_df_normal['pnl_net'].values
            normal_returns.append(np.sum(pnl_series_normal))
            normal_win_rates.append((pnl_series_normal > 0).mean() * 100)
            normal_max_dds.append(calculate_max_drawdown(pnl_series_normal))
            normal_sharpes.append(calculate_sharpe(pnl_series_normal))
        else:
            normal_returns.append(0)
            normal_win_rates.append(0)
            normal_max_dds.append(0)
            normal_sharpes.append(0)

    safe_returns = np.array(safe_returns)
    normal_returns = np.array(normal_returns)
    safe_win_rates = np.array(safe_win_rates)
    normal_win_rates = np.array(normal_win_rates)
    safe_max_dds = np.array(safe_max_dds)
    normal_max_dds = np.array(normal_max_dds)
    safe_sharpes = np.array(safe_sharpes)
    normal_sharpes = np.array(normal_sharpes)

    print("\n--- Phase 2: Hypothesis Testing Results ---")
    print(f"Safe SL Mean 3-Month PnL: {safe_returns.mean():.2f} ± {safe_returns.std() / np.sqrt(30) * 1.96:.2f}")
    print(f"Normal SL Mean 3-Month PnL: {normal_returns.mean():.2f} ± {normal_returns.std() / np.sqrt(30) * 1.96:.2f}")

    print(f"Safe SL Mean Win Rate: {safe_win_rates.mean():.2f}%")
    print(f"Normal SL Mean Win Rate: {normal_win_rates.mean():.2f}%")

    print(f"Safe SL Mean Max Drawdown: {safe_max_dds.mean():.2f}")
    print(f"Normal SL Mean Max Drawdown: {normal_max_dds.mean():.2f}")

    print(f"Safe SL Mean Sharpe Ratio: {safe_sharpes.mean():.2f}")
    print(f"Normal SL Mean Sharpe Ratio: {normal_sharpes.mean():.2f}")

    # Welch's T-Test
    t_stat, p_val_t = stats.ttest_ind(safe_returns, normal_returns, equal_var=False)
    print(f"\nWelch's T-Test p-value: {p_val_t:.4e}")

    # Mann-Whitney U Test
    u_stat, p_val_u = stats.mannwhitneyu(safe_returns, normal_returns, alternative='two-sided')
    print(f"Mann-Whitney U Test p-value: {p_val_u:.4e}")

    if p_val_t < 0.05:
        print("Conclusion: Reject Null Hypothesis. There is a statistically significant difference.")
    else:
        print("Conclusion: Fail to Reject Null Hypothesis. The difference is NOT statistically significant.")


    # Phase 3: Cross-Index Comparative Analysis
    print("\n--- Phase 3: Cross-Index Comparative Analysis (ANOVA) ---")

    index_returns = {'NIFTY': [], 'BANKNIFTY': [], 'SENSEX': []}

    for w_start, w_end in sampled_windows:
        mask = (df_safe['entry_time'] >= w_start) & (df_safe['entry_time'] <= w_end)
        w_df = df_safe[mask]

        for idx in index_returns.keys():
            idx_df = w_df[w_df['underlying'] == idx]
            pnl = idx_df['pnl_net'].sum() if not idx_df.empty else 0
            index_returns[idx].append(pnl)

    # ANOVA Test
    f_stat, p_val = stats.f_oneway(index_returns['NIFTY'], index_returns['BANKNIFTY'], index_returns['SENSEX'])
    print(f"ANOVA F-Statistic: {f_stat:.4f}")
    print(f"ANOVA p-value: {p_val:.4e}")

    if p_val < 0.05:
        print("Conclusion: Reject Null Hypothesis. There is a statistically significant difference in profitability across indices.")
    else:
        print("Conclusion: Fail to Reject Null Hypothesis. Differences across indices are not statistically significant.")

    print("\nPairwise T-Tests:")
    t_n_b, p_n_b = stats.ttest_ind(index_returns['NIFTY'], index_returns['BANKNIFTY'], equal_var=False)
    print(f"NIFTY vs BANKNIFTY: p-value = {p_n_b:.4e}")

    t_n_s, p_n_s = stats.ttest_ind(index_returns['NIFTY'], index_returns['SENSEX'], equal_var=False)
    print(f"NIFTY vs SENSEX: p-value = {p_n_s:.4e}")

    t_b_s, p_b_s = stats.ttest_ind(index_returns['BANKNIFTY'], index_returns['SENSEX'], equal_var=False)
    print(f"BANKNIFTY vs SENSEX: p-value = {p_b_s:.4e}")

    # Mean Expectancy per chunk
    print("\nMean 3-Month Expectancy (INR):")
    print(f"NIFTY:     {np.mean(index_returns['NIFTY']):.2f} ± {np.std(index_returns['NIFTY']) / np.sqrt(30) * 1.96:.2f}")
    print(f"BANKNIFTY: {np.mean(index_returns['BANKNIFTY']):.2f} ± {np.std(index_returns['BANKNIFTY']) / np.sqrt(30) * 1.96:.2f}")
    print(f"SENSEX:    {np.mean(index_returns['SENSEX']):.2f} ± {np.std(index_returns['SENSEX']) / np.sqrt(30) * 1.96:.2f}")

if __name__ == '__main__':
    main()
