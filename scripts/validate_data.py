# scripts/validate_data.py
import sys, os, yaml, pandas as pd
from datetime import datetime, timedelta
sys.path.append(os.getcwd())
from data.data_manager import DataManager

def validate():
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
    dm = DataManager(config)
    start = pd.to_datetime(config['backtest']['start_date'])
    end = pd.to_datetime(config['backtest']['end_date'])
    
    indices = list(config['indices'].keys())
    print(f"\nAUDITING DATA INTEGRITY: {start.date()} to {end.date()}")
    print("="*60)
    
    all_clear = True
    for idx in indices:
        print(f"Checking {idx}...")
        filepath = os.path.join(dm.base_path, "spot", f"{idx}_15m.csv")
        if not os.path.exists(filepath):
            print(f"  [X] NO FILE FOUND for {idx}")
            all_clear = False
            continue
            
        df = pd.read_csv(filepath)
        if df.empty:
            print(f"  [X] FILE IS EMPTY for {idx}")
            all_clear = False
            continue
            
        df['datetime'] = pd.to_datetime(df['datetime'])
        gaps = dm._check_for_gaps(df, start, end, idx)
        if gaps:
            print(f"  [X] {len(gaps)} GAPS FOUND:")
            for gs, ge in gaps:
                print(f"      - {gs.date()} to {ge.date()}")
            all_clear = False
        else:
            print(f"  [OK] Data is complete.")
            
    if all_clear:
        print("\nSUCCESS: All spot data is complete and verified for backtesting.")
    else:
        print("\nFAILURE: Missing data detected. Run backtest again to trigger repair.")

if __name__ == "__main__":
    validate()
