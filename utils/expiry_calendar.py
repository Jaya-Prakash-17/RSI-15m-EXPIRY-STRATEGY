# utils/expiry_calendar.py
"""
Definitive Expiry Calendar — Single Source of Truth
====================================================
Covers NIFTY, BANKNIFTY, and SENSEX from Jan 2020 to present.

All change dates are sourced from official NSE/BSE circulars:
  - NSE/FAOP/57540  (Jul 12 2023) — BANKNIFTY weekly Thu → Wed, eff Sep 4 2023
  - NSE/FAOP/60011  (Dec 28 2023) — BANKNIFTY monthly Thu → Wed, eff Mar 1 2024
  - SEBI/Nov 2024   — BANKNIFTY weekly DISCONTINUED Nov 20 2024
  - NSE Jan 2025    — BANKNIFTY monthly reverted Last Wed → Last Thu
  - BSE Jan 2025    — SENSEX weekly Fri → Tue, monthly Last Fri → Last Tue
  - SEBI Aug 2025   — NSE all to Tuesday, BSE all to Thursday, eff Sep 1/2 2025

Usage
-----
    from utils.expiry_calendar import is_expiry_day, get_expiry_for_date

    # Check if a date is an expiry day
    is_expiry_day('NIFTY', date(2025, 1, 2))   # True  (Thursday)
    is_expiry_day('NIFTY', date(2026, 1, 6))   # True  (Tuesday)
    is_expiry_day('BANKNIFTY', date(2024, 3, 27))  # True (last Wednesday)

    # Find the expiry date for a given reference date
    expiry = get_expiry_for_date('NIFTY', date(2025, 12, 29))
    # Returns the nearest expiry >= reference_date
"""

import calendar
import logging
from datetime import date, datetime, timedelta

logger = logging.getLogger("ExpiryCalendar")

# ─── Change-date constants (from official circulars) ───────────────────────

# NIFTY: weekly + monthly
_NIFTY_THU_TO_TUE = date(2025, 9, 2)   # First Tuesday expiry: Sep 2 2025

# BANKNIFTY: weekly
_BNF_WEEKLY_THU_TO_WED = date(2023, 9, 4)    # First Wed weekly: Sep 6 2023
_BNF_WEEKLY_DISCONTINUED = date(2024, 11, 20) # Last weekly: Nov 20 2024

# BANKNIFTY: monthly
_BNF_MONTHLY_THU_TO_WED = date(2024, 3, 1)   # First Last-Wed monthly: Mar 27 2024
_BNF_MONTHLY_WED_TO_THU = date(2025, 1, 1)   # Reverted to Last-Thu: Jan 28 2025
_BNF_MONTHLY_THU_TO_TUE = date(2025, 9, 1)   # NSE reform: Last-Tue from Sep 2025

# SENSEX: weekly
_SNX_WEEKLY_LAUNCHED    = date(2023, 5, 1)   # BSE launched SENSEX weekly (Fridays)
_SNX_WEEKLY_FRI_TO_TUE  = date(2025, 1, 1)  # BSE shifted weekly Fri → Tue
_SNX_WEEKLY_TUE_TO_THU  = date(2025, 9, 4)  # BSE reform: Thu from Sep 4 2025

# SENSEX: monthly
_SNX_MONTHLY_FRI_TO_TUE = date(2025, 1, 1)  # BSE monthly Last-Fri → Last-Tue
_SNX_MONTHLY_TUE_TO_THU = date(2025, 9, 1)  # BSE reform: Last-Thu from Sep 2025

# Weekday integers (Python convention)
MON, TUE, WED, THU, FRI = 0, 1, 2, 3, 4


# ─── Holiday awareness (from nse_calendar) ──────────────────────────────────

def _is_trading_day(d: date) -> bool:
    """Thin wrapper — falls back gracefully if nse_calendar unavailable."""
    try:
        from utils.nse_calendar import is_trading_day
        return is_trading_day(d)
    except ImportError:
        return d.weekday() < 5  # basic weekend filter


def _prev_trading_day(d: date) -> date:
    """Return the nearest trading day at or before d."""
    while not _is_trading_day(d):
        d -= timedelta(days=1)
    return d


def _last_weekday_of_month(year: int, month: int, target_weekday: int) -> date:
    """
    Return the last occurrence of target_weekday in the given month.
    If that day is a holiday, returns the previous trading day.
    """
    last_day = calendar.monthrange(year, month)[1]
    d = date(year, month, last_day)
    while d.weekday() != target_weekday:
        d -= timedelta(days=1)
    # Adjust for holiday (NSE rule: move to PREVIOUS trading day)
    return _prev_trading_day(d)


def _is_adjusted_weekly_expiry(check_date: date, weekday_resolver) -> bool:
    """Return True when check_date is the traded day for a weekly expiry."""
    for offset in range(7):
        scheduled = check_date + timedelta(days=offset)
        target_weekday = weekday_resolver(scheduled)
        if target_weekday is None or scheduled.weekday() != target_weekday:
            continue
        if _prev_trading_day(scheduled) == check_date:
            return True
    return False


# ─── Core: expiry weekday lookup ────────────────────────────────────────────

def _nifty_expiry_weekday(d: date) -> int:
    """Return the expected expiry weekday for NIFTY on date d."""
    return TUE if d >= _NIFTY_THU_TO_TUE else THU


def _banknifty_weekly_weekday(d: date) -> int | None:
    """
    Return the expected weekly expiry weekday for BANKNIFTY on date d.
    Returns None if weekly contracts don't exist for that period.
    """
    if d >= _BNF_WEEKLY_DISCONTINUED:
        return None  # Weekly discontinued Nov 20 2024
    if d >= _BNF_WEEKLY_THU_TO_WED:
        return WED   # Weekly Wednesday (Sep 4 2023 – Nov 19 2024)
    return THU       # Weekly Thursday (before Sep 4 2023)


def _banknifty_monthly_weekday(d: date) -> int:
    """Return the expected LAST-X-of-month expiry weekday for BANKNIFTY on date d."""
    if d >= _BNF_MONTHLY_THU_TO_TUE:
        return TUE   # Last Tuesday (Sep 1 2025 onwards)
    if d >= _BNF_MONTHLY_WED_TO_THU:
        return THU   # Last Thursday (Jan 2025 – Aug 2025)
    if d >= _BNF_MONTHLY_THU_TO_WED:
        return WED   # Last Wednesday (Mar 1 2024 – Dec 2024)
    return THU       # Last Thursday (before Mar 2024)


def _sensex_expiry_weekday(d: date) -> int | None:
    """
    Return the expected weekly expiry weekday for SENSEX on date d.
    Returns None if BSE hadn't launched weekly SENSEX contracts yet.
    """
    if d < _SNX_WEEKLY_LAUNCHED:
        return None  # No weekly SENSEX contracts before May 2023
    if d >= _SNX_WEEKLY_TUE_TO_THU:
        return THU   # Thursday (Sep 4 2025 onwards)
    if d >= _SNX_WEEKLY_FRI_TO_TUE:
        return TUE   # Tuesday (Jan 1 2025 – Sep 3 2025)
    return FRI       # Friday (May 2023 – Dec 2024)


def _sensex_monthly_weekday(d: date) -> int:
    """Return the expected LAST-X-of-month expiry weekday for SENSEX on date d."""
    if d >= _SNX_MONTHLY_TUE_TO_THU:
        return THU   # Last Thursday (Sep 1 2025 onwards)
    if d >= _SNX_MONTHLY_FRI_TO_TUE:
        return TUE   # Last Tuesday (Jan 1 2025 – Aug 2025)
    return FRI       # Last Friday (before Jan 2025)


# ─── Public API ─────────────────────────────────────────────────────────────

def is_expiry_day(underlying: str, check_date: date) -> bool:
    """
    Return True if check_date is an expiry day for the given underlying.

    Holiday handling: if the calculated expiry falls on a holiday, NSE/BSE
    move it to the PREVIOUS trading day. This function checks both the
    calculated day and the adjusted day, so it handles holidays correctly.

    Args:
        underlying: 'NIFTY', 'BANKNIFTY', or 'SENSEX'
        check_date: The date to check (date or datetime or pd.Timestamp)
    """
    # Normalise to date
    if isinstance(check_date, datetime):
        check_date = check_date.date()
    elif hasattr(check_date, 'date'):
        check_date = check_date.date()

    # Must be a trading day (skip weekends + holidays)
    if not _is_trading_day(check_date):
        return False

    weekday = check_date.weekday()

    # ── NIFTY ──────────────────────────────────────────────────────────────
    if underlying == 'NIFTY':
        return _is_adjusted_weekly_expiry(check_date, _nifty_expiry_weekday)

    # ── BANKNIFTY ──────────────────────────────────────────────────────────
    elif underlying == 'BANKNIFTY':
        monthly_wd = _banknifty_monthly_weekday(check_date)
        if weekday != monthly_wd:
            # Also check if we might have a weekly expiry on a different day
            weekly_wd = _banknifty_weekly_weekday(check_date)
            if weekly_wd is None or weekday != weekly_wd:
                return False
            # It's a weekly BANKNIFTY expiry weekday — but we only trade monthly
            # for this strategy. Return False for non-monthly-expiry weeks.
            # Fall through to monthly check below to handle the last-week case.
            # Actually check if this IS the last occurrence (monthly coincides)
            # which is handled by the last-week check below.
        # Check if this is the last occurrence of monthly_wd in the month
        last_expiry = _last_weekday_of_month(check_date.year, check_date.month, monthly_wd)
        return check_date == last_expiry

    # ── SENSEX ─────────────────────────────────────────────────────────────
    elif underlying == 'SENSEX':
        return _is_adjusted_weekly_expiry(check_date, _sensex_expiry_weekday)

    else:
        logger.warning(f"Unknown underlying: {underlying}")
        return False


def get_expiry_for_date(underlying: str, reference_date: date) -> date:
    """
    Return the nearest expiry date >= reference_date for the underlying.

    Searches forward up to 35 days to find the next expiry.
    Returns reference_date itself if none found (safe fallback).

    Args:
        underlying: 'NIFTY', 'BANKNIFTY', or 'SENSEX'
        reference_date: Starting date to search from
    """
    if isinstance(reference_date, datetime):
        reference_date = reference_date.date()
    elif hasattr(reference_date, 'date'):
        reference_date = reference_date.date()

    # For monthly-only indices, compute from month directly (more efficient)
    if underlying == 'BANKNIFTY':
        monthly_wd = _banknifty_monthly_weekday(reference_date)
        year, month = reference_date.year, reference_date.month
        expiry = _last_weekday_of_month(year, month, monthly_wd)
        if expiry < reference_date:
            # This month's expiry has passed — find next month's
            if month == 12:
                year += 1
                month = 1
            else:
                month += 1
            monthly_wd = _banknifty_monthly_weekday(date(year, month, 1))
            expiry = _last_weekday_of_month(year, month, monthly_wd)
        return expiry

    # For weekly indices (NIFTY, SENSEX) scan forward
    search_date = reference_date
    for _ in range(35):  # max 5 weeks forward
        if is_expiry_day(underlying, search_date):
            return search_date
        search_date += timedelta(days=1)

    logger.warning(f"Could not find expiry for {underlying} from {reference_date} — using reference date")
    return reference_date


def get_expiry_weekday_name(underlying: str, reference_date: date) -> str:
    """Return human-readable expiry day name for a given date. Useful for logging."""
    day_names = {MON: 'Monday', TUE: 'Tuesday', WED: 'Wednesday',
                 THU: 'Thursday', FRI: 'Friday'}

    if isinstance(reference_date, datetime):
        reference_date = reference_date.date()

    if underlying == 'NIFTY':
        wd = _nifty_expiry_weekday(reference_date)
        return f"Every {day_names[wd]} (weekly)"
    elif underlying == 'BANKNIFTY':
        wd = _banknifty_monthly_weekday(reference_date)
        return f"Last {day_names[wd]} of month"
    elif underlying == 'SENSEX':
        wd = _sensex_expiry_weekday(reference_date)
        if wd is None:
            return "No weekly contracts (pre-May 2023)"
        return f"Every {day_names[wd]} (weekly)"
    return "Unknown"


# ─── Self-test ───────────────────────────────────────────────────────────────

def _run_self_test():
    """Quick sanity check — run with: python -m utils.expiry_calendar"""
    tests = [
        # NIFTY: Thursday era
        ('NIFTY', date(2023, 1, 5),  True,  "NIFTY Thu 2023"),
        ('NIFTY', date(2023, 1, 3),  False, "NIFTY non-Thu 2023"),
        ('NIFTY', date(2025, 8, 28), True,  "NIFTY last Thu before reform"),
        # NIFTY: Tuesday era
        ('NIFTY', date(2025, 9, 2),  True,  "NIFTY first Tue after reform"),
        ('NIFTY', date(2026, 1, 6),  True,  "NIFTY Tue Jan 2026"),
        ('NIFTY', date(2026, 1, 7),  False, "NIFTY Wed Jan 2026 (not expiry)"),
        # BANKNIFTY: weekly+monthly Thursday era
        ('BANKNIFTY', date(2023, 8, 31), True,  "BNF last Thu Aug 2023 (monthly)"),
        ('BANKNIFTY', date(2023, 8, 24), False, "BNF non-last Thu Aug 2023"),
        # BANKNIFTY: weekly→Wed but monthly still Last Thu (Sep 4–Feb 29, 2024)
        # Strategy trades monthly only → last Wed is NOT a trading day
        # last Thu of Sep 2023 = Sep 28 (monthly expiry)
        ('BANKNIFTY', date(2023, 9, 27), False, "BNF last Wed Sep 2023 — monthly is Thu, not Wed"),
        ('BANKNIFTY', date(2023, 9, 28), True,  "BNF last Thu Sep 2023 — correct monthly"),
        ('BANKNIFTY', date(2023, 9, 6),  False, "BNF non-last Wed Sep 2023"),
        # BANKNIFTY: monthly→Last Wed era (Mar 1 2024 – Nov 2024)
        ('BANKNIFTY', date(2024, 3, 27), True,  "BNF first Last-Wed monthly Mar 2024"),
        ('BANKNIFTY', date(2024, 3, 20), False, "BNF non-last Wed Mar 2024"),
        # After weekly discontinued (Nov 20 2024), monthly still Last Wed briefly
        ('BANKNIFTY', date(2024, 11, 27), True, "BNF last Wed Nov 2024 (monthly, weekly gone)"),
        # BANKNIFTY: reverted to Last Thursday (Jan 2025)
        # Last Thursday of Jan 2025 = Jan 30
        ('BANKNIFTY', date(2025, 1, 30), True,  "BNF Last-Thu Jan 30 2025"),
        ('BANKNIFTY', date(2025, 1, 28), False, "BNF Jan 28 2025 is Tuesday — not expiry"),
        # BANKNIFTY: Last Tuesday era (Sep 1 2025 onwards)
        ('BANKNIFTY', date(2025, 9, 30), True,  "BNF Last-Tue Sep 2025"),
        ('BANKNIFTY', date(2026, 1, 27), True,  "BNF Last-Tue Jan 2026"),
        # SENSEX: pre-launch (no weekly)
        ('SENSEX', date(2022, 12, 1),  False, "SENSEX no weekly pre-May 2023"),
        # SENSEX: Friday weekly
        ('SENSEX', date(2024, 7, 19), True,  "SENSEX Fri weekly Jul 2024"),
        ('SENSEX', date(2024, 7, 18), False, "SENSEX Thu (not expiry) Jul 2024"),
        # SENSEX: Tuesday era
        ('SENSEX', date(2025, 1, 7),  True,  "SENSEX first Tue Jan 2025"),
        # SENSEX: Thursday era
        ('SENSEX', date(2025, 9, 4),  True,  "SENSEX first Thu Sep 2025"),
        ('SENSEX', date(2026, 3, 5),  True,  "SENSEX Thu Mar 2026"),
    ]

    print("\n" + "="*60)
    print(" EXPIRY CALENDAR SELF-TEST")
    print("="*60)
    passed = failed = 0
    for underlying, d, expected, label in tests:
        result = is_expiry_day(underlying, d)
        status = "✅" if result == expected else "❌"
        if result != expected:
            failed += 1
            print(f"{status} FAIL  {label}: expected={expected} got={result}")
        else:
            passed += 1
            print(f"{status} PASS  {label}")
    print(f"\nResult: {passed} passed, {failed} failed")
    print("="*60)

    print("\nNext expiry dates from today (2026-03-15):")
    today = date(2026, 3, 15)
    for idx in ['NIFTY', 'BANKNIFTY', 'SENSEX']:
        expiry = get_expiry_for_date(idx, today)
        rule   = get_expiry_weekday_name(idx, today)
        print(f"  {idx:12} → {expiry}  ({rule})")


if __name__ == '__main__':
    _run_self_test()
