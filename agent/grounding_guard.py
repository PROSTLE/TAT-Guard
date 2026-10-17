"""Grounding guard for agent answers (04_NON_HALLUCINATOR.md §5).

Every number in an answer must appear in the result sets of the SQL run in that same turn, or be one of the
regulatory constants from facts.yaml (TAT days, Rs/day). Derived numbers (sums, percentages) must therefore be
computed in SQL, so that they appear in a result set.

Changes vs the 04 §5 sketch: allowed constants come from facts.yaml via recon/rules.py (not typed in), and
non-numeric cells (dates, timestamps) are scanned for numbers too, so quoting "2026-10-07" from a result is grounded.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

try:
    from recon import rules
except ImportError:  # pragma: no cover
    import rules  # type: ignore

NUM = re.compile(r'(?<![\w.])-?\d[\d,]*(?:\.\d+)?')


def _norm(s: str):
    try:
        return Decimal(s.replace(",", "")).normalize()
    except InvalidOperation:
        return None


def numbers_in(text: str) -> set:
    return {v for v in (_norm(m) for m in NUM.findall(text)) if v is not None}


def numbers_in_results(results: list) -> set:
    """results: list of result sets; each result set is a list of rows; each row a sequence of cells."""
    out = set()
    for rows in results:
        for row in rows:
            for cell in row:
                if cell is None or isinstance(cell, bool):
                    continue
                if isinstance(cell, (int, float, Decimal)):
                    out.add(Decimal(str(cell)).normalize())
                out |= numbers_in(str(cell))   # also "2026-10-07", "18:00:00", "1,234"
    return out


def allowed_constants() -> frozenset:
    """TAT days and Rs/day: the only numbers an answer may state without a query (04 §6 system prompt)."""
    return frozenset(Decimal(v) for v in set(rules.tat_days().values()) | {rules.rupees_per_day()})


def check_answer(answer: str, sql_results: list, allowed=None) -> tuple[bool, set]:
    """Returns (ok, ungrounded_numbers)."""
    grounded = numbers_in_results(sql_results) | set(allowed_constants() if allowed is None else allowed)
    ungrounded = {n for n in numbers_in(answer) if n not in grounded}
    return (len(ungrounded) == 0, ungrounded)
