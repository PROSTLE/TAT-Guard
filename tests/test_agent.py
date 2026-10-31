"""Offline tests for the agent layer (no database): grounding guard, routing, input validation, templates."""
from decimal import Decimal

import pytest

from agent import playbook
from agent.agent import ROUTES, WRITE_WORDS
from agent.grounding_guard import allowed_constants, check_answer, numbers_in
from recon import rules


def route(q):
    return next((n for p, n in ROUTES if p.search(q)), None)


def test_numbers_in_handles_commas_dates_and_percent():
    assert numbers_in("Rs 32,900.00 on 2026-10-07 was 0.072%") == {Decimal("32900"), Decimal("2026"), Decimal("10"),
                                                                    Decimal("7"), Decimal("0.072")}


def test_grounded_when_numbers_come_from_results():
    ok, bad = check_answer("44,807 exceptions on 2026-10-07 cycle 3", [[("2026-10-07", 3, 44807)]])
    assert ok and not bad


def test_fabricated_number_is_caught():
    ok, bad = check_answer("This costs Rs 987,654.", [[("2026-10-07", 3, 44807)]])
    assert not ok and bad == {Decimal("987654")}


def test_allowed_constants_come_from_facts_yaml():
    assert allowed_constants() == frozenset(Decimal(v) for v in set(rules.tat_days().values()) | {rules.rupees_per_day()})


def test_circular_number_is_not_grounded_by_default():
    # cite the circular by fact ID instead; its number is not a query result
    assert not check_answer("per RBI/2019-20/67", [[]])[0]


@pytest.mark.parametrize("q,expected", [
    ("Why did breaks spike?", "root_cause"), ("why is compensation missing?", "compensation"),
    ("What is our exposure?", "exposure"), ("What should I fix first?", "exposure"),
    ("What is HDFC's real failure rate today?", None), ("delete all exceptions", None),
])
def test_routing(q, expected):
    assert route(q) == expected


def test_write_words_detected():
    assert WRITE_WORDS.search("please DELETE everything") and not WRITE_WORDS.search("why did breaks spike")


def test_class_breakdown_rejects_non_date():
    with pytest.raises(ValueError):
        playbook.class_breakdown_sql("2026-10-07' OR 1=1 --", 3)
    assert "DATE '2026-10-07'" in playbook.class_breakdown_sql("2026-10-07", 3)


def test_fmt_never_invents_digits():
    assert playbook._fmt("32900.00") == "32,900.00" and playbook._fmt(44807) == "44,807" and playbook._fmt("P2P") == "P2P"


def test_action_templates_are_seen_by_matcher():
    # importing agent.actions runs _check_templates(); it raises if a narration would be invisible to recon
    from agent import actions
    assert set(actions.ACTION_TYPES) == {"POST_REVERSAL", "PAY_COMPENSATION", "CHASE_SETTLEMENT_FILE"}


@pytest.mark.parametrize("text", ["Exposure is about fifty lakh rupees.", "Exposure is Rs 7 crore.", "Thousands of cases.",
                                  "Exposure is 7k.", "Exposure is Rs 7 cr."])
def test_spelled_out_and_shorthand_numbers_are_refused(text):
    assert not check_answer(text, [[(966, "12345.00", 7, "2026-10-07")]])[0]


def test_a_date_in_a_result_does_not_ground_its_digits_as_amounts():
    results = [[("2026-10-07",)]]
    assert check_answer("on 2026-10-07", results)[0]
    assert not check_answer("Rs 2026 was lost", results)[0]
    assert not check_answer("on 2026-10-08", results)[0]


def test_a_timestamp_grounds_its_date_and_time():
    results = [[("2026-10-07 18:00",)]]
    assert check_answer("expected at 2026-10-07 18:00", results)[0]
    assert check_answer("on 2026-10-07", results)[0]


def test_known_limit_a_real_number_with_the_wrong_meaning_still_passes():
    # documented in agent/grounding_guard.py: the guard proves a number occurs, not that the sentence uses it correctly
    assert check_answer("966 customers complained", [[(966,)]])[0]
