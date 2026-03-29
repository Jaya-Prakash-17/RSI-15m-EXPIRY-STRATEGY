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
    pattern = os.path.join(reports_dir, 'backtest_*_summary.json')
    files = sorted(glob.glob(pattern))
    results = []
    for f in files:
        try:
            with open(f) as fp:
                data = json.load(fp)
            year = extract_year(data)
            s = data.get('summary', {})
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
                'lots': data.get('config', {}).get('strategy', {}).get('lots_per_trade', '?'),
                'exit_target': data.get('config', {}).get('strategy', {}).get('single_lot_exit_target', '?'),
            })
        except Exception as e:
            print(f"Error loading {f}: {e}")
    return results


def print_table(results):
    if not results:
        print("No summary files found.")
        return

    header = f"{'Year':<6} {'Trades':<8} {'Win%':<7} {'PF':<6} {'Max DD%':<10} {'Net P&L':<12} {'Sharpe':<8} {'Verdict'}"
    print("\n" + "=" * 80)
    print(" OUT-OF-SAMPLE VALIDATION TABLE")
    print("=" * 80)
    print(header)
    print("-" * 80)

    all_pass = True
    for r in sorted(results, key=lambda x: x['year']):
        pf = r['profit_factor']
        dd = r['max_drawdown_pct']
        wr = r['win_rate']

        # GO/NO-GO criteria
        pf_ok = pf >= 1.1
        dd_ok = dd > -35.0
        wr_ok = 25 <= wr <= 55  # Relaxed range for different market regimes

        verdict = "PASS" if (pf_ok and dd_ok) else "FAIL"
        if not (pf_ok and dd_ok):
            all_pass = False

        flags = []
        if not pf_ok:
            flags.append(f"PF={pf:.2f}<1.1")
        if not dd_ok:
            flags.append(f"DD={dd:.1f}%")
        if not wr_ok:
            flags.append(f"WR={wr:.1f}%")

        flag_str = " | ".join(flags) if flags else ""
        print(
            f"{r['year']:<6} {r['trades']:<8} {wr:<7.1f} {pf:<6.2f} "
            f"{dd:<10.1f} Rs.{r['net_pnl']:<10,.0f} {r['sharpe']:<8.2f} "
            f"{verdict} {flag_str}"
        )

    print("=" * 80)
    print(f"\nGO/NO-GO CRITERIA:")
    print(f"  Profit Factor >= 1.1 | Max Drawdown > -35%")
    print(
        f"\nFINAL VERDICT: {'ALL YEARS PASS - ready for live consideration' if all_pass else 'STRATEGY FAILS OUT-OF-SAMPLE - do not deploy live'}"
    )
    print()


if __name__ == '__main__':
    reports_dir = sys.argv[1] if len(sys.argv) > 1 else 'reports'
    results = load_summaries(reports_dir)
    print_table(results)
