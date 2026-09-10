"""L2 — the acceptance table against a **real Qdrant** (Spec §12.3, §13 M1).

This is M1's proof, and it costs nothing: an ephemeral collection seeded with hand-written page
text, no PDF, no VLM, no spend. Every number asserted here comes out of
`data/fixtures/synthetic_pages/expected.json`, so a run cannot be made green by adjusting an
expectation in the test file — a disagreement between the corpus and the table is a finding (C10).

Why these assertions need a real index rather than a fake: `phrase_matching` is the mechanism the
whole exact surface rests on, and the only evidence that a phrase behaves like a phrase is Qdrant
answering. `tests/unit/test_lookup_pure.py` asserts the same table against an in-memory evaluator;
if the two ever disagree one of them goes red, which is why both exist.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

import pytest
from qdrant_client import QdrantClient

from vsir.core import ids
from vsir.core.exact import UnknownScopeKey, exact_filter
from vsir.core.observed_tokens import from_records, is_code_like, is_searchable
from vsir.core.tok import token_set
from vsir.eval import synthetic
from vsir.serve.caps import ToolError
from vsir.serve.envelope import Provenance, Status
from vsir.serve.tools.lookup import lookup

EMBED_DIM = 1536
PROVENANCE = Provenance(run_id=synthetic.SEED_RUN_ID, release_id="test")


@pytest.fixture(scope="module")
def corpus() -> synthetic.Corpus:
    return synthetic.load()


@pytest.fixture(scope="module")
def seeded(qdrant: QdrantClient, corpus: synthetic.Corpus) -> str:
    """The §13 M1 corpus in a collection of its own, dropped at the end of the module.

    Created through `core.indexed.create_collection` and `eval.synthetic.seed` — the same code
    path `vsir demo exact --synthetic` runs, so a green suite is evidence about the shipped
    command and not about a test's private setup.
    """
    collection = synthetic.synthetic_collection("vsir_pages_acceptance", EMBED_DIM)
    synthetic.seed(qdrant, collection, corpus.records(release_id="test"), dim=EMBED_DIM)
    try:
        yield collection
    finally:
        synthetic.drop(qdrant, collection)


@pytest.fixture
def ask(qdrant: QdrantClient, seeded: str):
    def _ask(label: str, **kwargs: Any):
        return lookup(qdrant, seeded, label, provenance=PROVENANCE, **kwargs)
    return _ask


def page_ids(response: Any) -> list[str]:
    return [hit.page_id for hit in response.hits]


# ── F1 · the wrong page is never returned as exact ──────────────────────────────────────────────

def test_lookup_sf_1_1a_returns_exactly_one(ask, corpus):
    """§12.3's first row. Any-order matching would return the decoy page as well (F1).

    `total` is the size of the **set**, so asserting it is 1 asserts more than `len(hits)`: it says
    the index found one page, not that one page fitted in the cap.
    """
    label = corpus.expected["compact_labels"][0]

    response = ask(label["label"])

    assert response.status is Status.OK
    assert response.total == 1
    assert page_ids(response) == [label["page_id"]]


def test_the_token_decoy_page_is_never_returned(ask, corpus):
    """p008 carries `sf`, `1` and `1a`, none of them adjacent — the whole point of a phrase."""
    decoy = corpus.expected["decoy"]

    response = ask(decoy["label"])

    assert decoy["page_id"] not in page_ids(response)


@pytest.mark.parametrize("row", [
    pytest.param(row, id=row["label"]) for row in synthetic.load().expected["one_character_apart"]
])
def test_a_label_one_character_apart_is_not_a_match(ask, row):
    """I3 — a variant may only re-space characters, so `SF 5.5b` can never reach `SF 5.5c`."""
    response = ask(row["label"])

    assert row["not_page_id"] not in page_ids(response)


# ── F3 · never abstain on a label that is printed ───────────────────────────────────────────────

def test_all_eight_compact_labels_found(ask, corpus):
    """Eight printed spellings, eight callers' spellings, one variant bridging each (§12.3, F3).

    Three of the three variants earn their place here: `as given` for the canonical spelling,
    `whitespace removed` for a compact printed callout like `SF121.1)`, and `letter-digit
    boundary` for a code printed with a space inside it like `Q 25`.
    """
    rows = corpus.expected["compact_labels"]
    assert len(rows) == 8

    for row in rows:
        response = ask(row["label"])

        assert response.status is Status.OK, f'{row["label"]} is printed as {row["printed"]}'
        assert page_ids(response) == [row["page_id"]], row["variant"]
        assert response.total == 1


def test_every_variant_kind_is_exercised_by_the_table(corpus):
    """A table that only exercised the identity variant would prove nothing about F3."""
    kinds = {row["variant"] for row in corpus.expected["compact_labels"]}

    assert kinds == {"as given", "whitespace removed", "letter-digit boundary"}


# ── F14 / I2 · a model-invented code is unfindable ──────────────────────────────────────────────

def test_hallucinated_code_never_findable(ask, corpus):
    """I2, F14 — `text` has one writer, so this is structural rather than statistical.

    `K999` is in the claiming page's `content.codes` and in its `vlm_codes`, and nowhere in its
    `text`. The exact surface cannot see it, and no combination of arguments makes it a `hit`.
    """
    fake = corpus.expected["hallucinated"]

    silent = ask(fake["label"])
    disclosed = ask(fake["label"], include_unverified=True)

    assert silent.status is Status.NOT_FOUND
    assert silent.hits == [] and silent.unverified_hits == []
    assert silent.total == 0
    assert disclosed.hits == []
    assert disclosed.status is Status.NOT_FOUND
    assert [hit.page_id for hit in disclosed.unverified_hits] == [fake["page_id"]]
    assert len(disclosed.unverified_hits) == fake["unverified_hits"]
    assert disclosed.unverified_hits[0].verified is False


def test_the_claiming_page_is_findable_by_what_its_text_does_say(ask, corpus):
    """The page is not quarantined — only the claim is. `X7` is printed on it and is findable."""
    fake = corpus.expected["hallucinated"]

    response = ask("X7")

    assert page_ids(response) == [fake["page_id"]]


def test_the_two_lists_are_never_merged(ask, corpus):
    fake = corpus.expected["hallucinated"]

    disclosed = ask(fake["label"], include_unverified=True)

    assert not (set(page_ids(disclosed))
                & {hit.page_id for hit in disclosed.unverified_hits})
    assert all(hit.verified is False for hit in disclosed.unverified_hits)


# ── F4 / §5.7 · unsearchable is not the same as absent ──────────────────────────────────────────

@pytest.mark.parametrize("kind", ["no_text", "untrusted"])
def test_an_unsearchable_scope_is_not_searchable_and_never_not_found(ask, corpus, kind):
    """*"That part doesn't exist"* about a page nobody could read is the injury F4 names."""
    row = corpus.expected[kind]

    scoped = ask(row["label"], scope=row["scope"])
    unscoped = ask(row["label"])

    assert scoped.status.value == row["scoped_status"]
    assert scoped.hits == []
    assert unscoped.status.value == row["unscoped_status"]
    assert unscoped.hits == []


def test_a_phrase_in_an_untrusted_text_layer_is_not_a_verified_hit(ask, corpus):
    """§5.7 — `K404` really is in p010's text. A garbled extraction is not evidence.

    It is still disclosed: the model's claim about the same page comes back through
    `unverified_hits`, which is the honest shape — *"something says K404 is here, and it is not
    the text layer"*.
    """
    row = corpus.expected["untrusted"]

    disclosed = ask(row["label"], include_unverified=True)

    assert disclosed.hits == []
    assert [hit.page_id for hit in disclosed.unverified_hits] == [row["page_id"]]
    assert disclosed.unverified_hits[0].text_trust == "untrusted"


def test_the_unverified_surface_reaches_a_page_with_no_text_layer(ask, corpus):
    """D3 — the only recall there is on a scanned page, which is why it ships at all."""
    row = corpus.expected["no_text"]

    disclosed = ask(row["label"], include_unverified=True)

    assert [hit.page_id for hit in disclosed.unverified_hits] == [row["page_id"]]
    assert disclosed.unverified_hits[0].text_trust == "no_text"


def test_a_shorter_label_can_phrase_match_inside_a_longer_printed_one(ask, corpus):
    """The accepted cost of phrase semantics, asserted so it is a property and not a surprise.

    `SF 1` re-spaces to `sf 1`, which is printed inside `SF 1.1A` on p001, so `lookup` returns
    that page. It is not fuzzy and it is not a fabrication — the characters really are on the page
    — but neither is it the label the caller typed. Telling `SF 1` apart from the beginning of
    `SF 1.1A` requires knowing where a code ends, which is an identifier grammar, and §5.2
    prohibits one. This is also why the §12.4 near-miss generator excludes any candidate the
    corpus prints in **any** spelling: a fabricated code that happens to be a printed phrase is
    not a near miss, and asserting on it would test the corpus instead of the system.
    """
    row = corpus.expected["phrase_prefix"]

    response = ask(row["label"])

    assert response.status.value == row["status"]
    assert page_ids(response) == [row["page_id"]]


# ── §7.1 · weak, capped, and the four absences ──────────────────────────────────────────────────

def test_lookup_3_is_weak_at_every_cap(ask, corpus):
    """§12.3 — `weak: true, needs_scope: true` at ANY cap, because `cap` is not a trust input."""
    expected = corpus.expected["weak"]

    for cap in expected["caps"]:
        response = ask(expected["label"], cap=cap)

        assert response.total == expected["total"]
        assert response.weak is True
        assert response.needs_scope is True
        assert response.capped is (expected["total"] > cap)
        assert len(response.hits) == min(cap, expected["total"])


def test_a_capped_result_is_the_first_pages_of_the_set(ask, corpus):
    """§16 — deterministic: same query, same rows, same order, over the real index."""
    expected = corpus.expected["weak"]

    five = ask(expected["label"], cap=5)
    everything = ask(expected["label"], cap=expected["total"])

    assert [hit.page_no for hit in five.hits] == [hit.page_no for hit in everything.hits][:5]
    assert five.hits == ask(expected["label"], cap=5).hits


def test_a_single_hit_is_not_weak(ask, corpus):
    response = ask(corpus.expected["compact_labels"][0]["label"])

    assert response.weak is False
    assert response.needs_scope is False
    assert response.capped is False


def test_a_not_found_a_different_move_could_answer_says_so(ask, corpus):
    """§12.3 — `lookup("alarm 152")` → `not_found` + `next.suggest: ["skim_pages"]`."""
    row = corpus.expected["suggest"]

    response = ask(row["label"])

    assert response.status.value == row["status"]
    assert response.next is not None
    assert response.next.suggest == row["suggest"]


def test_a_not_found_nothing_could_answer_suggests_nothing(ask, corpus):
    """An affordance offered on every abstention would mean nothing on any of them."""
    response = ask(corpus.expected["hallucinated"]["label"])

    assert response.status is Status.NOT_FOUND
    assert response.next is None


def test_the_compact_spelling_of_a_spaced_label_abstains_with_an_affordance(ask, corpus):
    """§5.6's variant rule is asymmetric by construction — recorded, and honest (R1).

    `variants("SF1.1A")` is `SF1.1A` and `SF 1.1 A`; it cannot produce `SF 1.1A`, because
    re-spacing a bare label spaces *every* letter-digit boundary and never just one. So a caller
    typing the compact form of a spaced printed label abstains — and abstains **with a next
    move**, never with a wrong page.
    """
    row = corpus.expected["asymmetric_variant"]

    response = ask(row["label"])

    assert response.status.value == row["status"]
    assert response.hits == []
    assert response.next is not None and response.next.suggest == row["suggest"]


def test_an_empty_scope_is_out_of_scope(ask, corpus):
    row = corpus.expected["out_of_scope"]

    response = ask(row["label"], scope=row["scope"])

    assert response.status.value == row["status"]
    assert response.scope_stats.pages == 0


def test_no_absence_is_ever_an_empty_ok(ask, corpus):
    """I5 — four typed absences, and the fifth possibility does not exist."""
    for label in ("K999", "SF 9.9", "K404", "alarm 152", "SF 7.7A", "SF1.1A"):
        response = ask(label)

        assert response.hits == []
        assert response.status is not Status.OK
        assert response.status.value in ("not_found", "not_searchable", "out_of_scope",
                                         "found_only_in_superseded")


# ── I7 · only a current, published page can answer ──────────────────────────────────────────────

def test_a_superseded_revision_cannot_answer(ask, corpus):
    """`is_current` is injected server-side, so the 0.9 page is in the collection and mute.

    It is **kept**, not deleted: retirement is scoped to the same `(doc_id, revision)` (§6.7),
    because a blanket delete would satisfy F12 by destroying the evidence F9 needs at M8.
    """
    for row in corpus.expected["superseded"]:
        response = ask(row["label"])

        assert len(response.hits) == row["hits"]
        if row["hits"]:
            assert page_ids(response) == [row["page_id"]]


def test_the_superseded_page_is_still_in_the_collection(qdrant, seeded, corpus):
    """Proof that the previous assertion is about the filter and not about a missing point."""
    superseded = [record for record in corpus.records() if not record.is_current]

    stored = qdrant.retrieve(seeded, ids=[ids.point_id(record.page_id)
                                          for record in superseded], with_payload=True)

    assert len(stored) == len(superseded) == 1
    assert stored[0].payload["is_current"] is False
    assert "SF 7.7A" in stored[0].payload["text"]


def test_a_caller_cannot_ask_for_a_non_current_page(ask, corpus):
    """An explicit `is_current: False` is overridden and the override is echoed back."""
    response = ask("SF 7.7A", scope={"is_current": False})

    assert response.effective_scope["is_current"] is True
    assert response.hits == []


# ── I6 / F10 · nothing is filtered off-index ────────────────────────────────────────────────────

def test_unknown_scope_key_returns_typed_400(ask):
    """F10's test row, at the tool boundary: a typed 400 naming the keys, never a scan.

    `content.codes` is a real field on every page and Qdrant would happily filter on it — just
    unindexed, skipping the filterable-HNSW path and returning a smaller answer that looks like a
    complete one. That is the whole of F10, which is why this is a refusal and not a slow path.
    """
    with pytest.raises(ToolError) as refusal:
        ask("K 158", scope={"content.codes": "K158"})

    assert refusal.value.code == "filter_unknown_key"
    assert refusal.value.http_status == 400
    assert refusal.value.details["keys"] == ["content.codes"]


def test_the_core_gate_still_raises_the_domain_error(ask):
    """The gate is `core/`'s and the translation is `serve/`'s — one check, not two."""
    with pytest.raises(UnknownScopeKey):
        exact_filter("K 158", {"content.codes": "K158"})


@pytest.mark.parametrize("scope", [
    {"page_kind": "table"}, {"section_id": ["SYN-M1@1.0#s001"]}, {"has_text": True},
    {"lang": "en"}, {"page_no": 1}, {"doc_type": "safety_function_list"},
    {"subjects": "cell 3"}, {"tags": "synthetic"}, {"revision": "1.0"},
    {"series_id": ["SYN-M1#s:safety-function-list"]}, {"text_trust": "ok"},
    {"run_id": synthetic.SEED_RUN_ID},
])
def test_every_indexed_scope_key_filters_for_real(ask, scope):
    """I6 — the keys `INDEXED` declares are the keys the live collection can actually filter on.

    An unindexed field does not fail in Qdrant, it runs a scan and skips the filterable-HNSW path,
    so *"the filter applied"* has to be asserted rather than assumed (F10).
    """
    response = ask("K 158", scope=scope)

    assert response.effective_scope == {**scope, "is_current": True}
    assert response.scope_stats.pages > 0


def test_a_cap_below_one_is_a_typed_refusal(ask):
    with pytest.raises(ToolError) as refusal:
        ask("3", cap=0)

    assert refusal.value.code == "cap_out_of_range"


# ── the envelope's own facts ────────────────────────────────────────────────────────────────────

def test_scope_stats_describe_the_real_collection(ask, corpus):
    expected = corpus.expected["corpus"]

    stats = ask("K 158").scope_stats

    assert stats.pages == expected["pages"]
    assert stats.pages_no_text == expected["pages_no_text"]
    assert [doc.doc_id for doc in stats.docs] == [expected["doc_id"]]
    assert stats.docs[0].searchable_ratio == pytest.approx(expected["searchable_ratio"])


def test_a_scoped_lookup_reports_the_scope_it_searched(ask):
    response = ask("K 158", scope={"section_id": ["SYN-M1@1.0#s001"]})

    assert response.scope_stats.pages == 8
    assert response.scope_stats.docs[0].searchable_ratio == pytest.approx(7 / 8)


def test_every_hit_carries_an_image_reference_and_no_hit_carries_bytes(ask, corpus):
    """§7.1, D12, P2 — enough to choose, never enough to answer.

    The URL is the percent-encoded form §7.2.5's example shows (U018): the `#` of a `page_id` is a
    fragment delimiter to every HTTP client, so the unencoded form this used to assert named the
    document and not the page. `tests/api/test_page_image.py` dereferences one of these URLs for
    real; here the shape is what matters, and that it names *this* row's page.
    """
    response = ask(corpus.expected["weak"]["label"], cap=26)

    assert response.hits
    for hit in response.hits:
        assert hit.image is not None
        assert hit.image.url == f"/pages/{quote(hit.page_id, safe='@')}/image?dpi=150"
        assert "#" not in hit.image.url and "%23" in hit.image.url
        assert hit.image.thumb_url.endswith("dpi=72")
    assert "bytes_b64" not in response.model_dump_json()


def test_the_response_carries_no_similarity_value(ask):
    """§7.6 — and a `lookup` has no ordinal either: it is a set, not a ranking."""
    body = ask("K 158").model_dump()

    assert "score" not in body
    assert all("score" not in hit and "rank" not in hit for hit in body["hits"])


def test_provenance_names_the_release_that_answered(ask):
    response = ask("K 158")

    assert response.provenance.release_id == "test"
    assert response.provenance.schema_version == 1


# ── I1 · one page, one point ────────────────────────────────────────────────────────────────────

def test_reseeding_the_corpus_does_not_double_anything(qdrant, seeded, corpus, ask):
    """I1, F12 — `point_id = uuid5(page_id)`, so a second seed overwrites in place."""
    before = ask("K 158")

    synthetic.seed(qdrant, seeded, corpus.records(release_id="test"), dim=EMBED_DIM,
                   recreate=False)
    after = ask("K 158")

    assert qdrant.count(seeded, exact=True).count == len(corpus.records())
    assert after.total == before.total == 1
    assert after.scope_stats.pages == before.scope_stats.pages


# ── §6.8 · the inventory, built from the seeded pages ───────────────────────────────────────────

def test_the_observed_token_inventory_matches_the_indexed_text(qdrant, seeded, corpus):
    """§6.8 — built from the same `text` the index answered from, and from nothing else.

    The **searchable** pages only (§5.7): a page `lookup` cannot search and `verify` cannot check
    must not volunteer codes either, or a garbled extraction's debris comes back beside an
    `absent` verdict as a "different part".

    Read back out of Qdrant rather than off the records, because the inventory that backs
    `present_instead` in production is built from what was **indexed**: if the payload and the
    record ever disagreed, the disclosure would describe a page the caller cannot search.
    """
    expected = corpus.expected["observed_tokens"]
    payloads = [point.payload for point in
                qdrant.scroll(collection_name=seeded, limit=1000, with_payload=True,
                              with_vectors=False)[0]
                if point.payload and point.payload.get("is_current")
                and is_searchable(point.payload)]

    inventory = from_records(payloads)[expected["doc_id"]]
    every_word = {word for payload in payloads for word in token_set(payload["text"])}

    assert len(inventory) == expected["count"]
    assert set(inventory.tokens) == {word for word in every_word if is_code_like(word)}
    for token in expected["includes"]:
        assert token in inventory
    for token in expected["excludes"]:
        assert token not in inventory


def test_a_present_instead_candidate_is_never_a_lookup_hit(ask, qdrant, seeded, corpus):
    """F16 — the disclosure and the match are different surfaces, and this is the seam.

    `K78` is what a `K73` claim would disclose. Looking `K73` up returns nothing at all: the
    inventory cannot promote a near miss into a hit, because `lookup` cannot reach the inventory.
    """
    payloads = [point.payload for point in
                qdrant.scroll(collection_name=seeded, limit=1000, with_payload=True,
                              with_vectors=False)[0]
                if point.payload and point.payload.get("is_current")
                and is_searchable(point.payload)]
    inventory = from_records(payloads)[corpus.doc_id]

    near_miss = ask("K 73")

    assert near_miss.hits == []
    assert inventory.starting_with("k7") == ("k78",)
    assert ask("K 78").total == 1
