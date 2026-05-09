# core/rate_limiter.py
"""
[BUG-RATELIMIT-01] Shared rate limiter for broker API calls.
Prevents LTP polling bursts from starving order management.
"""
import time


class RateLimiter:
    """Thread-safe rate limiter using monotonic clock.

    All API calls — LTP polling, order status checks, and order placement —
    share a single instance to enforce a global calls-per-second budget.
    """

    def __init__(self, calls_per_second: float = 5.0):
        self._interval = 1.0 / calls_per_second
        self._last_call = 0.0

    def acquire(self):
        """Block until the next call is allowed within the rate budget."""
        now = time.monotonic()
        wait = self._interval - (now - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    @property
    def interval(self) -> float:
        return self._interval
