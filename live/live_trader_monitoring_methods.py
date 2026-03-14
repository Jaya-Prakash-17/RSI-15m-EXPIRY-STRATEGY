# live_trader_monitoring_methods.py
#
# DEPRECATED — DO NOT USE
#
# This file previously contained duplicate definitions of:
#   - _monitor_active_trades()
#   - _handle_multi_lot_exits()
#   - _handle_single_lot_exits()
#   - _close_entire_position()
#   - _monitor_legacy_trade()
#
# These duplicates diverged from the CANONICAL versions in live/live_trader.py,
# causing BUG-002 (missing broker SL modification after partial exits) and
# BUG-003 (single-lot exit target inconsistency: T2 vs T3).
#
# All canonical code now lives in live/live_trader.py.
# This file is kept empty to prevent accidental re-creation.
#
# See git history for the original content if needed.
