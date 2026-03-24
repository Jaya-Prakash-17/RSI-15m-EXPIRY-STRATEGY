"""
core/exceptions.py — P-06
Domain exception hierarchy for the RSI-15m trading bot.
Import and raise these instead of generic Exception for meaningful error handling.
"""


class BotError(Exception):
    """Base for all bot-specific errors."""
    pass


# ─── Order Errors ────────────────────────────────────────────
class OrderError(BotError):
    pass


class InsufficientMarginError(OrderError):
    """Not enough margin to place order."""
    pass


class OrderRejectedError(OrderError):
    """Broker rejected the order."""
    def __init__(self, message: str, order_id: str = "", reason: str = ""):
        super().__init__(message)
        self.order_id = order_id
        self.reason = reason


class PositionNotFoundError(OrderError):
    """Attempting to close a position that doesn't exist."""
    pass


# ─── Network Errors ──────────────────────────────────────────
class NetworkError(BotError):
    pass


class NetworkTimeoutError(NetworkError):
    pass


class AuthExpiredError(NetworkError):
    pass


class MarketHaltedError(NetworkError):
    pass


# ─── Data Errors ─────────────────────────────────────────────
class DataError(BotError):
    pass


class InsufficientDataError(DataError):
    def __init__(self, symbol: str, required: int, available: int):
        super().__init__(f"Need {required} candles for {symbol}, got {available}")
        self.symbol = symbol
        self.required = required
        self.available = available


class SymbolNotFoundError(DataError):
    pass


# ─── Config Errors ───────────────────────────────────────────
class ConfigError(BotError):
    pass
