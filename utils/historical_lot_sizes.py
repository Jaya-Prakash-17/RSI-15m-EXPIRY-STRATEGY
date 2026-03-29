"""
Historical Option Lot Size Repository
Tracks SEBI/NSE lot size revisions for NIFTY, BANKNIFTY, and SENSEX.

Sources:
- NSE Circular: nseindia.com/regulations/circulars
- SEBI Circular: SEBI/HO/MRD/DNPMP/CIR/P/2024/xxx (Nov 2024 reform)
- BSE Circular: Nov 2024 reform
"""
from datetime import date, datetime
import logging

# Last verified against exchange circulars: 2024-12-31
LAST_VERIFIED = "2024-12-31"

LOT_SIZE_HISTORY = {
    'NIFTY': [
        (date(2020, 1, 1), 75),
        (date(2025, 9, 1), 65)
    ],
    'BANKNIFTY': [
        (date(2020, 1, 1), 25),
        (date(2024, 11, 20), 35),
        (date(2025, 9, 1), 30)
    ],
    'SENSEX': [
        (date(2023, 5, 1), 10),
        (date(2024, 11, 20), 20)
    ]
}

def get_historical_lot_size(underlying: str, reference_date) -> int:
    """Find the applicable lot size for the given date."""
    if isinstance(reference_date, datetime):
        reference_date = reference_date.date()
    
    # Boundary check for SENSEX
    if underlying == 'SENSEX' and reference_date < date(2023, 5, 1):
        raise ValueError("SENSEX options did not exist before 2023-05-01.")
    
    if underlying not in LOT_SIZE_HISTORY:
        logging.warning(f"Unknown underlying: {underlying}. No lot size history found.")
        return 0
    
    history = LOT_SIZE_HISTORY[underlying]
    
    # Scan history (sorted chronologically)
    applicable_size = 0
    for start_date, lot_size in history:
        if reference_date >= start_date:
            applicable_size = lot_size
        else:
            break
            
    return applicable_size

def run_startup_assertions():
    """Verify key boundary dates on startup."""
    assert get_historical_lot_size('NIFTY', date(2024, 11, 19)) == 75
    assert get_historical_lot_size('NIFTY', date(2025, 9, 1)) == 65
    assert get_historical_lot_size('BANKNIFTY', date(2024, 11, 19)) == 25
    assert get_historical_lot_size('BANKNIFTY', date(2024, 11, 20)) == 35
    assert get_historical_lot_size('BANKNIFTY', date(2025, 9, 1)) == 30
    print("✅ Historical lot size assertions passed.")

def _run_self_test():
    """Run comprehensive self-test."""
    print("Running historical lot size self-test...")
    test_cases = [
        ('NIFTY', date(2020, 3, 15), 75),
        ('NIFTY', date(2024, 11, 19), 75),
        ('NIFTY', date(2025, 9, 1), 65),
        ('NIFTY', date(2026, 3, 1), 65),
        ('BANKNIFTY', date(2024, 11, 19), 25),
        ('BANKNIFTY', date(2024, 11, 20), 35),
        ('BANKNIFTY', date(2025, 9, 1), 30),
        ('SENSEX', date(2023, 5, 1), 10),
        ('SENSEX', date(2024, 11, 20), 20)
    ]
    
    for underlying, ref_date, expected in test_cases:
        actual = get_historical_lot_size(underlying, ref_date)
        assert actual == expected, f"FAILED: {underlying} on {ref_date} expected {expected}, got {actual}"
    
    # Error case
    try:
        get_historical_lot_size('SENSEX', date(2022, 1, 1))
        assert False, "FAILED: SENSEX pre-launch should have raised ValueError"
    except ValueError:
        pass
        
    print("✅ All historical lot size self-test cases passed.")

if __name__ == '__main__':
    _run_self_test()
