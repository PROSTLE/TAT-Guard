"""Reference implementation of the RBI TAT penalty rule (pure functions, no DB).

Rule (RBI/2019-20/67): "₹100/- per day if delay is beyond T + 1 day" (UPI P2P, IMPS), "beyond T + 5 days" (UPI P2M).
"T is the day of transaction and refers to the calendar date." [RBI-TAT-DAYCOUNT]
"R is the day on which the reversal is concluded ..." [RBI-TAT-R-DEF]
So: penalty days = max(0, (R - T) in calendar days - TAT). When the case is still open, R is replaced by the as-of date.

The SQL view RECON.PENALTY_EXPOSURE must agree with this module to the rupee (02_CROSS_CHECK.md §4).
"""
from __future__ import annotations

from datetime import date, timedelta

try:
    from recon import rules
except ImportError:      # allow `python recon/penalty.py` / tests that put recon/ on sys.path
    import rules  # type: ignore


def penalty_days(txn_date: date, as_of: date, case: str) -> int:
    """Calendar days beyond T+TAT. as_of = reversal date R if resolved, else the evaluation date."""
    elapsed = (as_of - txn_date).days
    return max(0, elapsed - rules.tat_days()[case])


def penalty_rupees(txn_date: date, as_of: date, case: str) -> int:
    return penalty_days(txn_date, as_of, case) * rules.rupees_per_day()


def exposure_next_24h(txn_date: date, today: date, case: str) -> int:
    """₹ that will be owed tomorrow if still unresolved (used for queue ranking)."""
    return penalty_rupees(txn_date, today + timedelta(days=1), case)


def deadline(txn_date: date, case: str) -> date:
    """Last calendar day on which reversal is still within TAT (T + TAT)."""
    return txn_date + timedelta(days=rules.tat_days()[case])
