"""Grounding guard for agent answers (04_NON_HALLUCINATOR.md §5).

Every number in an answer must appear in the result sets of the SQL run in that same turn, or be one of the
regulatory constants from facts.yaml (TAT days, Rs/day). Derived numbers (sums, percentages) must therefore be
computed in SQL, so that they appear in a result set.

Changes vs the 04 §5 sketch: allowed constants come from facts.yaml via recon/rules.py (not typed in). Dates and times
are compared as whole literals, so a date in a result grounds that date but not "2026" as an amount. Spelled-out numbers
and scale shorthand ("fifty lakh", "7 crore", "12k") are refused, because digits alone could not ground them: the answer
must quote the figure as the query returned it.

Limit: this proves each number occurs in the results, not that the sentence uses it correctly. "966 customers complained"
passes if 966 is a count of something else. The queries shown with every answer are the check for that.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

try:
    from recon import rules
except ImportError:  # pragma: no cover
    import rules  # type: ignore

NUM = re.compile(r'(?<![\w.])-?\d[\d,]*(?:\.\d+)?')
DATETIME = re.compile(r'\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?|(?<![\d:])\d{2}:\d{2}(?::\d{2})?(?![\d:])')
WORDS = re.compile(r'\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|'
                   r'seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundreds?|'
                   r'thousands?|lakhs?|lacs?|crores?|millions?|billions?|trillions?)\b', re.I)
SHORTHAND = re.compile(r'(?<![\w.])\d[\d,]*(?:\.\d+)?\s*(?:k|cr|l|mn|bn)\b', re.I)


def _norm(s: str):
    try:
        return Decimal(s.replace(",", "")).normalize()
    except InvalidOperation:
        return None


def numbers_in(text: str) -> set:
    return {v for v in (_norm(m) for m in NUM.findall(text)) if v is not None}


def split_datetimes(text: str) -> tuple[set, str]:
    """(date/time literals found, the text without them)."""
    return set(DATETIME.findall(text)), DATETIME.sub(" ", text)


def grounded_in_results(results: list) -> tuple[set, set]:
    """(numbers, date/time literals) in a list of result sets; a result set is a list of rows of cells."""
    nums, dates = set(), set()
    for rows in results:
        for row in rows:
            for cell in row:
                if cell is None or isinstance(cell, bool):
                    continue
                if isinstance(cell, (int, float, Decimal)):
                    nums.add(Decimal(str(cell)).normalize())
                found, rest = split_datetimes(str(cell))
                dates |= found | {part for d in found for part in re.split(r"[ T]", d)}   # a timestamp grounds its date too
                nums |= numbers_in(rest)                                                 # also "1,234"
    return nums, dates


def allowed_constants() -> frozenset:
    """TAT days and Rs/day: the only numbers an answer may state without a query (04 §6 system prompt)."""
    return frozenset(Decimal(v) for v in set(rules.tat_days().values()) | {rules.rupees_per_day()})


def check_answer(answer: str, sql_results: list, allowed=None) -> tuple[bool, set]:
    """Returns (ok, ungrounded_numbers)."""
    nums, dates = grounded_in_results(sql_results)
    grounded = nums | set(allowed_constants() if allowed is None else allowed)
    found, rest = split_datetimes(answer)
    ungrounded = {n for n in numbers_in(rest) if n not in grounded} | (found - dates)
    ungrounded |= {m.group(0).lower() for m in WORDS.finditer(rest)} | {m.group(0).lower() for m in SHORTHAND.finditer(rest)}
    return (len(ungrounded) == 0, ungrounded)
