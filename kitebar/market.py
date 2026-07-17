"""IST clock and NSE market-hours helpers."""

from datetime import datetime, timedelta

from .constants import IST, MARKET_CLOSE, MARKET_OPEN

def now_ist():
    return datetime.now(IST)


def is_market_open(dt):
    """NSE cash-market hours: Mon–Fri 09:15–15:30 IST (holidays not modelled)."""
    return dt.weekday() < 5 and MARKET_OPEN <= dt.time() <= MARKET_CLOSE


def last_market_close(dt):
    """The most recent market close at or before `dt` (IST)."""
    day = dt
    while True:
        candidate = day.replace(hour=MARKET_CLOSE.hour, minute=MARKET_CLOSE.minute,
                                second=0, microsecond=0)
        if day.weekday() < 5 and candidate <= dt:
            return candidate
        day = (day - timedelta(days=1)).replace(hour=23, minute=59)
