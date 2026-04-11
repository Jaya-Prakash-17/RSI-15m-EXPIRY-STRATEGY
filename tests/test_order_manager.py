import pytest
from unittest.mock import MagicMock
from execution.order_manager import OrderManager, is_order_filled, is_partially_filled

@pytest.fixture
def order_manager():
    config = {
        'trading': {'paper_trading': False},
        'indices': {
            'NIFTY': {'lot_size': 75},
            'BANKNIFTY': {'lot_size': 15}
        }
    }
    om = OrderManager(config)
    om.client = MagicMock()
    return om

def test_lot_size_resolution(order_manager):
    assert order_manager._resolve_lot_size("NSE-NIFTY-JAN-22500-CE") == 75
    assert order_manager._resolve_lot_size("NSE-BANKNIFTY-JAN-52000-PE") == 15
    assert order_manager._resolve_lot_size("UNKNOWN") == 1

def test_check_order_fill_success(order_manager):
    order_manager.client.get_order_status.return_value = {
        'status': 'COMPLETE',
        'filled_quantity': 75,
        'fill_price': 150.5
    }

    price = order_manager.check_order_fill("ORD123", timeout=1)
    assert price == 150.5

def test_check_order_fill_timeout_cancel(order_manager):
    # Simulate order staying PENDING then being cancelled by timeout logic
    order_manager.client.get_order_status.side_effect = [
        {'status': 'PENDING'},
        {'status': 'PENDING'},
        {'status': 'CANCELLED'}
    ]
    order_manager.client.cancel_order.return_value = True

    price = order_manager.check_order_fill("ORD123", timeout=0.1)
    assert price is None
    order_manager.client.cancel_order.assert_called_with("ORD123")

def test_partial_fill_detection():
    assert is_partially_filled("PARTIALLY_FILLED")
    assert is_partially_filled("PARTIAL")
    assert not is_partially_filled("COMPLETE")
    assert not is_partially_filled("PENDING")

def test_full_fill_detection():
    assert is_order_filled("COMPLETE")
    assert is_order_filled("FILLED")
    assert is_order_filled("EXECUTED")
    assert not is_order_filled("PARTIALLY_FILLED")
