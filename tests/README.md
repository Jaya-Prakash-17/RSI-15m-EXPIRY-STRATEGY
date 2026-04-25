# Test Suite & Safety Verifications

This directory contains scripts for validating the trading system's logic, safety features, and multi-index robustness.

## Verification Scripts

| Script | Purpose |
|---|---|
| `verify_safety.py` | Audits historical trades for SL compliance and risk breaches. |
| `verify_multi_index.py` | Validates performance attribution across different indices (NIFTY, BANKNIFTY, SENSEX). |
| `verify_resilience.py` | Tests the system against edge cases like missing data or connectivity issues. |

## Running Tests

```bash
python tests/verify_safety.py
python tests/verify_multi_index.py
```

It is recommended to run these scripts after any major change to the `intraday_engine.py` or `expiry_rsi_breakout.py`.
