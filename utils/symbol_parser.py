"""
utils/symbol_parser.py — P-17
Shared symbol parsing utilities to avoid duplicated underlying detection logic
scattered across backtest/intraday_engine.py, execution/order_manager.py, and live_trader.py.
"""


def detect_underlying(symbol: str) -> str:
    """
    Detect underlying index from a Groww option symbol.
    IMPORTANT: Checks BANKNIFTY before NIFTY — 'NIFTY' is a substring of 'BANKNIFTY'.

    WARNING: If this returns 'UNKNOWN', the caller MUST reject/skip the trade.
    Do NOT use a fallback like `underlying = 'NIFTY'` — this causes silent
    position sizing errors (e.g., SENSEX lot=20 vs NIFTY lot=65 = 3.25x error).

    Examples:
        detect_underlying('NSE-BANKNIFTY-30Mar26-52000-PE') → 'BANKNIFTY'
        detect_underlying('NSE-NIFTY-25Mar26-22500-CE')     → 'NIFTY'
        detect_underlying('BSE-SENSEX-27Mar26-75000-CE')    → 'SENSEX'
        detect_underlying('UNKNOWN-SYM')                    → 'UNKNOWN'  # MUST skip trade
    """
    for u in ('BANKNIFTY', 'SENSEX', 'NIFTY'):
        if u in symbol:
            return u
    return 'UNKNOWN'


def parse_opt_type(symbol: str) -> str:
    """
    Extract option type (CE or PE) from a Groww option symbol.

    Examples:
        parse_opt_type('NSE-NIFTY-25Mar26-22500-CE') → 'CE'
        parse_opt_type('NSE-BANKNIFTY-30Mar26-52000-PE') → 'PE'
        parse_opt_type('UNKNOWN')                         → ''
    """
    if symbol.endswith('-CE') or '-CE-' in symbol:
        return 'CE'
    if symbol.endswith('-PE') or '-PE-' in symbol:
        return 'PE'
    return ''
