# Tests

Automated tests for validating strategy logic and infrastructure.

| File | Purpose |
|---|---|
| `test_integration.py` | **Full Flow Test.** End-to-end simulation of a trading day. Checks symbol resolution, signal generation, and order management. |
| `test_business_logic.py` | **Strategy Unit Tests.** Validates RSI calculations, green candle logic, and target/SL math. |
| `verify_fixes.py` | **Regression Tests.** Specifically covers past high-impact bugs (e.g. SENSEX mapping, config validation fixes). |

## Running Tests

```bash
# Recommended: Run with pytest
pytest tests/

# Individual test
python tests/test_integration.py
```
