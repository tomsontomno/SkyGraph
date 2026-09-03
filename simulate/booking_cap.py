"""Wizz "n flights per day" booking rule as a post-filter on routes.

A route is a list of legs ``(from_city, to_city, [departure_iso, arrival_iso])`` as produced by
core/route_find.py.  Because the DFS stores every valid prefix, filtering finished routes is
equivalent to enforcing the rule inside the search.

Modes:
  * ``calendar``: at most ``cap`` departures per local calendar day (the date part of the departure
    string, i.e. the day at the departure airport).
  * ``rolling24``: no ``cap + 1`` departures inside any window of less than 24 hours.  Departures are
    compared as aware datetimes, so the UTC offsets in the ISO strings are taken into account.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Iterable, List, Sequence

CAP_MODES = ('calendar', 'rolling24')
NO_CAP = 'none'


def passes_daily_cap(route: Sequence, cap: int, mode: str) -> bool:
    """True when ``route`` respects the booking rule.

    Preconditions: ``cap >= 1``; ``mode`` in CAP_MODES; every leg carries ISO departure strings
    with a UTC offset.  Postcondition: pure function, no side effects.
    """
    if cap < 1:
        raise ValueError(f"cap must be >= 1, got {cap}")
    if mode == 'calendar':
        per_day = Counter(leg[2][0][:10] for leg in route)
        return max(per_day.values(), default=0) <= cap
    if mode == 'rolling24':
        departures = sorted(datetime.fromisoformat(leg[2][0]) for leg in route)
        window = timedelta(hours=24)
        for i in range(len(departures) - cap):
            if departures[i + cap] - departures[i] < window:
                return False
        return True
    raise ValueError(f"unknown cap mode {mode!r}, expected one of {CAP_MODES}")


def filter_daily_cap(routes: Iterable[Sequence], cap: int, mode: str) -> List:
    """Routes that pass ``passes_daily_cap``; ``mode == 'none'`` returns everything unchanged."""
    if mode == NO_CAP:
        return list(routes)
    return [route for route in routes if passes_daily_cap(route, cap, mode)]
