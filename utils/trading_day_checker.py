# utils/trading_day_checker.py
"""
Dynamic trading day verification using API data availability.
This is preferred over hardcoded calendars for accuracy.
"""
import logging
from datetime import datetime

logger = logging.getLogger("TradingDayChecker")

# Cache to avoid repeated API calls
_trading_day_cache = {}

def is_trading_day_from_api(date, groww_client, index='NIFTY'):
    """
    Check if a date is a trading day by verifying if data exists.
    
    This is the most accurate method as it checks actual data availability
    from the broker API, catching special trading days automatically.
    
    Args:
        date: Date to check (datetime or date object)
        groww_client: GrowwClient instance for API calls
        index: Index symbol to check (default: NIFTY)
    
    Returns:
        True if market data exists for this day, False otherwise
    """
    if isinstance(date, datetime):
        date = date.date()
    
    # Check cache first
    cache_key = f"{date}_{index}"
    if cache_key in _trading_day_cache:
        return _trading_day_cache[cache_key]
    
    try:
        # Try to fetch a single candle for this date
        from datetime import datetime as dt
        start_time = dt.combine(date, dt.min.time())
        end_time = dt.combine(date, dt.max.time())
        
        df = groww_client.get_historical_candles(
            symbol=index,
            interval=15,
            start_date=start_time,
            end_date=end_time
        )
        
        # If we got data, it's a trading day
        is_trading = df is not None and not df.empty
        
        # Cache the result
        _trading_day_cache[cache_key] = is_trading
        
        logger.debug(f"{date} ({date.strftime('%A')}): {'Trading Day' if is_trading else 'No Trading'}")
        
        return is_trading
        
    except Exception as e:
        logger.warning(f"Failed to check trading day via API for {date}: {e}")
        # Fall back to calendar-based check
        from utils.nse_calendar import is_trading_day
        return is_trading_day(date)

def clear_cache():
    """Clear the trading day cache"""
    global _trading_day_cache
    _trading_day_cache = {}
