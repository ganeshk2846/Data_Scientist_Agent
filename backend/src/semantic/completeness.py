"""Completeness rules and last complete period detection (V2-DATA-1, V2-DATA-3).

Enforces:
- 2018-08 is the last complete month on Olist.
- 2018-09 (16 orders), 2018-10 (4 orders), and 2016-09 are flagged incomplete.
- Descriptive answers spanning incomplete periods must declare caveats.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# Tail & head truncated periods on Olist e-commerce snapshot
INCOMPLETE_MONTHS = frozenset({"2016-09", "2018-09", "2018-10"})
INCOMPLETE_QUARTERS = frozenset({"2016-Q3", "2018-Q3", "2018-Q4"})
LAST_COMPLETE_MONTH = "2018-08"
LAST_COMPLETE_QUARTER = "2018-Q2"
LAST_COMPLETE_YEAR = "2017"

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def last_complete_period(metric: str = "revenue", grain: str = "month") -> str:
    """Return the last complete period for a metric and time grain (V2-DATA-1)."""
    grain_clean = grain.lower().strip()
    if grain_clean in ("month", "monthly"):
        return LAST_COMPLETE_MONTH
    if grain_clean in ("quarter", "quarterly"):
        return LAST_COMPLETE_QUARTER
    if grain_clean in ("year", "yearly", "annual"):
        return LAST_COMPLETE_YEAR
    if grain_clean in ("day", "daily"):
        return "2018-08-31"
    return LAST_COMPLETE_MONTH


def is_period_complete(period: str, grain: str = "month") -> bool:
    """Return True if the period is complete, False if truncated (V2-DATA-1)."""
    p = period.strip()
    grain_clean = grain.lower().strip()

    if grain_clean in ("month", "monthly"):
        if p in INCOMPLETE_MONTHS:
            return False
        # Months after 2018-08 or before 2016-10 are incomplete
        if _MONTH_RE.match(p):
            if p > LAST_COMPLETE_MONTH or p < "2016-10":
                return False
            return True
        return False

    if grain_clean in ("quarter", "quarterly"):
        if p in INCOMPLETE_QUARTERS or p > LAST_COMPLETE_QUARTER:
            return False
        return True

    if grain_clean in ("year", "yearly", "annual"):
        # 2018 is incomplete (ended Aug), 2016 is incomplete (started Sep)
        if p in ("2016", "2018") or p > LAST_COMPLETE_YEAR:
            return False
        return True

    if grain_clean in ("day", "daily"):
        return "2016-10-01" <= p <= "2018-08-31"

    return True


def get_completeness_caveats(
    periods: Iterable[str], grain: str = "month"
) -> tuple[str, ...]:
    """Generate warning caveats if requested window includes incomplete periods (V2-DATA-3)."""
    caveats = []
    for p in periods:
        if not is_period_complete(p, grain=grain):
            if p == "2018-09":
                caveats.append(
                    "Period 2018-09 is truncated in the dataset with only 16 orders; volume is incomplete."
                )
            elif p == "2018-10":
                caveats.append(
                    "Period 2018-10 is truncated in the dataset with only 4 orders; volume is incomplete."
                )
            elif p == "2016-09":
                caveats.append(
                    "Period 2016-09 represents initial collection onset and is incomplete."
                )
            else:
                caveats.append(
                    f"Period {p} is flagged as incomplete due to low observed volume against historical baseline."
                )
    return tuple(caveats)
