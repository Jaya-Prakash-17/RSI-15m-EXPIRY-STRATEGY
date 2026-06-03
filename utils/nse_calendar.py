
# Holiday data completeness tracking
HOLIDAY_DATA_VERIFIED_THROUGH = "2026-12-31"  # Update after each annual verification
HOLIDAY_DATA_SOURCE = "https://www.nseindia.com/resources/exchange-communication-holidays"

NSE_HOLIDAYS = {
    2020: [
        '2020-02-21',  # Mahashivratri
        '2020-03-10',  # Holi
        '2020-04-02',  # Ram Navami
        '2020-04-06',  # Mahavir Jayanti
        '2020-04-10',  # Good Friday
        '2020-04-14',  # Dr. Ambedkar Jayanti
        '2020-05-01',  # Maharashtra Day
        '2020-05-25',  # Id-ul-Fitr
        '2020-10-02',  # Gandhi Jayanti
        '2020-11-16',  # Gurunanak Jayanti
        '2020-11-30',  # Gurunanak Jayanti (Extra)
        '2020-12-25',  # Christmas
    ],
    2021: [
        '2021-01-26',  # Republic Day
        '2021-03-11',  # Mahashivratri
        '2021-03-29',  # Holi
        '2021-04-02',  # Good Friday
        '2021-04-14',  # Dr. Ambedkar Jayanti
        '2021-04-21',  # Ram Navami
        '2021-05-13',  # Eid ul-Fitr
        '2021-07-21',  # Bakri Id
        '2021-08-19',  # Muharram
        '2021-09-10',  # Ganesh Chaturthi
        '2021-10-15',  # Dussehra
        '2021-11-04',  # Diwali Laxmi Pujan
        '2021-11-05',  # Diwali Balipratipada
        '2021-11-19',  # Gurunanak Jayanti
    ],
    2022: [
        '2022-01-26',  # Republic Day
        '2022-03-01',  # Mahashivratri
        '2022-03-18',  # Holi
        '2022-04-14',  # Dr. Ambedkar Jayanti
        '2022-04-15',  # Good Friday
        '2022-05-03',  # Eid ul-Fitr
        '2022-08-09',  # Muharram
        '2022-08-15',  # Independence Day
        '2022-08-31',  # Ganesh Chaturthi
        '2022-10-05',  # Dussehra
        '2022-10-24',  # Diwali Laxmi Pujan
        '2022-10-26',  # Diwali Balipratipada
        '2022-11-08',  # Gurunanak Jayanti
    ],
    2023: [
        '2023-01-26',  # Republic Day
        '2023-03-07',  # Holi
        '2023-03-30',  # Ram Navami
        '2023-04-04',  # Mahavir Jayanti
        '2023-04-07',  # Good Friday
        '2023-04-14',  # Dr. Ambedkar Jayanti
        '2023-05-01',  # Maharashtra Day
        '2023-06-29',  # Bakri Id
        '2023-08-15',  # Independence Day
        '2023-09-19',  # Ganesh Chaturthi
        '2023-10-02',  # Gandhi Jayanti
        '2023-10-24',  # Dussehra
        '2023-11-13',  # Diwali Laxmi Pujan
        '2023-11-14',  # Diwali Balipratipada
        '2023-11-27',  # Gurunanak Jayanti
        '2023-12-25',  # Christmas
    ],
    2024: [
        '2024-01-22',  # Special Holiday
        '2024-01-26',  # Republic Day
        '2024-03-08',  # Mahashivratri
        '2024-03-25',  # Holi
        '2024-03-29',  # Good Friday
        '2024-04-11',  # Id-Ul-Fitr
        '2024-04-17',  # Ram Navami
        '2024-05-01',  # Maharashtra Day
        '2024-05-20',  # General Elections
        '2024-06-17',  # Bakri Id
        '2024-07-17',  # Muharram
        '2024-08-15',  # Independence Day
        '2024-10-02',  # Gandhi Jayanti
        '2024-11-01',  # Diwali Laxmi Pujan
        '2024-11-15',  # Gurunanak Jayanti
        '2024-11-20',  # Maharashtra Assembly Elections
        '2024-12-25',  # Christmas
    ],
    2025: [
        '2025-02-26',  # Mahashivratri
        '2025-03-14',  # Holi
        '2025-03-31',  # Id-Ul-Fitr
        '2025-04-10',  # Mahavir Jayanti
        '2025-04-14',  # Dr. Ambedkar Jayanti
        '2025-04-18',  # Good Friday
        '2025-05-01',  # Maharashtra Day
        '2025-08-15',  # Independence Day
        '2025-08-27',  # Ganesh Chaturthi
        '2025-10-02',  # Gandhi Jayanti / Dussehra
        '2025-10-10',  # Additional Holiday
        '2025-10-21',  # Diwali Laxmi Pujan
        '2025-10-22',  # Diwali Balipratipada
        '2025-11-05',  # Gurunanak Jayanti
        '2025-12-25',  # Christmas
    ],
    2026: [
        '2026-01-26',  # Republic Day
        '2026-03-03',  # Holi
        '2026-03-26',  # Ram Navami
        '2026-03-31',  # Mahavir Jayanti
        '2026-04-03',  # Good Friday
        '2026-04-14',  # Dr. Ambedkar Jayanti
        '2026-05-01',  # Maharashtra Day
        '2026-05-28',  # Bakri Id
        '2026-06-26',  # Muharram
        '2026-09-14',  # Ganesh Chaturthi
        '2026-10-02',  # Gandhi Jayanti
        '2026-10-20',  # Dussehra
        '2026-11-10',  # Diwali (Balipratipada)
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

def validate_holiday_list():
    """Verify no holidays fall on weekends (they would be redundant)."""
    from datetime import date, datetime
    for year, holidays in NSE_HOLIDAYS.items():
        for h in holidays:
            d = datetime.strptime(h, '%Y-%m-%d').date()
            if d.weekday() >= 5:
                print(f"WARNING: {h} is a weekend ({d.strftime('%A')}) in NSE_HOLIDAYS[{year}]")

def get_trading_days_count(start_date, end_date) -> int:
    """Count actual trading days between two dates (inclusive).
    Useful for estimating data download size before hitting API."""
    from datetime import timedelta
    count = 0
    d = start_date
    while d <= end_date:
        if is_trading_day(d):
            count += 1
        d += timedelta(days=1)
    return count

if __name__ == '__main__':
    validate_holiday_list()
