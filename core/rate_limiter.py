# core/rate_limiter.py
"""
[BUG-RATELIMIT-01] Shared rate limiter for broker API calls.
Prevents LTP polling bursts from starving order management.
"""
import time
import threading


class RateLimiter:
    """Thread-safe rate limiter using monotonic clock.

    All API calls — LTP polling, order status checks, and order placement —
    share a single instance to enforce a global calls-per-second budget.

    Thread-safety guarantee: The entire read-check-sleep-write cycle is
    protected by a threading.Lock, ensuring that concurrent callers from
    ThreadPoolExecutor or any other multi-threaded context are serialized
    and cannot exceed the configured rate even under contention.
    """

    def __init__(self, calls_per_second: float = 5.0):
        self._interval = 1.0 / calls_per_second
        self._last_call = 0.0
        self._lock = threading.Lock()

    def acquire(self):
        """Block until the next call is allowed within the rate budget.

        Thread-safe: only one thread proceeds through the gate at a time.
        """
        with self._lock:
            now = time.monotonic()
            wait = self._interval - (now - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    @property
    def interval(self) -> float:
        return self._interval
