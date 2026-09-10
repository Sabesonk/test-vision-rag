"""L2 — `resolve(printed_label, doc_id?)` (Spec §7.2.3, F5, register E9, U017).

An agent reads *"see page 8"* on one page and has to open another. This is the move that turns the
label a **person** reads into the id this service addresses pages by — and its two disclosures,
`label_verified` and `interpolated`, are as much of the answer as the id is.

**Its own corpus, and that is the finding rather than a convenience.** The M1 synthetic corpus
formats every page's `printed_page_no` from `document.json` and never writes it into the page text,
so no page in it prints its own label. A resolver can only find a label some surface actually
carries, so this suite seeds three small documents whose text prints their page numbers the way a
real footer does — which is also the shape the 3-window fixture's `printed_labels` have (§12.3).

What is asserted:

* an unambiguous label resolves to one page, with `label_verified` read off the record;
* **an ambiguous label returns every candidate** (F5) — two binders that both number a page 8 are
  a question for the caller, and choosing between them silently is how a citation lands on the
  wrong page;
* a label **no page prints** is recovered from the bracket, and comes back `interpolated: true` —
  the one inference §6.5 permits, and it is only permitted because it says so;
* the mechanism is the index: an exact **phrase** filter over `text` and a **facet** over `doc_id`.
  A call spy asserts that nothing here scrolls, which is register **E9**'s defect — a fixed 4,096
  scroll window that reports *not found* about pages it never reached.
"""
from __future__ import annotations

from typing import Any

import pytest

from vsir.core import ids
from vsir.core.record import PageContent, PageRecord, Provenance
from vsir.serve.envelope import Provenance as ResponseProvenance
from vsir.serve.tools.resolve import matches, resolve

from conftest import EMBED_DIM, seed_with_vectors

RESOLVE = "/tools/resolve"
COLLECTION = "vsir_pages_u017_resolve_1536"


def page(doc_id: str, page_no: int, *, text: str, printed: str = "",
         verified: bool = False, interpolated: bool = False, candidates: tuple[str, ...] = (),
         has_text: bool = True, is_current: bool = True) -> PageRecord:
    """One §5.3 record whose **text prints its own page label**, the way a footer does."""
    revision = "1.0"
    return PageRecord(
        doc_id=doc_id, revision=revision, is_current=is_current, doc_type="manual",
        page_kind="prose", lang=["en"], page_no=page_no,
        section_id=[ids.section_id(doc_id, revision, 1)],
        series_id=[ids.series_id(doc_id, "body")],
        has_text=has_text, text_trust="ok" if has_text else "no_text",
        run_id="r-resolve", text=text,
        content=PageContent(printed_page_no=printed, label_verified=verified,
                            interpolated=interpolated, label_candidates=list(candidates)),
        provenance=Provenance(page_id=ids.page_id(doc_id, revision, page_no),
                              release_id="test"),
    )


#: Three documents. `RES-A` has a **gap**: its second page prints no label, and pages either side
#: print 7 and 9 — the bracket. `RES-B` and `RES-C` both print 8, which is the ambiguity F5 is
#: about. `RES-D` is a page that was never published and must be invisible (I7).
CORPUS = (
    page("RES-A", 1, text="Chapter 1 — introduction\nCell 3 controller\n7\n",
         printed="7", verified=True),
    page("RES-A", 2, text="Wiring of the emergency stop chain, continued.\n"),
    page("RES-A", 3, text="Spares list for the cell 3 controller\n9\n",
         printed="9", verified=True),
    page("RES-A", 4, text="Appendix A — torque figures\n10\n",
         printed="10", interpolated=True),
    page("RES-B", 1, text="Guard door interlock overview\n8\n", printed="8", verified=True),
    page("RES-C", 1, text="Panel layout, front elevation\n8\n", printed="8", verified=True),
    page("RES-D", 1, text="Draft, not published\n8\n", printed="8", verified=True,
         is_current=False),
    # §6.5's ambiguous label, in the shape `attribute_label` actually produces it: a sheet that
    # carries **both** readings, so neither the model's nor `/PageLabels`' can be preferred.
    # `printed_page_no` is empty and both live in `label_candidates`.
    page("RES-E", 1, text="Torque table 13 / 18 — continued from the previous sheet\n",
         candidates=("13", "18")),
    # The other shape of the same ambiguity: the page prints **neither** reading. Nothing in the
    # text layer carries either label, so no phrase query can reach it by one — the documented
    # limit, asserted below rather than left to be discovered.
    page("RES-F", 1, text="", printed="", candidates=("22", "27"), has_text=False),
)


class SpyClient:
    """Records every store call by name and answers from the real client (see E9)."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self.inner, name)
        if not callable(attribute):
            return attribute

        def recorded(*args: Any, **call: Any) -> Any:
            self.calls.append(name)
            return attribute(*args, **call)

        return recorded


@pytest.fixture(scope="module")
def resolve_collection(qdrant, stub_embedder):
    seed_with_vectors(qdrant, COLLECTION, CORPUS, dim=EMBED_DIM, embedder=stub_embedder)
    try:
        yield COLLECTION
    finally:
        if qdrant.collection_exists(COLLECTION):
            qdrant.delete_collection(COLLECTION)


@pytest.fixture
def ask(qdrant, resolve_collection):
    def _resolve(printed_label: str, **arguments: Any):
        return resolve(qdrant, resolve_collection, printed_label,
                       provenance=ResponseProvenance(release_id="test"), **arguments)
    return _resolve


# ── the label comparison ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("requested,stored,expected", [
    ("8", "8", True),
    ("Page 8 of 55", "8", True),           # a citation, against a footer that prints the number
    ("8", "Page 8 of 30", True),           # and the other way round
    ("8", "18", False),                    # never a substring of a token
    ("8", "88", False),
    ("8", "", False),
    ("iv", "iv", True),
    ("3-2", "3-2", True),
    ("3-2", "3-1", False),
])
def test_a_label_matches_as_a_phrase_and_never_as_a_distance(requested, stored, expected):
    """The same contiguous, in-order mechanism the index uses — no edit distance (§7.6, F16)."""
    assert matches(requested, stored) is expected


# ── the answer ──────────────────────────────────────────────────────────────────────────────────

def test_an_unambiguous_label_resolves_to_one_page_with_its_disclosures(ask):
    response = ask("7", doc_id="RES-A")

    assert response.status.value == "ok"
    [hit] = response.hits
    assert hit.page_id == "RES-A@1.0#p001"
    assert hit.printed_page_no == "7"
    assert hit.label_verified is True
    assert hit.interpolated is False
    assert hit.image is not None and hit.image.url.endswith("/image?dpi=150")


def test_interpolated_is_read_off_the_record_not_re_derived(ask):
    """§6.5 recorded it at derivation, weighing the page's own text; this is not a second opinion."""
    [hit] = ask("10", doc_id="RES-A").hits

    assert hit.page_id == "RES-A@1.0#p004"
    assert hit.interpolated is True
    assert hit.label_verified is False


def test_a_citation_resolves_to_the_page_whose_footer_prints_the_number(ask):
    """*"Page 8 of 55"* is what an agent reads; ``8`` is what the footer prints (`label_words`)."""
    response = ask("Page 8 of 55", doc_id="RES-B")

    assert response.status.value == "ok"
    [hit] = response.hits
    assert hit.page_id == "RES-B@1.0#p001"
    assert hit.printed_page_no == "8"
    assert hit.label_verified is True


def test_a_citation_that_names_two_numbers_is_ambiguous_evidence_and_says_so(ask):
    """`10` is printed in `RES-A` and `8` in two other binders: three candidates, no pick (F5).

    Not a defect to be tuned away. *"Page 8 of 10"* really could be a reference to the page
    numbered 10, and the honest answer is the list — the caller has a `doc_id` to narrow with.
    """
    response = ask("Page 8 of 10")

    assert sorted(hit.page_id for hit in response.hits) == [
        "RES-A@1.0#p004", "RES-B@1.0#p001", "RES-C@1.0#p001"]


def test_the_citation_probe_is_bounded(ask):
    """A sentence is not a citation, and cannot be turned into one query per word."""
    from vsir.serve.tools.resolve import RESOLVE_LABEL_WORDS, label_words

    assert label_words("Page 8 of 55") == ["8", "55"]
    assert label_words("see the diagram") == []
    assert len(label_words(" ".join(str(n) for n in range(50)))) == RESOLVE_LABEL_WORDS


def test_a_page_whose_own_label_is_ambiguous_answers_to_every_reading_of_it(ask):
    """U009's recorded follow-up, and F5 from the other side (§6.5).

    Reading only `printed_page_no` would make exactly the pages a citation is most likely to be
    wrong about the pages no citation can open: §6.5 leaves `printed_page_no` **empty** when the
    two readings cannot be arbitrated, and puts both in `label_candidates`.
    """
    thirteen = ask("13", doc_id="RES-E")
    eighteen = ask("18", doc_id="RES-E")

    assert [hit.page_id for hit in thirteen.hits] == ["RES-E@1.0#p001"]
    assert [hit.page_id for hit in eighteen.hits] == ["RES-E@1.0#p001"]
    # Echoed as stored: the page has no settled label, and writing the reading that matched would
    # claim it prints one. `label_verified: false` is the disclosure.
    assert thirteen.hits[0].printed_page_no == ""
    assert thirteen.hits[0].label_verified is False
    assert thirteen.hits[0].interpolated is False


def test_a_reading_the_page_does_not_print_cannot_be_reached_and_says_so(ask):
    """The documented limit, asserted so it is a decision rather than a discovery.

    `attribute_label` produces candidates in two shapes (§6.5): a sheet that prints **both**
    readings — reachable by either, above — and a page that prints **neither**, where the model and
    `/PageLabels` simply disagree. The second is invisible to a phrase query for the same reason an
    `interpolated` label is: there is nothing in the text layer to match. It comes back as a typed
    absence with the move that *can* still answer, never as a silent nothing.

    The bracket does not rescue this one either: it needs both neighbours printed, and this page's
    document has none.
    """
    response = ask("22", doc_id="RES-F")

    assert response.status.value == "not_searchable"
    assert response.hits == []


def test_the_labels_a_page_answers_to_are_its_settled_one_or_its_candidates():
    from vsir.serve.tools.resolve import labels_of

    assert labels_of({"printed_page_no": "8"}) == ["8"]
    assert labels_of({"printed_page_no": "", "label_candidates": ["13", "18"]}) == ["13", "18"]
    # A settled label wins: candidates are only populated where there is no settled reading.
    assert labels_of({"printed_page_no": "8", "label_candidates": ["13"]}) == ["8"]
    assert labels_of({}) == []


def test_an_ambiguous_label_returns_every_candidate(ask):
    """**F5.** Two binders both number a page 8; a silent pick is how a citation goes wrong."""
    response = ask("8")

    assert response.status.value == "ok"
    assert [hit.page_id for hit in response.hits] == ["RES-B@1.0#p001", "RES-C@1.0#p001"]
    assert all(hit.label_verified for hit in response.hits)
    assert response.total == 2


def test_doc_id_narrows_an_ambiguous_label_to_one_candidate(ask):
    [hit] = ask("8", doc_id="RES-B").hits

    assert hit.page_id == "RES-B@1.0#p001"


def test_a_label_no_page_prints_is_recovered_from_the_bracket_and_says_so(ask):
    """The one inference §6.5 permits: *n−1* and *n+1*, two physical pages apart.

    Nothing prints `8` in `RES-A`, so the phrase surface is structurally blind to it — which is
    exactly the case `interpolated` exists to disclose. The page comes back, and it comes back
    labelled as inferred rather than read.
    """
    response = ask("8", doc_id="RES-A")

    assert response.status.value == "ok"
    [hit] = response.hits
    assert hit.page_id == "RES-A@1.0#p002"
    assert hit.interpolated is True
    assert hit.label_verified is False
    assert hit.printed_page_no == ""


def test_the_bracket_never_extrapolates_from_one_neighbour(ask):
    """`11` has a `10` below it and nothing above: one neighbour and a delta is a guess (§6.5)."""
    response = ask("11", doc_id="RES-A")

    assert response.status.value == "not_found"
    assert response.hits == []


def test_a_label_nothing_carries_is_a_typed_absence_with_an_affordance(ask):
    response = ask("404")

    assert response.status.value == "not_found"
    assert response.hits == []
    assert response.next is not None
    assert response.next.suggest == ["skim_pages", "lookup"]


def test_an_unpublished_page_is_not_resolvable(ask):
    """I7 — `is_current=True` is injected server-side and the caller does not get a vote."""
    response = ask("8")

    assert "RES-D@1.0#p001" not in [hit.page_id for hit in response.hits]
    assert response.effective_scope["is_current"] is True


# ── the mechanism (register E9) ─────────────────────────────────────────────────────────────────

def test_resolve_uses_an_indexed_facet_and_never_scrolls(qdrant, resolve_collection):
    """E9 — the defect was a fixed scroll window, so the fix is that there is no scroll at all.

    `facet` is the indexed query that answers *"which binders print this label"* without counting
    payloads in this process; `query_points` returns the bounded, page-ordered candidates. Neither
    is `scroll`, and a `scroll` reappearing here is the regression this asserts against.
    """
    spy = SpyClient(qdrant)
    resolve(spy, resolve_collection, "8", provenance=ResponseProvenance(release_id="test"))

    assert "scroll" not in spy.calls
    assert "facet" in spy.calls
    assert "query_points" in spy.calls


def test_the_candidate_fetch_is_bounded_and_page_ordered(ask):
    """A capped resolve returns the **first** pages of the set, not an arbitrary sample of it."""
    response = ask("8")

    assert response.capped is False
    assert [hit.page_id for hit in response.hits] == sorted(hit.page_id for hit in response.hits)


def test_a_confirmation_past_the_first_window_is_still_found(qdrant, stub_embedder):
    """E9, in the shape that actually bites: the label is on a page the first window misses.

    A bare number is printed as a *number* on many pages and as a *label* on one. Here 130 pages
    carry the token `40` in their body text and the page whose **footer** prints it is the last of
    them — two windows past the first. A resolver that compared one window would report
    `not_found` about a page it never looked at, which is exactly what register E9 describes.
    """
    from vsir.serve.tools.resolve import RESOLVE_CANDIDATES

    pages = RESOLVE_CANDIDATES * 2 + 2
    corpus = [page("RES-WIDE", n, text=f"Torque figures: tighten to 40 Nm. Step {n}.\n")
              for n in range(1, pages)]
    corpus.append(page("RES-WIDE", pages, text="Index of parts\n40\n", printed="40",
                       verified=True))
    seed_with_vectors(qdrant, "vsir_pages_u017_wide_1536", corpus, dim=EMBED_DIM,
                      embedder=stub_embedder)
    try:
        response = resolve(qdrant, "vsir_pages_u017_wide_1536", "40",
                           provenance=ResponseProvenance(release_id="test"))
    finally:
        qdrant.delete_collection("vsir_pages_u017_wide_1536")

    assert response.total == pages
    assert response.capped is False, "the whole matched set was compared"
    assert [hit.page_id for hit in response.hits] == [f"RES-WIDE@1.0#p{pages:03d}"]


# ── the refusals ────────────────────────────────────────────────────────────────────────────────

def test_an_empty_label_is_a_typed_400(ask):
    from vsir.serve.caps import ToolError

    with pytest.raises(ToolError) as refusal:
        ask("   ")
    assert refusal.value.code == "label_empty"


# ── over HTTP, through the release's own dispatcher ─────────────────────────────────────────────

def test_resolve_over_http_is_the_same_answer(skimming, token_header, resolve_collection,
                                              qdrant, monkeypatch):
    """The tool is reachable at `POST /tools/resolve` and its envelope is Family A (§7.1).

    Pointed at the suite's own collection by configuration rather than by patching the tool: the
    app reads `VSIR_COLLECTION`, so this is the shipped resolution path with a different corpus
    under it.
    """
    from fastapi.testclient import TestClient

    from vsir.serve.app import create_app

    from conftest import SKIM_RUNS, serve_env

    with TestClient(create_app(serve_env(VSIR_COLLECTION="vsir_pages_u017_resolve",
                                         VSIR_RUNS_COLLECTION=SKIM_RUNS))) as client:
        response = client.post(RESOLVE, json={"printed_label": "8"}, headers=token_header)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert [hit["page_id"] for hit in body["hits"]] == ["RES-B@1.0#p001", "RES-C@1.0#p001"]
    assert body["effective_scope"] == {"is_current": True}
    assert "bytes_b64" not in response.text
