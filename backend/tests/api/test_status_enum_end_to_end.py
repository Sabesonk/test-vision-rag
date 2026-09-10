"""L2 — the six-value status enum, reached through the HTTP surface (Spec §7.1, I5, AC-003).

`impl`'s own docstring called an empty ``200`` *"the agent's designed abstention path"*. §2.5 D1
records removing it as a breaking change, and this file is where the replacement is proved: an
empty `ok` is impossible, and each of the four absences is a **different instruction** to the
caller that a crafted request can actually reach.

| status | what the caller must do | reachable here |
|---|---|---|
| `ok` | use the hits | yes |
| `not_found` | abstain — unless `next.suggest` says another move could answer | yes |
| `not_searchable` | escalate to vision; do **not** conclude the part does not exist (F4) | yes |
| `out_of_scope` | re-orient and widen; the corpus was never asked | yes |
| `found_only_in_superseded` | surface the revision and let the caller decide | **M8** — see below |
| `error` | retry or report, and **never** abstain | yes, as a 5xx |

Two of those six need their wording pinned, because they are the two a reader will ask about.

**`found_only_in_superseded` is F9's, and Spec §10 closes F9 at M8** — `is_current` is injected
today (I7) so a superseded page simply cannot answer, and the corpus's own `expected.json` records
the current answer as `not_found`. Until U025 makes the probe revision-aware, emitting the sixth
value would mean claiming a row this milestone does not own (§10's "Closed at" column is
authoritative). The test below asserts the corpus's stated behaviour and names the unit that
changes it, so the day it changes this test goes red rather than quietly staying green.

**`error` is a 5xx, not a `200` whose body says `"error"`.** §7.1 is explicit: *"a backend failure
is a 5xx, never an empty result"*, and the reason is the same one behind the whole enum — a failed
call returned as a call that found nothing turns our outage into the agent's fabricated
abstention. So the value exists in the enum for a caller to switch on, and this service reaches it
by refusing with a status code, which is what the last row asserts.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from vsir.core.status import ABSENCES, Status
from vsir.eval import synthetic
from vsir.serve.app import create_app
from vsir.serve.envelope import LookupHit, SearchResponse

from conftest import serve_env

LOOKUP = "/tools/lookup"
UNREACHABLE_URL = "http://127.0.0.1:6399"  # nothing listens here, and nothing may start to

EXPECTED = synthetic.load().expected

#: One crafted request per reachable status. The request *is* the proof — a status nobody can
#: produce is a branch nobody has run.
REACHABLE = {
    Status.OK: {"label": EXPECTED["compact_labels"][0]["label"]},
    Status.NOT_FOUND: {"label": EXPECTED["suggest"]["label"]},
    Status.NOT_SEARCHABLE: {"label": EXPECTED["no_text"]["label"],
                            "scope": EXPECTED["no_text"]["scope"]},
    Status.OUT_OF_SCOPE: {"label": EXPECTED["out_of_scope"]["label"],
                          "scope": EXPECTED["out_of_scope"]["scope"]},
}


def ask(served: Any, token_header: dict, body: dict) -> dict:
    response = served.post(LOOKUP, json=body, headers=token_header)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_enum_has_exactly_six_values():
    """AC-003's first half. A seventh would make every caller's switch statement incomplete."""
    assert [status.value for status in Status] == [
        "ok", "not_found", "not_searchable", "out_of_scope", "found_only_in_superseded", "error"]
    assert len(ABSENCES) == 4 and Status.OK not in ABSENCES and Status.ERROR not in ABSENCES


@pytest.mark.parametrize("status", list(REACHABLE), ids=lambda status: status.value)
def test_each_reachable_status_is_reached_by_a_crafted_request(served, token_header, status):
    """One request per status, end to end through the wrapper (U015's acceptance criterion)."""
    payload = ask(served, token_header, REACHABLE[status])

    assert payload["status"] == status.value


def test_not_searchable_is_never_not_found(served, token_header):
    """**F4, the M3 half.** *"That part doesn't exist"* about a page nobody could read.

    The scoped call and the unscoped call for the same label are the whole distinction: scoped to
    the one page with no text layer, the honest answer is *"nothing here was searchable — escalate
    to vision"*. Unscoped, 28 pages really were searched and really do not carry it, so
    `not_found` is honest there. The corpus states both.
    """
    row = EXPECTED["no_text"]

    scoped = ask(served, token_header, {"label": row["label"], "scope": row["scope"]})
    unscoped = ask(served, token_header, {"label": row["label"]})

    assert scoped["status"] == row["scoped_status"] == Status.NOT_SEARCHABLE.value
    assert unscoped["status"] == row["unscoped_status"] == Status.NOT_FOUND.value
    assert scoped["scope_stats"]["pages"] == scoped["scope_stats"]["pages_no_text"] == 1


def test_an_untrusted_text_layer_is_also_not_searchable(served, token_header):
    """§5.7, §11.3 — a phrase that matches inside a garbled extraction is not a verified hit.

    A collapsed `grounded_rate` sets `text_trust: untrusted`, and an untrusted page counts as
    unsearchable: the text is there, and nobody may be told it is evidence.
    """
    row = EXPECTED["untrusted"]

    payload = ask(served, token_header, {"label": row["label"], "scope": row["scope"]})

    assert payload["status"] == row["scoped_status"] == Status.NOT_SEARCHABLE.value


def test_out_of_scope_is_never_not_found(served, token_header):
    """The corpus was never asked, so *"it is not there"* would be a claim about nothing."""
    row = EXPECTED["out_of_scope"]

    payload = ask(served, token_header, {"label": row["label"], "scope": row["scope"]})

    assert payload["status"] == Status.OUT_OF_SCOPE.value
    assert payload["scope_stats"]["pages"] == 0
    assert payload["scope_stats"]["docs"] == []


def test_found_only_in_superseded_is_declared_and_is_f9s_row_at_m8(served, token_header):
    """The sixth value exists; **F9 owns it and §10 closes F9 at M8** (U025).

    Today `is_current` is injected server-side on every query (I7), so a label printed only on
    revision 0.9 is not *found in a superseded revision* — it is not found at all, which is what
    the current corpus honestly says. Asserting the corpus's own statement here means the day
    U025 upgrades this answer, this test goes red and is updated deliberately.
    """
    row = EXPECTED["superseded"][0]
    assert Status.FOUND_ONLY_IN_SUPERSEDED in ABSENCES

    payload = ask(served, token_header, {"label": row["label"]})

    assert payload["status"] == row["status"] == Status.NOT_FOUND.value
    assert payload["hits"] == []


def test_error_is_a_5xx_and_never_an_empty_ok(qdrant, corpus):
    """§7.1, §11.3 — the store did not answer, so the answer is a refusal with a name.

    The one thing it must never be is a `200` with an empty `hits`: that body is
    indistinguishable from *"searched, and the part genuinely is not there"*, which is the single
    answer this system exists to be trusted about.
    """
    app = create_app(serve_env(VSIR_QDRANT_URL=UNREACHABLE_URL))
    with TestClient(app) as client:
        response = client.post(LOOKUP, json={"label": "SF 1.1A"},
                               headers={"Authorization": f"Bearer {serve_env()['VSIR_API_TOKENS']}"})

    assert response.status_code == 503
    body = response.json()
    assert body["error"] == "qdrant_unavailable"
    assert body["retryable"] is True
    assert "hits" not in body and "status" not in body


@pytest.mark.parametrize("status", list(REACHABLE), ids=lambda status: status.value)
def test_no_response_is_ok_with_nothing_in_it(served, token_header, status):
    """I5, asserted on the wire — re-validating the body re-runs `empty_is_never_ok`.

    A `200` this service emitted that the declared model would refuse to build is the exact
    defect the validator exists to make impossible, so it is checked from the outside too.
    """
    payload = ask(served, token_header, REACHABLE[status])

    parsed = SearchResponse[LookupHit].model_validate(payload)

    assert bool(parsed.hits or parsed.unverified_hits) is (parsed.status is Status.OK)


def test_an_absence_still_carries_the_full_context(served, token_header):
    """Every field a caller reasons with is present on an absence too, not only on a hit.

    An absence with no `scope_stats` is an absence a caller cannot act on: *"nothing found"* over
    40 pages of which 40 have no text layer is a completely different instruction from the same
    words over 40 searchable ones.
    """
    payload = ask(served, token_header, REACHABLE[Status.NOT_FOUND])

    assert payload["effective_scope"] == {"is_current": True}
    assert payload["scope_stats"]["pages"] == EXPECTED["corpus"]["pages"]
    assert payload["provenance"]["release_id"] == "test"
    assert isinstance(payload["reads_remaining"], int)
    assert payload["total"] == 0 and payload["capped"] is False
