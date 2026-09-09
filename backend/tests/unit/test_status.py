"""L0 — the six-value status enum (Spec §7.1, I5)."""
from __future__ import annotations

from vsir.core.status import ABSENCES, CHECK_STATES, Status


def test_there_are_exactly_six_statuses():
    assert len(list(Status)) == 6
    assert [status.value for status in Status] == [
        "ok", "not_found", "not_searchable", "out_of_scope", "found_only_in_superseded", "error",
    ]


def test_the_four_absences_are_distinct_and_do_not_include_error():
    """`error` is not an absence: an outage returned as "nothing found" is a fabricated abstention."""
    assert len(ABSENCES) == 4
    assert Status.OK not in ABSENCES
    assert Status.ERROR not in ABSENCES
    assert len(set(ABSENCES)) == 4


def test_a_status_is_its_string_so_a_response_serialises_to_the_wire_value():
    assert Status.NOT_FOUND == "not_found"
    assert f"{Status.OK}" == "ok"


def test_the_check_vocabulary_is_three_states_and_is_not_the_status_enum():
    """§7.2.4 — "is this code on this page?" has three answers, and a boolean must lie about one."""
    assert CHECK_STATES == ("present", "absent", "unverifiable")
    assert not set(CHECK_STATES) & {status.value for status in Status}
