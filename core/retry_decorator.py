# core/retry_decorator.py
import time
import logging
from functools import wraps

logger = logging.getLogger(__name__)

def retry(max_attempts=3, backoff=2.0, exceptions=(Exception,)):
    """
    Retry decorator for handling transient network/API failures.
    
    Args:
        max_attempts: Maximum number of retry attempts
        backoff: Exponential backoff multiplier (seconds)
        exceptions: Tuple of exceptions to catch and retry
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            last_exception = None
            
            while attempt < max_attempts:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    attempt += 1
                    
                    if attempt >= max_attempts:
                        logger.error(f"{func.__name__} failed after {max_attempts} attempts: {e}")
                        raise
                    
                    wait_time = backoff ** attempt
                    logger.warning(f"{func.__name__} failed (attempt {attempt}/{max_attempts}): {e}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
            
            raise last_exception
        
        return wrapper
    return decorator
