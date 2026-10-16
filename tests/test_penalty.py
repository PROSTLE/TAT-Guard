"""V3 unit tests (03_VERIFIER.md). Expectations are hand-derivable and assume calendar days,
which is now verified: "T is the day of transaction and refers to the calendar date." [RBI-TAT-DAYCOUNT]"""
from datetime import date

import yaml

from recon import rules
from recon.penalty import deadline, exposure_next_24h, penalty_days, penalty_rupees

T = date(2026, 10, 1)
CASES = [
    # case,     as_of,              expected_days
    ("UPI_P2P", date(2026, 10, 1), 0),   # same day
    ("UPI_P2P", date(2026, 10, 2), 0),   # T+1: on time
    ("UPI_P2P", date(2026, 10, 3), 1),   # T+2: 1 day late -> Rs 100
    ("UPI_P2P", date(2026, 10, 6), 4),
    ("UPI_P2M", date(2026, 10, 6), 0),   # T+5: on time
    ("UPI_P2M", date(2026, 10, 7), 1),
    ("IMPS",    date(2026, 10, 3), 1),
]


def test_days():
    for case, as_of, exp in CASES:
        assert penalty_days(T, as_of, case) == exp, (case, as_of)


def test_rupees():
    assert penalty_rupees(T, date(2026, 10, 6), "UPI_P2P") == 400


def test_never_negative():
    assert penalty_days(T, date(2026, 9, 30), "UPI_P2P") == 0


def test_month_boundary_calendar_days():
    assert penalty_days(date(2026, 10, 30), date(2026, 11, 2), "UPI_P2P") == 2


def test_exposure_next_24h():
    assert exposure_next_24h(T, date(2026, 10, 2), "UPI_P2P") == 100   # tomorrow is T+2
    assert exposure_next_24h(T, date(2026, 10, 1), "UPI_P2P") == 0


def test_deadline():
    assert deadline(T, "UPI_P2M") == date(2026, 10, 6)


def test_constants_match_facts_yaml():
    # 02_CROSS_CHECK.md §7: code constants == facts.yaml values, read independently here
    facts = {f["id"]: f for f in yaml.safe_load(open(rules.FACTS_PATH, encoding="utf-8"))["facts"]}
    assert rules.tat_days() == {"UPI_P2P": facts["RBI-TAT-UPI-P2P"]["value"],
                                "UPI_P2M": facts["RBI-TAT-UPI-P2M"]["value"],
                                "IMPS": facts["RBI-TAT-IMPS"]["value"]}
    assert rules.rupees_per_day() == facts["RBI-TAT-COMP"]["value"]
    assert facts["RBI-TAT-DAYCOUNT"]["status"] == "verified"
