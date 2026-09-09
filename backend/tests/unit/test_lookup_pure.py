"""L0 — `lookup` as a pure function (Spec §7.2.2, §7.1, I2, I5, I6, I7).

`lookup` takes a client and a collection and holds nothing else, so everything about its
*behaviour* can be asserted without Docker: which absence it chooses, what `cap` may and may not
move, that the two surfaces are never merged, and that `is_current` is injected whatever the caller
says. The store is replaced by :class:`FakeStore`, which understands exactly the filter shapes this
module builds and nothing else.

**Why a fake is honest here.** The one thing a fake could get wrong is what a `MatchPhrase` means,
and that is already pinned: `tok()` mirrors Qdrant's WORD tokenizer (§5.6) and
`tests/api/test_tokenizer_differential.py` proves it against a live `qdrant/qdrant:v1.19.0`. So
this evaluator implements a phrase as *"`tok(phrase)` appears contiguously in `tok(text)`"* — the
behaviour that test measured — and `tests/api/test_acceptance_synthetic.py` re-runs the same
acceptance table against the real index. If the two ever disagree, one of the two suites goes red,
which is the point of having both.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pytest
from qdrant_client.http import models as qm

from vsir.core.exact import UnknownScopeKey
from vsir.core.record import PageRecord
from vsir.core.tok import tok
from vsir.eval import synthetic
from vsir.serve.caps import ToolError
from vsir.serve.envelope import ImageRef, LookupHit, Provenance, Status
from vsir.serve.tools import lookup as lookup_module
from vsir.serve.tools.lookup import (
    UNSEARCHABLE_TRUST,
    effective_scope,
    hit_from_payload,
    image_ref,
    label_variants,
    lookup,
    searchable,
)

PACKAGE = Path(__file__).resolve().parents[2] / "vsir"
PROVENANCE = Provenance(run_id="R", release_id="test-release")
COLLECTION = "fake_pages"


# ── the fake store ──────────────────────────────────────────────────────────────────────────────

def _phrase_matches(phrase: str, text: str) -> bool:
    """A phrase is its tokens, contiguous and in order — what §5.5's `phrase_matching` buys."""
    needle, haystack = tok(phrase), tok(text)
    if not needle:
        return False
    return any(haystack[at:at + len(needle)] == needle
               for at in range(len(haystack) - len(needle) + 1))


def _condition_matches(payload: dict, condition: Any) -> bool:
    if isinstance(condition, qm.Filter):
        return _filter_matches(payload, condition)
    value = payload.get(condition.key)
    match = condition.match
    if isinstance(match, qm.MatchValue):
        return value == match.value
    if isinstance(match, qm.MatchAny):
        members = value if isinstance(value, list) else [value]
        return any(member in match.any for member in members)
    if isinstance(match, qm.MatchPhrase):
        return _phrase_matches(match.phrase, str(value or ""))
    raise AssertionError(f"the fake store does not implement {type(match).__name__} — and "
                         f"`lookup` must not be using it (I3)")


def _filter_matches(payload: dict, query: qm.Filter | None) -> bool:
    """Qdrant's rule: the three clauses are ANDed, and `should` means at least one."""
    if query is None:
        return True
    if query.must and not all(_condition_matches(payload, c) for c in query.must):
        return False
    if query.must_not and any(_condition_matches(payload, c) for c in query.must_not):
        return False
    if query.should and not any(_condition_matches(payload, c) for c in query.should):
        return False
    return True


@dataclass
class _Count:
    count: int


@dataclass
class _Point:
    id: str
    payload: dict


@dataclass
class _FacetHit:
    value: Any
    count: int


@dataclass
class _Facet:
    hits: list[_FacetHit]


class FakeStore:
    """The three read operations `lookup` uses, over a list of payloads in memory."""

    def __init__(self, payloads: Iterable[dict]) -> None:
        self.payloads = list(payloads)
        self.calls = 0

    def _matching(self, query: qm.Filter | None) -> list[dict]:
        self.calls += 1
        return [payload for payload in self.payloads if _filter_matches(payload, query)]

    def count(self, _collection: str, count_filter: qm.Filter | None = None,
              exact: bool = False) -> _Count:
        assert exact is True, "`total` and `weak` are contracts, not estimates (§7.1)"
        return _Count(count=len(self._matching(count_filter)))

    def scroll(self, collection_name: str, scroll_filter: qm.Filter | None = None,
               limit: int = 10, with_payload: bool = True, with_vectors: bool = False,
               order_by: str | None = None) -> tuple[list[_Point], None]:
        assert with_vectors is False, "a search never loads a vector it does not use"
        found = self._matching(scroll_filter)
        if order_by:
            found.sort(key=lambda payload: payload.get(order_by) or 0)
        return [_Point(id=str(index), payload=payload)
                for index, payload in enumerate(found[:limit])], None

    def facet(self, _collection: str, key: str, facet_filter: qm.Filter | None = None,
              limit: int = 10, exact: bool = False) -> _Facet:
        counts: dict[Any, int] = {}
        for payload in self._matching(facet_filter):
            counts[payload.get(key)] = counts.get(payload.get(key), 0) + 1
        ordered = sorted(counts.items(), key=lambda item: -item[1])[:limit]
        return _Facet(hits=[_FacetHit(value=value, count=count) for value, count in ordered])


@pytest.fixture(scope="module")
def corpus() -> synthetic.Corpus:
    return synthetic.load()


@pytest.fixture(scope="module")
def store(corpus: synthetic.Corpus) -> FakeStore:
    return FakeStore(record.to_payload() for record in corpus.records(release_id="test-release"))


def ask(store: FakeStore, label: str, **kwargs: Any):
    return lookup(store, COLLECTION, label, provenance=PROVENANCE, **kwargs)


def page(page_no: int, **overrides: Any) -> dict:
    """One minimal payload, for the edge cases the corpus deliberately does not contain."""
    record = PageRecord(doc_id="D", revision="1", is_current=True, page_no=page_no,
                        has_text=True, text_trust="ok", text="",
                        provenance={"page_id": f"D@1#p{page_no:03d}"})
    return {**record.to_payload(), **overrides}


# ── the injection, the scope, and the two filters ───────────────────────────────────────────────

def test_is_current_is_injected_server_side():
    """I7 — a run that has not passed its gates cannot answer, whatever the caller asked for."""
    assert effective_scope(None) == {"is_current": True}
    assert effective_scope({"doc_id": "D"}) == {"doc_id": "D", "is_current": True}
    assert effective_scope({"is_current": False}) == {"is_current": True}


def test_the_searchable_filter_excludes_both_unsearchable_trust_levels():
    """§5.7 — `no_text` has nothing to match and `untrusted` is not evidence."""
    query = searchable(qm.Filter(must=[]))

    assert len(query.must_not) == 1
    assert query.must_not[0].key == "text_trust"
    assert sorted(query.must_not[0].match.any) == sorted(UNSEARCHABLE_TRUST)


def test_an_unknown_scope_key_is_refused_before_it_reaches_the_store(store):
    """I6, F10 — a typed refusal, never an unindexed scan, and never a narrower answer."""
    with pytest.raises(UnknownScopeKey) as refusal:
        ask(store, "K158", scope={"content.codes": "K158"})

    assert refusal.value.keys == ["content.codes"]


def test_label_variants_is_the_one_variant_function():
    assert list(label_variants("SF 1.1A")) == ["SF 1.1A", "SF1.1A", "SF 1.1 A"]


# ── the hit ─────────────────────────────────────────────────────────────────────────────────────

def test_a_hit_carries_an_image_reference_and_never_bytes():
    """§7.1, D12, P2 — ~60 bytes, and it renders nothing until something dereferences it."""
    reference = image_ref("D@1#p007")

    assert reference.url == "/pages/D@1#p007/image?dpi=150"
    assert reference.thumb_url == "/pages/D@1#p007/image?dpi=72"
    assert reference.dpi == 150
    assert (reference.width, reference.height) == (0, 0)
    assert not [field for field in ImageRef.model_fields if "bytes" in field]
    assert not [field for field in LookupHit.model_fields if "bytes" in field]


def test_verified_describes_the_surface_and_nothing_else():
    """§7.1 — `text` is true, `vlm_codes` is false. Not a claim about the page or the model."""
    payload = page(3, text_trust="degraded", content={"printed_page_no": "Page 3 of 9"},
                   page_kind="schematic")

    from_text = hit_from_payload(payload, verified=True)
    from_codes = hit_from_payload(payload, verified=False)

    assert (from_text.verified, from_codes.verified) == (True, False)
    assert from_text.page_id == "D@1#p003"
    assert from_text.page_no == 3
    assert from_text.printed_page_no == "Page 3 of 9"
    assert from_text.page_kind == "schematic"
    assert from_text.text_trust == "degraded"
    assert from_text.next is None       # P4's affordances need the doc's page count (U017)


# ── the status ladder: four absences, and never an empty `ok` (I5) ──────────────────────────────

def test_a_hit_is_ok(store):
    response = ask(store, "SF 1.1A")

    assert response.status is Status.OK
    assert [hit.page_id for hit in response.hits] == ["SYN-M1@1.0#p001"]


def test_an_empty_scope_is_out_of_scope(store):
    response = ask(store, "SF 1.1A", scope={"doc_id": "NO-SUCH-DOC"})

    assert response.status is Status.OUT_OF_SCOPE
    assert response.scope_stats.pages == 0


def test_a_scope_with_no_searchable_page_is_not_searchable():
    """F4 — *"that part doesn't exist"* about a page nobody could read is the injury."""
    store = FakeStore([page(1, has_text=False, text_trust="no_text"),
                       page(2, text_trust="untrusted", text="K404 on rail 3")])

    response = ask(store, "K404")

    assert response.status is Status.NOT_SEARCHABLE
    assert response.hits == []
    assert response.scope_stats.pages == 2
    assert response.scope_stats.pages_no_text == 1


def test_a_searchable_scope_with_no_match_is_not_found(store):
    response = ask(store, "K999")

    assert response.status is Status.NOT_FOUND
    assert response.hits == []


def test_out_of_scope_wins_over_not_searchable_on_an_empty_scope():
    """Asked-and-unreadable and never-asked are different instructions to the caller."""
    store = FakeStore([page(1, has_text=False, text_trust="no_text")])

    assert ask(store, "K404", scope={"doc_id": "OTHER"}).status is Status.OUT_OF_SCOPE
    assert ask(store, "K404").status is Status.NOT_SEARCHABLE


def test_an_empty_result_can_never_be_ok(store):
    """I5's validator, reached through the tool rather than the model."""
    for label in ("K999", "SF 9.9", "alarm 152"):
        assert ask(store, label).status is not Status.OK


# ── `next.suggest`: a `not_found` a different move could answer says so ─────────────────────────

def test_a_not_found_whose_words_occur_suggests_another_move(store):
    """§7.1, §12.3 — `alarm` is on p024 and `152` on p026; the phrase is nowhere."""
    response = ask(store, "alarm 152")

    assert response.status is Status.NOT_FOUND
    assert response.next is not None
    assert response.next.suggest == ["skim_pages"]


def test_a_not_found_whose_words_occur_nowhere_suggests_nothing(store):
    """A hallucinated code has no affordance to offer, and inventing one would be noise."""
    response = ask(store, "K999")

    assert response.status is Status.NOT_FOUND
    assert response.next is None


def test_a_single_character_word_does_not_earn_a_suggestion(store):
    """`min_token_len=1` is for the index (§5.5), not for deciding what to suggest.

    ``Z 1`` re-spaces to ``Z1``; the corpus is full of the token ``1`` and has no ``z`` and no
    ``z1``. A suggestion earned by one digit occurring somewhere would fire on almost every
    `not_found` and mean nothing.
    """
    response = ask(store, "Z 1")

    assert response.status is Status.NOT_FOUND
    assert response.next is None


def test_a_word_that_is_itself_a_variant_is_not_probed_twice(store):
    """`total == 0` over the OR of the variants already answers a one-word variant."""
    before = store.calls
    ask(store, "K999")

    assert store.calls - before <= 8, "one probe (`999`), not one per spelling"


def test_the_probe_count_is_bounded(store):
    """A pathological 'label' cannot turn one refusal into hundreds of counts."""
    before = store.calls
    response = ask(store, " ".join(str(number) for number in range(100, 160)))

    assert response.status is Status.NOT_FOUND
    assert store.calls - before <= 8 + lookup_module.SUGGEST_WORD_PROBES


def test_the_compact_spelling_of_a_spaced_label_abstains_with_an_affordance(store):
    """§5.6 — `variants()` re-spaces, and it cannot un-space *one* boundary out of two.

    p001 prints `SF 1.1A`. From `SF1.1A` the three spellings are `SF1.1A` ([sf1, 1a]) and
    `SF 1.1 A` ([sf, 1, 1, a]) — neither is [sf, 1, 1a]. That is a recall gap by construction
    (R1), and what makes it survivable is that it degrades to an honest abstention carrying a next
    move, never to a wrong page.
    """
    response = ask(store, "SF1.1A")

    assert response.status is Status.NOT_FOUND
    assert response.hits == []
    assert response.next is not None and response.next.suggest == ["skim_pages"]


# ── `cap`, `total`, `capped`, `weak` (§7.1) ─────────────────────────────────────────────────────

@pytest.mark.parametrize("cap", [1, 5, 20, 200])
def test_cap_bounds_the_page_of_the_set_and_never_the_signal(store, corpus, cap):
    """A trust signal a client could flip with `cap=200` would be worse than no signal."""
    expected = corpus.expected["weak"]

    response = ask(store, expected["label"], cap=cap)

    assert response.total == expected["total"]
    assert len(response.hits) == min(cap, expected["total"])
    assert response.capped is (expected["total"] > cap)
    assert response.weak is True
    assert response.needs_scope is True


def test_weak_is_the_server_constant_against_the_scope_size(store):
    """`weak = total > max(WEAK_ABS, 0.25 * pages)` — 26 of 30 is weak, 1 of 30 is not."""
    assert ask(store, "3").weak is True
    assert ask(store, "SF 1.1A").weak is False


def test_a_capped_result_is_the_first_pages_of_the_set_in_reading_order(store):
    """Deterministic (§16): the same query returns the same rows in the same order."""
    first_five = ask(store, "3", cap=5)
    everything = ask(store, "3", cap=200)

    page_numbers = [hit.page_no for hit in first_five.hits]
    assert page_numbers == sorted(page_numbers)
    assert page_numbers == [hit.page_no for hit in everything.hits][:5]


@pytest.mark.parametrize("cap", [0, -1])
def test_a_cap_below_one_is_a_typed_refusal(store, cap):
    """The alternatives are all lies: `ok` with no hits is impossible (I5), and an absence
    reported beside ``total: 26`` says *"nothing is there"* about a set whose size it is
    simultaneously reporting."""
    with pytest.raises(ToolError) as refusal:
        ask(store, "3", cap=cap)

    assert refusal.value.code == "cap_out_of_range"
    assert refusal.value.http_status == 400


# ── the two surfaces are never merged (I2, D3) ──────────────────────────────────────────────────

def test_a_hallucinated_code_is_only_ever_an_unverified_hit(store, corpus):
    """I2, F14 — `ingest/probe.py` is the only writer of `text`, so this is structural."""
    fake = corpus.expected["hallucinated"]

    silent = ask(store, fake["label"])
    disclosed = ask(store, fake["label"], include_unverified=True)

    assert silent.status is Status.NOT_FOUND and silent.unverified_hits == []
    assert disclosed.hits == []
    assert [hit.page_id for hit in disclosed.unverified_hits] == [fake["page_id"]]
    assert disclosed.unverified_hits[0].verified is False
    assert disclosed.status is Status.NOT_FOUND, "the verified surface found nothing, and says so"


def test_the_unverified_surface_reaches_a_page_with_no_text_layer(store, corpus):
    """D3 — `vlm_codes` is the only recall there is on a scanned page, so no trust filter."""
    row = corpus.expected["no_text"]

    disclosed = ask(store, row["label"], include_unverified=True)

    assert [hit.page_id for hit in disclosed.unverified_hits] == [row["page_id"]]
    assert disclosed.unverified_hits[0].text_trust == "no_text"


def test_total_counts_the_verified_surface_only(store, corpus):
    """`total` is the size of the exact set. An opt-in disclosure does not inflate it."""
    fake = corpus.expected["hallucinated"]

    assert ask(store, fake["label"], include_unverified=True).total == 0


# ── the envelope's stateless half (F8, C11) ─────────────────────────────────────────────────────

def test_effective_scope_is_echoed_back(store):
    response = ask(store, "SF 1.1A", scope={"page_kind": "table"})

    assert response.effective_scope == {"page_kind": "table", "is_current": True}


def test_scope_stats_report_what_was_searched(store, corpus):
    expected = corpus.expected["corpus"]

    stats = ask(store, "SF 1.1A").scope_stats

    assert stats.pages == expected["pages"]
    assert stats.pages_no_text == expected["pages_no_text"]
    assert [doc.doc_id for doc in stats.docs] == [expected["doc_id"]]
    assert stats.docs[0].searchable_ratio == pytest.approx(expected["searchable_ratio"])


def test_provenance_and_budget_come_from_the_caller(store):
    response = lookup(store, COLLECTION, "SF 1.1A", provenance=PROVENANCE, reads_remaining=3)

    assert response.provenance.release_id == "test-release"
    assert response.reads_remaining == 3


# ── the module boundary that keeps `present_instead` out of `hits` (§6.8, F16) ──────────────────

def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_lookup_cannot_import_the_observed_token_inventory():
    """§6.8 — display-only, *"enforced by module boundary"*. This is that enforcement.

    The inventory is built with a heuristic (a token containing a digit) that is fine for a
    disclosure beside an `absent` verdict and catastrophic in a match. A `lookup` that could reach
    it could return a near-miss code as the answer (F16), so the guarantee is that it cannot.
    """
    imported = _imports_of(PACKAGE / "serve" / "tools" / "lookup.py")

    assert not [name for name in imported if "observed_tokens" in name]
    assert not [name for name in imported if "present_instead" in name or "nearmiss" in name]


def test_lookup_matches_only_with_phrases():
    """I3 — one exact-match code path. A `MatchText` here would be a wrong answer, not a slow one."""
    source = (PACKAGE / "serve" / "tools" / "lookup.py").read_text(encoding="utf-8")

    assert "MatchText" not in source
    assert "exact_filter" in source


def test_the_fake_store_refuses_a_match_type_lookup_must_not_use(store):
    """The fake is only evidence if it would notice: an unsupported match raises, never passes."""
    with pytest.raises(AssertionError):
        _condition_matches({"text": "K158"},
                           qm.FieldCondition(key="text", match=qm.MatchText(text="K158")))


def test_the_module_exports_no_field_named_like_a_score():
    """§7.6 — no similarity value is computed, stored or returned by this tool."""
    response_fields = set(LookupHit.model_fields)

    assert "score" not in response_fields
    assert "fused" not in response_fields
    assert "rank" not in response_fields, "a lookup is a set, not a ranking (§7.2.2)"


def test_the_tool_module_declares_no_module_level_state():
    """§15 Factor VI — nothing correctness-bearing survives between two calls."""
    tree = ast.parse((PACKAGE / "serve" / "tools" / "lookup.py").read_text(encoding="utf-8"))
    assignments = [node for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))]

    for node in assignments:
        assert isinstance(node.value, (ast.Constant, ast.Tuple, ast.Call)), \
            f"module-level mutable state on line {node.lineno}"
    assert not [node for node in assignments
                if isinstance(node.value, (ast.Dict, ast.List, ast.Set))]


def test_lookup_is_indifferent_to_being_called_twice(store, corpus):
    """Statelessness, asserted rather than assumed: the same call returns the same envelope."""
    first = ask(store, "SF 1.1A", include_unverified=True)
    second = ask(store, "SF 1.1A", include_unverified=True)

    assert first.model_dump() == second.model_dump()
