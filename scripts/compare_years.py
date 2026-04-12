#!/usr/bin/env python3
"""
scripts/compare_years.py
Usage: python scripts/compare_years.py reports/
Reads all backtest_*_summary.json files and compares metrics by year.
"""
import json
import os
import sys
import glob


def extract_year(summary):
    """Extract the backtest year from the config in the summary."""
    try:
        start = summary['config']['backtest']['start_date']
        return start[:4]
    except (KeyError, TypeError):
        return 'unknown'


def load_summaries(reports_dir):
    # Pattern updated to catch the strategy-named summary files
    pattern = os.path.join(reports_dir, '*_summary.json')
    files = sorted(glob.glob(pattern))
    print(f"Found {len(files)} summary files in {reports_dir}")
    results = []
    for f in files:
        try:
            with open(f) as fp:
                data = json.load(fp)

            # Smart year extraction: internal config OR filename segment
            year = extract_year(data)
            if year == 'unknown':
                # Try to find a 4-digit year in the filename (e.g., ..._2023-2023_...)
                import re
                match = re.search(r'(\d{4})-\1', os.path.basename(f))
                if match:
                    year = match.group(1)
                else:
                    # Fallback to any 4-digit number
                    match = re.search(r'_(\d{4})_', os.path.basename(f))
                    if match:
                        year = match.group(1)

            s = data.get('summary', {})
            # Handle potential index list in config
            indices_cfg = data.get('config', {}).get('indices', {})
            index_list = list(indices_cfg.keys()) if isinstance(indices_cfg, dict) else [str(indices_cfg)]

            results.append({
                'year': year,
                'file': os.path.basename(f),
                'trades': s.get('total_trades', 0),
                'win_rate': s.get('win_rate', 0),
                'profit_factor': s.get('profit_factor', 0),
                'max_drawdown': s.get('max_drawdown', 0),
                'max_drawdown_pct': s.get('max_drawdown_pct', 0),
                'net_pnl': s.get('total_pnl', 0),
                'sharpe': s.get('sharpe_ratio', 0),
                'indices': ", ".join(index_list),
                'lots': data.get('config', {}).get('strategy', {}).get('lots_per_trade', '?'),
                'exit_target': data.get('config', {}).get('strategy', {}).get('single_lot_exit_target', '?'),
                'rsi_period': data.get('config', {}).get('strategy', {}).get('rsi', {}).get('period', '?'),
            })
        except Exception as e:
            print(f"Error loading {f}: {e}")
    print(f"Successfully loaded metrics for {len(results)} years.")
    return results


def print_table(results):
    if not results:
        print("No summary files found.")
        return

    header = f"{'Yr':<4} {'P':<2} {'Trd':<4} {'Win%':<5} {'PF':<5} {'DD%':<6} {'PnL':<10} {'Shp':<5} {'Verdict'}"
    print("\n" + "=" * 80)
    print(" OUT-OF-SAMPLE VALIDATION TABLE")
    print("=" * 80)

    # Check config of the first result to contextualize WR expectations
    exit_target = results[0]['exit_target'] if results else '?'
    print(f" CONFIG: single_lot_exit_target = {exit_target}")
    print("-" * 80)
    print(header)
    print("-" * 80)

    # WR thresholds: T2 exit → typical 45-55%; T3 exit → typical 45-65%; >70% = bias flag
    all_pass = True
    for r in sorted(results, key=lambda x: x['year']):
        pf = r['profit_factor']
        dd = r['max_drawdown_pct']
        wr = r['win_rate']

        pf_ok = pf >= 1.1
        dd_ok = dd > -35.0
        wr_ok = 25 <= wr <= 70

        verdict = "PASS" if (pf_ok and dd_ok and wr_ok) else "FAIL"
        if not (pf_ok and dd_ok and wr_ok):
            all_pass = False

        print(
            f"{r['year']:<4} {r['rsi_period']:<2} {r['trades']:<4} {wr:<5.1f} {pf:<5.2f} "
            f"{dd:<6.1f} {r['net_pnl']:<10,.0f} {r['sharpe']:<5.2f} "
            f"{verdict}"
        )

    print("=" * 80)
    print(f"GO/NO-GO CRITERIA (ALL must pass):")
    print(f"  Profit Factor >= 1.1")
    print(f"  Max Drawdown > -35%")
    print(f"  Win Rate 25%-70% (T2 exit: expect 45-55%; T3 exit: expect 45-65%)")

    # V16-P-02: Year-over-year consistency checks
    pnls = {r['year']: r['net_pnl'] for r in results if r['year'] != 'unknown'}
    total_pnl = sum(pnls.values()) if pnls else 0

    if len(pnls) >= 2 and total_pnl != 0:
        import numpy as np
        pnl_values = list(pnls.values())
        cv = np.std(pnl_values) / abs(np.mean(pnl_values)) if np.mean(pnl_values) != 0 else 0
        print(f"\n  YoY Consistency:")
        print(f"    PnL Coefficient of Variation: {cv:.2f}")
        if cv > 1.5:
            print(f"    [!] HIGH VARIANCE: strategy performance is regime-dependent")

        for yr, pnl in pnls.items():
            share = abs(pnl) / abs(total_pnl) * 100 if total_pnl != 0 else 0
            if share > 40:
                print(f"    [!] CONCENTRATION: {yr} accounts for {share:.1f}% of total PnL (limit: 40%)")

        crash_years_pnl = sum(pnls.get(y, 0) for y in ['2020', '2021'])
        if total_pnl > 0 and crash_years_pnl / total_pnl > 0.5:
            print(f"    [!] REGIME BIAS: 2020+2021 = {crash_years_pnl/total_pnl*100:.1f}% of total PnL (crash-bounce regime)")

    print(
        f"\nFINAL VERDICT: {'ALL YEARS PASS - ready for live consideration' if all_pass else 'STRATEGY FAILS OUT-OF-SAMPLE - do not deploy live'}"
    )
    print()


if __name__ == '__main__':
    reports_dir = sys.argv[1] if len(sys.argv) > 1 else 'reports'
    results = load_summaries(reports_dir)
    print_table(results)
