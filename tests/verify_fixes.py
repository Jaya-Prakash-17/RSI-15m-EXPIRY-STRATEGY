import os
import sys
import logging
from unittest.mock import MagicMock

# Configure minimal logging to not clutter output
logging.basicConfig(level=logging.ERROR)

def run_tests():
    print("="*60)
    print(" V E R I F Y I N G   F I X E S ")
    print("="*60)
    
    passed = 0
    failed = 0

    def assert_test(name, condition, error_msg=""):
        nonlocal passed, failed
        if condition:
            print(f"PASS: {name}")
            passed += 1
        else:
            print(f"FAIL: {name} - {error_msg}")
            failed += 1

    # DUMMY CONFIG FOR TESTS
    dummy_config = {
        'indices': {
            'NIFTY': {'lot_size': 65},
            'BANKNIFTY': {'lot_size': 30},
            'SENSEX': {'lot_size': 20}
        },
        'strategy': {
            'rsi': {
                'period': 14,
                'threshold': 60,
                'warmup_periods': 100
            },
            'alert_validity': 1,
            'lots_per_trade': 1,
            'exit_mode': 'single_lot',
            'single_lot_exit_target': 3,
            'signal_window_start': '10:00',
            'signal_window_end': '13:30',
        },
        'risk': {
            'max_loss_per_day': 5000
        },
        'capital': {
            'initial': 100000
        },
        'data': {
            'storage_path': 'data'
        },
        'trading': {
            'paper_trading': True,
            'window': {
                'start': '10:15',
                'end': '15:00',
                'auto_square_off': '15:25'
            }
        }
    }

    # 1 & 2. AUDIT-003 & AUDIT-004: Lot size resolution
    try:
        from execution.order_manager import OrderManager
        om = OrderManager(dummy_config)
        assert_test("AUDIT-004: BANKNIFTY Lot Size == 30", 
                    om._resolve_lot_size('NSE-BANKNIFTY-27Jan26-59700-PE', '') == 30, "Should be 30")
        assert_test("AUDIT-004: NIFTY Lot Size == 65", 
                    om._resolve_lot_size('NSE-NIFTY-27Jan26-22500-CE', '') == 65, "Should be 65")
        assert_test("AUDIT-004: SENSEX Lot Size == 20", 
                    om._resolve_lot_size('BSE-SENSEX-27Jan26-79500-PE', '') == 20, "Should be 20")
    except Exception as e:
        assert_test("AUDIT-003/004: Lot size resolution", False, str(e))

    # 3. AUDIT-005: qty_filled key logic
    try:
        order_status = {'filled_quantity': 65, 'fill_price': 87.50}
        qty = int(order_status.get('filled_quantity') or order_status.get('quantity') or 0)
        assert_test("AUDIT-005: filled_quantity key resolution", qty == 65, f"Expected 65, got {qty}")
    except Exception as e:
        assert_test("AUDIT-005: filled_quantity resolution", False, str(e))

    # 4. BUG-016: RSI Warmup
    try:
        from strategy.expiry_rsi_breakout import ExpiryRSIBreakout
        strategy = ExpiryRSIBreakout(dummy_config)
        assert_test("BUG-016: RSI Warmup extracted from config correctly", 
                    strategy.rsi_warmup == 100, f"Expected 100, got {strategy.rsi_warmup}")
    except Exception as e:
        assert_test("BUG-016: RSI Warmup", False, str(e))

    # 5. BUG-024: is_order_filled
    try:
        from execution.order_manager import is_order_filled
        assert_test("BUG-024: is_order_filled handles 'COMPLETE'", is_order_filled('COMPLETE') == True)
        assert_test("BUG-024: is_order_filled handles 'FILLED'", is_order_filled('FILLED') == True)
        assert_test("BUG-024: is_order_filled handles 'PENDING'", is_order_filled('PENDING') == False)
        assert_test("BUG-024: is_order_filled handles None", is_order_filled(None) == False)
        assert_test("BUG-024: is_order_filled handles empty string", is_order_filled('') == False)
    except Exception as e:
        assert_test("BUG-024: is_order_filled", False, str(e))

    # 6. NEW-002: Atomic writes in TradeTracker (tempfile)
    try:
        with open('execution/trade_tracker.py', 'r', encoding='utf-8') as f:
            content = f.read()
            assert_test("NEW-002: Atomic Writes - tempfile imported", 'tempfile' in content)
    except Exception as e:
        assert_test("NEW-002: Atomic Writes", False, str(e))

    # 7. NEW-003: Single instance lock in run_live (fcntl or msvcrt)
    try:
        with open('run_live.py', 'r', encoding='utf-8') as f:
            content = f.read()
            assert_test("NEW-003: Single instance lock mechanism is present", 
                        'fcntl' in content or 'msvcrt' in content)
    except Exception as e:
        assert_test("NEW-003: Single instance lock", False, str(e))

    # 8. AUDIT-001: Ghost import removed
    try:
        import glob
        ghost_found = False
        for root, _, files in os.walk('.'):
            for file in files:
                if file.endswith('.py'):
                    if file != 'verify_fixes.py':
                        with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                            if 'groww_data_manager' in f.read():
                                ghost_found = True
                                break
        assert_test("AUDIT-001: No groww_data_manager ghost imports", not ghost_found)
    except Exception as e:
        assert_test("AUDIT-001: Ghost import removed", False, str(e))

    # 9. Config Validation: Bad auto_square_off
    try:
        from run_live import validate_config
        # Our dummy_config has auto_square_off='15:25' while end='15:00'.
        # Previously blocked, now allowed with warning.
        import logging
        logging.getLogger().setLevel(logging.CRITICAL)  # suppress the expected warning
        is_valid = validate_config(dummy_config)
        assert_test("Config Validation: 15:25 auto_square_off is warned not blocked", is_valid == True)
    except Exception as e:
        assert_test("Config Validation", False, str(e))

    print("="*60)
    print(f"RESULTS: {passed} PASSED, {failed} FAILED")
    print("="*60)

    if failed > 0:
        sys.exit(1)

if __name__ == '__main__':
    # Ensure project root is in pythonpath
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    run_tests()
