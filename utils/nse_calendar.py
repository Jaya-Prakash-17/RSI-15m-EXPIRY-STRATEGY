# NSE Holiday Calendar
# Format: YYYY-MM-DD
# Source: NSE official holiday calendar

NSE_HOLIDAYS = {
    2025: [
        '2025-01-26',  # Republic Day
        '2025-03-14',  # Holi
        '2025-03-31',  # Id-Ul-Fitr
        '2025-04-10',  # Mahavir Jayanti  
        '2025-04-14',  # Dr. Ambedkar Jayanti
        '2025-04-18',  # Good Friday
        '2025-05-01',  # Maharashtra Day
        '2025-06-07',  # Bakri Id
        '2025-08-15',  # Independence Day
        '2025-08-27',  # Ganesh Chaturthi
        '2025-10-02',  # Gandhi Jayanti
        '2025-10-21',  # Dussehra
        '2025-11-01',  # Diwali (Laxmi Pujan)
        '2025-11-02',  # Diwali (Balipratipada)
        '2025-11-05',  # Gurunanak Jayanti
        '2025-12-25',  # Christmas
    ],
    2026: [
        '2026-01-26',  # Republic Day
        '2026-03-03',  # Holi
        '2026-03-20',  # Id-Ul-Fitr
        '2026-03-30',  # Mahavir Jayanti
        '2026-04-03',  # Good Friday
        '2026-04-06',  # Ram Navami
        '2026-04-14',  # Dr. Ambedkar Jayanti
        '2026-05-01',  # Maharashtra Day
        '2026-05-27',  # Bakri Id
        '2026-08-15',  # Independence Day
        '2026-08-16',  # Ganesh Chaturthi (Sunday)
        '2026-10-02',  # Gandhi Jayanti
        '2026-10-10',  # Dussehra
        '2026-10-20',  # Diwali (Laxmi Pujan)
        '2026-10-21',  # Diwali (Balipratipada)
        '2026-11-24',  # Gurunanak Jayanti
        '2026-12-25',  # Christmas
    ],
}

# Special trading days (weekends when market is open)
# Format: YYYY-MM-DD
SPECIAL_TRADING_DAYS = {
    2025: [
        # Add special trading days like Budget Day on weekends
    ],
    2026: [
        '2026-02-01',  # Budget Day 2026 (Sunday - Market open)
    ],
}

def is_special_trading_day(date):
    """Check if a date is a special trading day (weekend but market open)"""
    from datetime import datetime
    if isinstance(date, datetime):
        date = date.date()
    
    date_str = date.strftime('%Y-%m-%d')
    year = date.year
    
    if year in SPECIAL_TRADING_DAYS:
        return date_str in SPECIAL_TRADING_DAYS[year]
    
    return False

def is_nse_holiday(date):
    """Check if a date is an NSE holiday"""
    from datetime import datetime
    if isinstance(date, datetime):
        date = date.date()
    
    date_str = date.strftime('%Y-%m-%d')
    year = date.year
    
    if year in NSE_HOLIDAYS:
        return date_str in NSE_HOLIDAYS[year]
    
    return False

def is_trading_day(date):
    """
    Check if a date is a trading day.
    
    Returns True if:
    - It's a weekday (Mon-Fri) and not a holiday, OR
    - It's a special trading day (e.g., Budget Day on Sunday)
    
    Returns False if:
    - It's a weekend and NOT a special trading day, OR
    - It's a declared NSE holiday
    """
    from datetime import datetime
    if isinstance(date, datetime):
        date = date.date()
    
    # Check if it's a special trading day first (overrides weekend check)
    if is_special_trading_day(date):
        return True
    
    # Weekend check (Saturday=5, Sunday=6)
    if date.weekday() >= 5:
        return False
    
    # Holiday check
    return not is_nse_holiday(date)
