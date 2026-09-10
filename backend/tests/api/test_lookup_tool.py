"""L2 — `lookup` **over HTTP** (Spec §7.2.2, §7.1). U015's half of the M1 proof.

`tests/api/test_acceptance_synthetic.py` already proves the acceptance table by calling
:func:`vsir.serve.tools.lookup.lookup` in-process. This file asks a narrower and more suspicious
question: *does that proof survive the wrapper?* The seam it guards is the one the plan calls out
— "the wrapper re-implements status or cap logic, so M1's proof stops applying at the tool
boundary" — so the rows here are the same rows, re-run through `POST /tools/lookup` with a bearer
token, an ASGI stack and a JSON round trip in between.

Every expected value is read out of `data/fixtures/synthetic_pages/expected.json`. A number in
this file that the corpus does not also state would be a number somebody could adjust to make a
run green, which is exactly what C10 forbids.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from vsir.core.status import ABSENCES, Status
from vsir.eval import synthetic
from vsir.serve.envelope import WEAK_ABS, LookupHit, SearchResponse

from conftest import serve_env

LOOKUP = "/tools/lookup"

#: The acceptance table, read at collection time so each of the eight spellings of §12.3 is its
#: own red row rather than one assertion inside a loop. It is the same checked-in file the
#: `corpus` fixture hands the other tests — read twice, never restated (C10).
EXPECTED = synthetic.load().expected


def ask(served: Any, token_header: dict, **body: Any) -> Any:
    response = served.post(LOOKUP, json=body, headers=token_header)
    assert response.status_code == 200, response.text
    return response.json()


def page_ids(payload: dict) -> list[str]:
    return [hit["page_id"] for hit in payload["hits"]]


# ── the acceptance table, through the wrapper ───────────────────────────────────────────────────

def test_lookup_sf_1_1a_over_http_returns_exactly_one(served, token_header, corpus):
    """§12.3's first row, and U015's first acceptance criterion: `ok`, `total == 1`.

    The decoy page carries all three tokens and no phrase, so any-order matching returns two
    pages here and a phrase returns one (F1). That the wrapper cannot change that is the point.
    """
    row = corpus.expected["compact_labels"][0]

    payload = ask(served, token_header, label=row["label"])

    assert payload["status"] == Status.OK.value
    assert payload["total"] == 1
    assert page_ids(payload) == [row["page_id"]]
    assert corpus.expected["decoy"]["page_id"] not in page_ids(payload)


@pytest.mark.parametrize("row", EXPECTED["compact_labels"], ids=lambda row: row["label"])
def test_every_compact_label_is_found_over_http(served, token_header, row):
    """F3 — the eight spellings of §12.3, each one found through the HTTP surface."""
    payload = ask(served, token_header, label=row["label"])

    assert payload["status"] == Status.OK.value, row["variant"]
    assert row["page_id"] in page_ids(payload)


def test_a_hallucinated_code_is_unfindable_over_http(served, token_header, corpus):
    """F14, AC-001 — the page *claims* `K999`; its text does not carry it, so nothing finds it.

    `ingest/probe.py` is the only writer of `text` (I2), so this is not "unlikely to match": there
    is no surface the claim could have reached. It comes back only through `unverified_hits`, and
    only when the caller opted in.
    """
    row = corpus.expected["hallucinated"]

    plain = ask(served, token_header, label=row["label"])
    opted_in = ask(served, token_header, label=row["label"], include_unverified=True)

    assert plain["status"] == row["status"]
    assert plain["hits"] == [] and plain["unverified_hits"] == []
    assert opted_in["hits"] == []
    assert len(opted_in["unverified_hits"]) == row["unverified_hits"]
    assert all(hit["verified"] is False for hit in opted_in["unverified_hits"])
    assert opted_in["unverified_hits"][0]["page_id"] == row["page_id"]


def test_include_unverified_leaves_hits_unchanged(served, token_header, corpus):
    """§7.2.2 — *"scores and lists are never merged"*. Opting in adds a list; it edits nothing.

    A `vlm_codes` hit merged into `hits` would make an opt-in flag change what "verified" means,
    which is the one thing D3 ships this surface on condition of never doing.
    """
    label = corpus.expected["compact_labels"][0]["label"]

    plain = ask(served, token_header, label=label)
    opted_in = ask(served, token_header, label=label, include_unverified=True)

    assert opted_in["hits"] == plain["hits"]
    assert opted_in["total"] == plain["total"]
    assert all(hit["verified"] is True for hit in plain["hits"])


# ── `next.suggest` and the tokens behind it (§7.1) ──────────────────────────────────────────────

def test_a_not_found_a_skim_could_answer_carries_the_move_and_the_tokens(served, token_header,
                                                                         corpus):
    """§12.3's row, and U015's second acceptance criterion.

    Both words are in the corpus and the phrase is nowhere, so the honest answer is `not_found`
    *plus* an affordance. The status stays honest; `next.suggest` is what stops the agent
    abstaining on a phrasing accident, and `tokens_observed` is the evidence §7.1 asks for in the
    same sentence — so a caller can tell "the words are here, the phrase is not" from "none of
    this is in the corpus" without spending a skim to find out.
    """
    row = corpus.expected["suggest"]

    payload = ask(served, token_header, label=row["label"])

    assert payload["status"] == row["status"] == Status.NOT_FOUND.value
    assert payload["next"]["suggest"] == row["suggest"]
    assert payload["next"]["tokens_observed"] == row["tokens_observed"]


def test_a_not_found_nothing_could_answer_carries_no_move(served, token_header, corpus):
    """The affordance is earned, not reflexive: no token of `K999` occurs anywhere in `text`."""
    row = corpus.expected["hallucinated"]

    payload = ask(served, token_header, label=row["label"])

    assert payload["status"] == Status.NOT_FOUND.value
    assert payload["next"] == row["next"] is None


def test_the_asymmetric_variant_degrades_to_an_abstention_with_a_move(served, token_header,
                                                                      corpus):
    """R1 — `variants()` cannot re-space one boundary and not the others, so recall has a gap.

    The gap degrades to `not_found` **with** a next move, and never to a wrong page. That is the
    whole design in one row.
    """
    row = corpus.expected["asymmetric_variant"]

    payload = ask(served, token_header, label=row["label"])

    assert payload["status"] == row["status"]
    assert payload["next"]["suggest"] == row["suggest"]
    assert payload["hits"] == []


# ── `weak` is the server's, at any cap (§7.1) ───────────────────────────────────────────────────

@pytest.mark.parametrize("cap", [5, 20, 200])
def test_weak_does_not_move_with_the_callers_cap(served, token_header, corpus, cap):
    """§12.3 — `lookup("3")` unscoped is `weak` at **any** cap.

    `cap` bounds the page of the set that comes back and nothing else. A trust signal a client
    could switch off by asking for more rows would be worse than no signal at all, so `weak` is
    computed from `total` against the server constant.
    """
    row = corpus.expected["weak"]
    assert row["weak_abs"] == WEAK_ABS  # the corpus and the code agree on the constant

    payload = ask(served, token_header, label=row["label"], cap=cap)

    assert payload["total"] == row["total"]
    assert payload["weak"] is row["weak"]
    assert payload["needs_scope"] is row["needs_scope"]
    assert payload["capped"] is (row["total"] > cap)
    assert len(payload["hits"]) == min(cap, row["total"])


# ── `is_current` is injected server-side, always (I7, §6.7) ─────────────────────────────────────

def test_a_superseded_page_never_answers(served, token_header, corpus):
    """I7, F9 — the label is printed only on revision 0.9, and 0.9 is not current."""
    row = corpus.expected["superseded"][0]

    payload = ask(served, token_header, label=row["label"])

    assert payload["status"] == row["status"]
    assert len(payload["hits"]) == row["hits"] == 0


def test_a_caller_cannot_switch_is_current_off(served, token_header, corpus):
    """The injection is an override, not a default: an explicit `false` is replaced, and said so.

    A caller that could pass `is_current: false` could make an unpublished run answer, which is
    I7 defeated by a request parameter. The override is visible rather than silent — the response
    echoes the scope that was *actually* searched.
    """
    row = corpus.expected["superseded"][0]

    payload = ask(served, token_header, label=row["label"], scope={"is_current": False})

    assert payload["effective_scope"]["is_current"] is True
    assert payload["hits"] == []
    assert payload["status"] in {status.value for status in ABSENCES}


def test_the_label_printed_on_both_revisions_answers_once(served, token_header, corpus):
    """Only the current revision can answer, so a code on both is one hit and not two (F12)."""
    row = corpus.expected["superseded"][1]

    payload = ask(served, token_header, label=row["label"])

    assert len(payload["hits"]) == row["hits"] == 1
    assert page_ids(payload) == [row["page_id"]]


# ── every envelope carries the four context fields (§7.1) ───────────────────────────────────────

def test_every_response_carries_scope_stats_effective_scope_provenance_and_reads_remaining(
        served, token_header, corpus):
    """U015's acceptance criterion, and F8's mechanism.

    `effective_scope` is what makes the stateless service honest: the caller is told exactly what
    was searched rather than trusting a session it cannot see (C11). `scope_stats.pages_no_text`
    is the blind spot as a number, which is why F4 cannot happen quietly.
    """
    payload = ask(served, token_header, label=corpus.expected["compact_labels"][0]["label"])

    assert payload["effective_scope"] == {"is_current": True}
    stats = payload["scope_stats"]
    assert stats["pages"] == corpus.expected["corpus"]["pages"]
    assert stats["pages_no_text"] == corpus.expected["corpus"]["pages_no_text"]
    assert [doc["doc_id"] for doc in stats["docs"]] == [corpus.doc_id]
    assert stats["docs"][0]["searchable_ratio"] == pytest.approx(
        corpus.expected["corpus"]["searchable_ratio"])
    assert isinstance(payload["reads_remaining"], int)
    assert payload["provenance"] == {"run_id": "", "release_id": "test", "schema_version": 1}


def test_the_response_body_validates_as_the_declared_model(served, token_header, corpus):
    """The wire shape is §7.1's model and not a dict that resembles it.

    Re-parsing the body through `SearchResponse` also re-runs `empty_is_never_ok`, so a body this
    service emitted that I5 would reject is caught here rather than at the caller.
    """
    payload = ask(served, token_header, label=corpus.expected["compact_labels"][0]["label"])

    parsed = SearchResponse[LookupHit].model_validate(payload)

    assert parsed.status is Status.OK
    assert parsed.hits and parsed.hits[0].image is not None


def test_no_hit_carries_image_bytes(served, token_header, corpus):
    """P2, D12 — a reference is ~60 bytes and renders nothing; `bytes_b64` belongs to `fetch`.

    A raster in a triage row would let the agent answer from the search result instead of
    choosing and then paying, which is the failure the whole reference indirection prevents.
    """
    payload = ask(served, token_header, label=corpus.expected["weak"]["label"], cap=200)

    body = json.dumps(payload)
    assert "bytes_b64" not in body
    for hit in payload["hits"]:
        assert hit["image"]["url"].startswith("/pages/")
        assert hit["image"]["thumb_url"]
        assert set(hit["image"]) == {"url", "thumb_url", "dpi", "width", "height"}


def test_no_response_field_is_named_score(served, token_header, corpus):
    """§7.6 — an ordinal is permitted, a similarity is refused. Asserted on the wire, not the code.

    The conformance grep covers the declaration; this covers the thing a caller actually sees, so
    a field that arrived through a `model_dump` of something else would still be caught.
    """
    payload = ask(served, token_header, label=corpus.expected["compact_labels"][0]["label"])

    def keys(node: Any) -> list[str]:
        if isinstance(node, dict):
            return [key for name, value in node.items() for key in [name, *keys(value)]]
        if isinstance(node, list):
            return [key for item in node for key in keys(item)]
        return []

    assert "score" not in keys(payload)
    assert "fused" not in keys(payload)  # `impl`'s RRF sum — a score under another name


# ── the typed refusals of the surface (§7.3, I6) ────────────────────────────────────────────────

def test_an_unknown_scope_key_is_a_400_naming_the_key(served, token_header, corpus):
    """I6, F10 — a filter outside `INDEXED` is refused, never run as an unindexed scan.

    Silent recall loss is the failure: an unindexed filter still returns *something*, and the
    caller believes it narrowed the search.
    """
    response = served.post(LOOKUP, json={"label": "SF 1.1A", "scope": {"content.text": "x"}},
                           headers=token_header)

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "filter_unknown_key"
    assert body["keys"] == ["content.text"]


def test_a_cap_below_one_is_a_400_naming_its_bound(served, token_header):
    response = served.post(LOOKUP, json={"label": "SF 1.1A", "cap": 0}, headers=token_header)

    assert response.status_code == 400
    assert response.json() == {"error": "cap_out_of_range", "tool": "lookup",
                               "detail": response.json()["detail"], "minimum": 1, "requested": 0}


def test_a_body_that_is_not_an_object_is_a_400(served, token_header):
    """A JSON array parses fine and is still not a set of parameters."""
    response = served.post(LOOKUP, content=b'["SF 1.1A"]',
                           headers={**token_header, "content-type": "application/json"})

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


def test_lookup_is_free_and_leaves_the_read_budget_untouched(served, token_header, corpus):
    """§7.3 — only `read` charges. `reads_remaining` is reported on every envelope regardless."""
    quota = int(serve_env()["VSIR_READ_QUOTA"])
    label = corpus.expected["compact_labels"][0]["label"]

    first = ask(served, token_header, label=label)
    second = ask(served, token_header, label=label)

    assert first["reads_remaining"] == second["reads_remaining"] == quota
