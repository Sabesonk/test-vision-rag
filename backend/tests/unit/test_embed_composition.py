"""L0/L1 — the dense composition (Spec §5.3, D4) and the two backends that turn it into a vector.

Three of these tests exist because of an **API fact**, not a design choice, and each one is a
silent failure if it regresses: `task_type` is rejected by this model, a bare list in ``contents``
returns one aggregated embedding for the whole batch, and a wrong ``output_dimensionality`` is a
different space rather than an error. The transport is injected so all three are decidable without
a network and without a credential (§12.2: L0-L3 never call Gemini).

The rest are about the composition being §5.3's — the order of the parts, one summary Part per
language (D5, D8), and the raster last at ``dpi_index``. That order is a spec clause, and the
thing the previous implementation got wrong here was not the model call but what it packed.
"""
from __future__ import annotations

import contextlib
import time

from types import SimpleNamespace
from typing import Any, Sequence

import pytest

from vsir.config import DPI_ANSWER, DPI_INDEX, EMBED_MAX_EDGE_PX, load_config
from vsir.core.record import PageContent, PageRecord, Provenance, StoredSection, Summary
from vsir.ingest import embed as embed_module
from vsir.ingest import render
from vsir.ingest.embed import (
    Composition,
    EmbedCallFailed,
    EmbedDimMismatch,
    EmbedError,
    EmbedUnavailable,
    GeminiEmbedder,
    StubEmbedder,
    compose,
    embed_document,
    embedder,
)

from conftest import SYNTHETIC_ENV

DIM = 8


def raster(page_no: int = 1, *, dpi: int = DPI_INDEX, fill: int = 200) -> render.Raster:
    """A tiny real PNG. `prepare_image` opens it, so a hand-made byte string will not do."""
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (12, 16), (fill, fill, fill)).save(buffer, format="PNG")
    return render.Raster(page_no=page_no, dpi=dpi, width=12, height=16, png=buffer.getvalue())


def record(*, page_no: int = 1, text: str = "", summaries: Sequence[tuple[str, str]] = (),
           topics: Sequence[str] = (), codes: Sequence[str] = (),
           sections: Sequence[str] = ()) -> PageRecord:
    page_id = f"DOC@1.0#p{page_no:03d}"
    return PageRecord(
        doc_id="DOC", revision="1.0", page_no=page_no, text=text,
        content=PageContent(
            summaries=[Summary(lang=lang, text=body) for lang, body in summaries],
            topics=list(topics), codes=list(codes),
            sections=[StoredSection(section_id=f"DOC@1.0#s{n:03d}", title=title)
                      for n, title in enumerate(sections, start=1)],
        ),
        provenance=Provenance(page_id=page_id),
    )


class Recorder:
    """A transport that records every call and returns the embeddings it is told to."""

    def __init__(self, *, dim: int = DIM, returns: int | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.dim = dim
        self.returns = returns

    def __call__(self, **call: Any) -> Any:
        self.calls.append(call)
        wanted = self.returns if self.returns is not None else len(call["contents"])
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.5] * self.dim)
                                           for _ in range(wanted)])

    @property
    def contents(self) -> list[Any]:
        return [content for call in self.calls for content in call["contents"]]


def gemini(**overrides: Any) -> GeminiEmbedder:
    transport = overrides.pop("transport", None) or Recorder()
    return GeminiEmbedder(model="gemini-embedding-2", dim=overrides.pop("dim", DIM),
                          credential="not-a-real-credential", transport=transport,
                          sleep=lambda _seconds: None, **overrides)


# ── the composition is §5.3's, part for part ─────────────────────────────────────────────────────

def test_the_parts_are_section_5_3_s_order():
    """doc_title · section_titles · summaries[] · topics · codes · text[:N] · the raster."""
    composed = compose(
        record(text="K158 emergency stop wiring", summaries=[("en", "The E-stop chain.")],
               topics=["emergency stop"], codes=["K158", "SF 1.1A"],
               sections=["Emergency stop circuits"]),
        raster(), doc_title="C24 SAFETY COMPONENT CIRCUIT LIST", text_chars=2000)

    assert composed.parts == (
        "C24 SAFETY COMPONENT CIRCUIT LIST",
        "Emergency stop circuits",
        "The E-stop chain.",
        "emergency stop",
        "K158 SF 1.1A",
        "K158 emergency stop wiring",
    )


def test_every_text_part_is_its_own_part_and_never_a_concatenated_blob():
    """D4 — the model fuses structured parts; a pre-joined string is what D8 rules out."""
    composed = compose(record(text="body", summaries=[("en", "summary")], topics=["topic"]),
                       raster(), doc_title="title", text_chars=2000)
    parts = composed.contents().parts

    assert [part.text for part in parts[:-1]] == list(composed.parts)
    assert len(parts) == len(composed.parts) + 1


def test_a_two_language_page_gets_two_separate_summary_parts():
    """D5/D8 — one blended IT/EN summary poisons the embedding, so it is never built."""
    composed = compose(
        record(summaries=[("it", "Catena di arresto di emergenza."),
                          ("en", "The emergency stop chain.")]),
        raster(), text_chars=2000)

    assert composed.summary_parts == 2
    assert composed.parts == ("Catena di arresto di emergenza.", "The emergency stop chain.")
    assert not any("Catena" in part and "emergency" in part for part in composed.parts)


def test_the_last_part_is_the_page_raster_at_dpi_index():
    composed = compose(record(text="body"), raster(), text_chars=2000)
    last = composed.contents().parts[-1]

    assert composed.dpi == DPI_INDEX == 150
    assert last.text is None
    assert last.inline_data.mime_type == "image/png"
    assert last.inline_data.data == composed.image


def test_the_dpi_answer_raster_is_refused_rather_than_embedded():
    """SA-12 — two dpis, three uses. Mixing them puts two rasters' vectors in one collection."""
    with pytest.raises(EmbedError) as refusal:
        compose(record(), raster(dpi=DPI_ANSWER), text_chars=2000)

    assert refusal.value.details["expected"] == DPI_INDEX


def test_a_raster_of_the_wrong_page_is_refused():
    """A page embedded beside its neighbour's pixels is the injury I4 exists to prevent."""
    with pytest.raises(EmbedError):
        compose(record(page_no=4), raster(page_no=5), text_chars=2000)


def test_an_absent_field_contributes_no_part_at_all():
    """An empty Part is a token spent on nothing, and `impl` filters them out too."""
    composed = compose(record(text="only the text"), raster(), text_chars=2000)

    assert composed.parts == ("only the text",)
    assert composed.summary_parts == 0


def test_the_printed_page_label_is_not_a_part():
    """§5.3's order does not carry it, and `resolve` answers a printed label from a facet.

    `impl` prefixes `page ` onto a label that already reads `Page 1 of 55` and embeds the result
    on every page of the corpus (guide 08 §5.4). Dropping the part drops the defect with it.
    """
    page = record(text="body")
    page.content.printed_page_no = "Page 1 of 55"

    assert compose(page, raster(), text_chars=2000).parts == ("body",)


def test_a_repeated_section_title_is_said_once():
    composed = compose(record(sections=["Emergency stop circuits", "Emergency stop circuits"]),
                       raster(), text_chars=2000)

    assert composed.parts == ("Emergency stop circuits",)


def test_the_page_text_cap_is_applied_and_the_drop_is_counted():
    """Register defect: `impl` cuts `text[:4000]` and counts nothing, so nothing tells you when."""
    composed = compose(record(text="x" * 2500), raster(), text_chars=2000)

    assert composed.text_chars == 2000
    assert composed.text_dropped == 500
    assert composed.parts[-1] == "x" * 2000


def test_a_page_within_the_cap_drops_nothing():
    composed = compose(record(text="x" * 12), raster(), text_chars=2000)

    assert (composed.text_chars, composed.text_dropped) == (12, 0)


def test_the_raster_long_edge_is_bounded_before_the_call():
    """The image part is billed by area, so the bound is what keeps a run's cost predictable."""
    from io import BytesIO

    from PIL import Image

    big = BytesIO()
    Image.new("RGB", (4000, 100), (10, 20, 30)).save(big, format="PNG")
    prepared = embed_module.prepare_image(big.getvalue())

    with Image.open(BytesIO(prepared)) as opened:
        assert max(opened.size) == EMBED_MAX_EDGE_PX
        assert opened.mode == "RGB"


# ── embed_key: the receipt that stops the re-bill (register B5) ──────────────────────────────────

def test_the_key_is_the_composition_and_the_model_and_nothing_else():
    composed = compose(record(text="body"), raster(), doc_title="title", text_chars=2000)

    assert composed.key("gemini-embedding-2") == composed.key("gemini-embedding-2")
    assert composed.key("gemini-embedding-2") != composed.key("some-other-embed-model")


@pytest.mark.parametrize("changed", [
    {"text": "a different body"},
    {"topics": ["a new topic"]},
    {"codes": ["K159"]},
    {"summaries": [("en", "a different summary")]},
    {"sections": ["Another section"]},
])
def test_any_change_to_a_part_changes_the_key(changed):
    base = compose(record(text="body"), raster(), text_chars=2000)
    moved = compose(record(**{"text": "body", **changed}), raster(), text_chars=2000)

    assert moved.key("m") != base.key("m")


def test_a_changed_raster_changes_the_key():
    """The pixels are an input to the embedding, so a corrected page must miss the cache."""
    base = compose(record(text="body"), raster(fill=200), text_chars=2000)
    repainted = compose(record(text="body"), raster(fill=40), text_chars=2000)

    assert repainted.image != base.image
    assert repainted.key("m") != base.key("m")


def test_two_part_lists_that_would_concatenate_alike_do_not_collide():
    """A separator is ambiguous; the canonical form is JSON so a key cannot be shared."""
    left = Composition(page_id="a", parts=("a b", "c"), image=b"png")
    right = Composition(page_id="a", parts=("a", "b c"), image=b"png")

    assert left.canonical != right.canonical
    assert left.key("m") != right.key("m")


def test_the_composition_version_is_an_input_to_the_key():
    composed = Composition(page_id="a", parts=("body",), image=b"png")

    from vsir.vlm.cache import embed_key

    assert composed.key("m") == embed_key(composed.canonical, embed_model="m")
    assert embed_key(composed.canonical, embed_model="m",
                     composition_version="d4-fused-v2") != composed.key("m")


# ── the Gemini backend: three load-bearing API facts ─────────────────────────────────────────────

def test_each_page_is_its_own_content_and_n_pages_return_n_vectors():
    """A bare list in `contents` returns ONE aggregated embedding for the lot (D4)."""
    transport = Recorder()
    pages = [compose(record(page_no=n, text=f"page {n}"), raster(page_no=n), text_chars=2000)
             for n in range(1, 4)]

    vectors = gemini(transport=transport).embed_pages(pages)

    assert len(vectors) == 3
    assert len(transport.calls) == 1
    assert len(transport.calls[0]["contents"]) == 3
    assert all(type(content).__name__ == "Content" for content in transport.contents)


def test_task_type_is_never_sent_to_the_embedding_model():
    """`gemini-embedding-2` rejects it: a caller who added it back would 400 on every page."""
    transport = Recorder()
    embedder_under_test = gemini(transport=transport)

    embedder_under_test.embed_pages([compose(record(text="body"), raster(), text_chars=2000)])
    embedder_under_test.embed_query("which safety function covers the emergency stop?")
    embedder_under_test.embed_query_image(raster().png, "the wiring detail")

    assert len(transport.calls) == 3
    for call in transport.calls:
        assert "task_type" not in call
        assert getattr(call["config"], "task_type", None) is None
        assert call["config"].output_dimensionality == DIM
        assert call["config"].model_dump(exclude_none=True) == {"output_dimensionality": DIM}


def test_a_short_returned_count_falls_back_to_one_call_per_page():
    """If the API ever aggregates a list of Contents, an aggregate must not be written as page 1."""
    transport = Recorder(returns=1)
    pages = [compose(record(page_no=n, text=f"page {n}"), raster(page_no=n), text_chars=2000)
             for n in range(1, 4)]

    vectors = gemini(transport=transport).embed_pages(pages)

    assert len(vectors) == 3
    assert len(transport.calls) == 4, "one batch call, then one call per page"
    assert [len(call["contents"]) for call in transport.calls] == [3, 1, 1, 1]


def test_a_fallback_that_still_returns_the_wrong_count_is_a_refusal():
    class Aggregating(Recorder):
        def __call__(self, **call: Any) -> Any:
            self.calls.append(call)
            return SimpleNamespace(embeddings=[])

    with pytest.raises(EmbedCallFailed):
        gemini(transport=Aggregating()).embed_pages(
            [compose(record(text="body"), raster(), text_chars=2000)])


def test_a_wrong_dimension_raises_rather_than_being_quietly_stored():
    """`output_dimensionality` is MRL truncation, and a short vector is a different space."""
    with pytest.raises(EmbedDimMismatch) as refusal:
        gemini(transport=Recorder(dim=DIM - 1)).embed_pages(
            [compose(record(text="body"), raster(), text_chars=2000)])

    assert refusal.value.details == {"model": "gemini-embedding-2", "returned": DIM - 1,
                                     "expected": DIM}


def test_the_batch_size_splits_the_request_and_order_is_preserved():
    transport = Recorder()
    pages = [compose(record(page_no=n, text=f"page {n}"), raster(page_no=n), text_chars=2000)
             for n in range(1, 6)]

    vectors = gemini(transport=transport, batch_size=2, concurrency=1).embed_pages(pages)

    assert len(vectors) == 5
    assert [len(call["contents"]) for call in transport.calls] == [2, 2, 1]


def test_an_empty_batch_makes_no_call():
    transport = Recorder()

    assert gemini(transport=transport).embed_pages([]) == []
    assert transport.calls == []


def test_a_transient_failure_is_retried_and_a_bad_request_is_not():
    attempts: list[int] = []

    def flaky(**call: Any) -> Any:
        attempts.append(len(attempts))
        if len(attempts) < 3:
            raise RuntimeError("503 service unavailable")
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.5] * DIM)])

    page = [compose(record(text="body"), raster(), text_chars=2000)]
    assert len(gemini(transport=flaky).embed_pages(page)) == 1
    assert len(attempts) == 3

    def refused(**call: Any) -> Any:
        raise RuntimeError("400 invalid argument")

    with pytest.raises(EmbedCallFailed) as refusal:
        gemini(transport=refused).embed_pages(page)
    assert refusal.value.details["attempts"] == 1


def test_a_floating_alias_is_refused_at_the_point_of_spend():
    """F11, register B6 — boot checks it, and so does the call, for a long-lived worker."""
    with pytest.raises(EmbedUnavailable) as refusal:
        GeminiEmbedder(model="gemini-embedding-2-lat" + "est", dim=DIM,
                       credential="x", transport=Recorder()).embed_pages(
            [compose(record(text="body"), raster(), text_chars=2000)])

    assert refusal.value.code == "embed_backend_unavailable"


def test_an_image_query_sends_one_content_with_the_image_last_and_no_prefix():
    """D12 — an image query lands in the space the pages occupy; no instruction when multimodal."""
    transport = Recorder()

    gemini(transport=transport).embed_query_image(raster().png, "the wiring detail")

    contents = transport.calls[0]["contents"]
    assert len(contents) == 1
    parts = contents[0].parts
    assert parts[0].text == "the wiring detail"
    assert parts[-1].inline_data.mime_type == "image/png"


def test_an_image_only_query_carries_no_text_part():
    transport = Recorder()

    gemini(transport=transport).embed_query_image(raster().png)

    assert len(transport.calls[0]["contents"][0].parts) == 1


# ── the stub backend, and the lookup that chooses it ─────────────────────────────────────────────

def test_the_stub_is_a_function_of_the_composition_and_nothing_else():
    """Same composition, same vector — which is what makes a re-ingest bit-identical (I1)."""
    stub = StubEmbedder(dim=32, model="gemini-embedding-2")
    one = compose(record(text="body"), raster(), text_chars=2000)
    same = compose(record(text="body"), raster(), text_chars=2000)
    other = compose(record(text="a different body"), raster(), text_chars=2000)

    assert stub.embed_pages([one]) == stub.embed_pages([same])
    assert stub.embed_pages([one]) != stub.embed_pages([other])
    assert len(stub.embed_pages([one])[0]) == 32


def test_the_stub_vector_is_a_unit_vector_so_cosine_means_something():
    import math

    vector = StubEmbedder(dim=64, model="m").embed_pages(
        [compose(record(text="body"), raster(), text_chars=2000)])[0]

    assert math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0, abs_tol=1e-9)


def test_the_stub_moves_with_the_model_id_so_two_recipes_never_share_a_vector():
    page = compose(record(text="body"), raster(), text_chars=2000)

    assert (StubEmbedder(dim=16, model="a").embed_pages([page])
            != StubEmbedder(dim=16, model="b").embed_pages([page]))


def test_the_backend_is_a_configuration_lookup_never_a_branch():
    """§15 Factor X — VSIR_VLM selects the embedding backend too, so a stub run cannot spend."""
    assert isinstance(embedder(load_config(SYNTHETIC_ENV)), StubEmbedder)
    assert set(embed_module.EMBEDDERS) == {"stub", "gemini"}

    live = load_config({**SYNTHETIC_ENV, "VSIR_VLM": "gemini"})
    with pytest.raises(EmbedUnavailable) as refusal:
        embedder(live)
    assert "VSIR_VLM_KEY" in str(refusal.value)


def test_an_unpinned_embedding_model_is_refused_when_the_backend_is_built():
    with pytest.raises(EmbedUnavailable):
        embedder(load_config({**SYNTHETIC_ENV,
                              "VSIR_EMBED_MODEL": "gemini-embedding-lat" + "est"}))


# ── step 09 over a document: the cache, and the stamp (register B5) ──────────────────────────────

class Counting:
    """An embedder that counts the pages it was asked to buy."""

    name = "counting"
    model = "gemini-embedding-2"

    def __init__(self, dim: int = DIM) -> None:
        self.dim = dim
        self.bought: list[str] = []

    def embed_pages(self, compositions: Sequence[Composition]) -> list[list[float]]:
        self.bought.extend(item.page_id for item in compositions)
        return [[0.25] * self.dim for _ in compositions]

    def embed_query(self, question: str) -> list[float]:
        return [0.25] * self.dim

    def embed_query_image(self, image: bytes, text: str | None = None) -> list[float]:
        return [0.25] * self.dim


def test_every_record_comes_back_stamped_with_its_embed_key(synthetic_pdf):
    backend = Counting()
    records = [record(page_no=n, text=f"page {n}") for n in (1, 2)]

    embedding = embed_document(backend, records, source=synthetic_pdf, text_chars=2000)

    assert len(embedding.vectors) == 2
    for stamped in embedding.records:
        assert stamped.provenance.embed_key == embedding.composition(stamped.page_id).key(
            backend.model)
    assert embedding.billed == tuple(page.page_id for page in records)
    assert embedding.reused == ()


def test_an_unchanged_composition_is_reused_and_never_re_billed(synthetic_pdf):
    """Register B5 — the store is the index, so closing it adds no state anywhere."""
    backend = Counting()
    records = [record(page_no=n, text=f"page {n}") for n in (1, 2)]
    first = embed_document(backend, records, source=synthetic_pdf, text_chars=2000)

    cached = {page_id: (first.composition(page_id).key(backend.model), vector)
              for page_id, vector in first.vectors.items()}
    backend.bought.clear()
    second = embed_document(backend, records, source=synthetic_pdf, text_chars=2000,
                            cached=cached)

    assert backend.bought == []
    assert second.reused == tuple(page.page_id for page in records)
    assert second.vectors == first.vectors


@pytest.mark.parametrize("stale", [
    "a key from a different composition",
    "",
])
def test_a_cache_entry_whose_key_does_not_match_is_re_billed(synthetic_pdf, stale):
    backend = Counting()
    records = [record(page_no=1, text="page 1")]
    cached = {records[0].page_id: (stale, [0.1] * DIM)}

    embedding = embed_document(backend, records, source=synthetic_pdf, text_chars=2000,
                              cached=cached)

    assert backend.bought == [records[0].page_id]
    assert embedding.reused == ()


def test_a_cached_vector_of_the_wrong_dim_is_re_billed(synthetic_pdf):
    """A 768 vector in a 1536 collection is not a cache hit, it is a rejected upsert."""
    backend = Counting()
    records = [record(page_no=1, text="page 1")]
    composed = embed_document(backend, records, source=synthetic_pdf, text_chars=2000)
    backend.bought.clear()

    embed_document(backend, records, source=synthetic_pdf, text_chars=2000,
                   cached={records[0].page_id: (
                       composed.composition(records[0].page_id).key(backend.model),
                       [0.1] * (DIM - 1))})

    assert backend.bought == [records[0].page_id]


def test_an_embedder_that_returns_the_wrong_count_is_a_refusal(synthetic_pdf):
    class Short(Counting):
        def embed_pages(self, compositions):
            return super().embed_pages(compositions)[:-1]

    with pytest.raises(EmbedCallFailed):
        embed_document(Short(), [record(page_no=n, text=f"p{n}") for n in (1, 2)],
                       source=synthetic_pdf, text_chars=2000)


# ── L1: the generated corpus (§13 M2a) ──────────────────────────────────────────────────────────

def test_the_generated_corpus_embeds_one_fused_vector_per_page(synthetic_pdf, stitched, extracted,
                                                               synthetic_config):
    """42 pages, 42 vectors, every one composed from that page's own record and raster (I1, D4)."""
    doc, probed, facts, _plan, _extraction = extracted
    cfg = synthetic_config
    backend = embedder(cfg)

    embedding = embed_document(backend, stitched.pages, source=synthetic_pdf,
                               content_hash=probed.content_hash, doc_title=facts.title,
                               text_chars=cfg.embed_text_chars)

    assert len(embedding.vectors) == len(stitched.pages) == probed.page_count
    assert {len(vector) for vector in embedding.vectors.values()} == {cfg.embed_dim}
    assert len({composition.key(backend.model)
                for composition in embedding.compositions}) == probed.page_count
    assert all(composition.dpi == DPI_INDEX for composition in embedding.compositions)
    assert all(part.strip() for composition in embedding.compositions
               for part in composition.parts)
    assert embedding.records[0].provenance.embed_key
    assert doc.doc_id in {stamped.doc_id for stamped in embedding.records}


def test_the_corpus_composition_carries_the_document_title_first(synthetic_pdf, stitched,
                                                                 extracted, synthetic_config):
    _doc, probed, facts, _plan, _extraction = extracted
    cfg = synthetic_config

    embedding = embed_document(embedder(cfg), stitched.pages[:1], source=synthetic_pdf,
                               content_hash=probed.content_hash, doc_title=facts.title,
                               text_chars=cfg.embed_text_chars)

    assert facts.title
    assert embedding.compositions[0].parts[0] == facts.title


# ── the lazy SDK client is built once, under concurrency ────────────────────────────────────────

def test_one_sdk_client_is_built_no_matter_how_many_threads_ask_at_once():
    """The race that failed a live 56-page ingest at step 09 (2026-09-11).

    `embed_pages` fans batches over a pool of `EMBED_CONCURRENCY` workers, and `_client()` was an
    unguarded ``if self._sdk_client is None``. Two threads both saw ``None``, both built a client,
    and the second assignment orphaned the first — whose `httpx` transport then closed under the
    thread still using it: `RuntimeError: Cannot send a request, as the client has been closed`.

    Invisible below `EMBED_BATCH_SIZE` pages, because one batch is one worker. That is why a green
    suite and a two-page live run both missed it, and it is why this test drives the threads
    directly rather than going through a document.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    built: list[object] = []
    barrier = threading.Barrier(8)

    embedder = gemini()

    def build() -> object:
        # Every thread arrives at the check together, which is the only way to make the
        # unguarded version fail reliably rather than one run in ten.
        barrier.wait()
        client = embedder._client()
        built.append(client)
        return client

    with monkeypatched_genai(built_count := []):
        with ThreadPoolExecutor(max_workers=8) as pool:
            clients = list(pool.map(lambda _: build(), range(8)))

    assert len({id(client) for client in clients}) == 1, \
        "every thread must get the same client instance"
    assert len(built_count) == 1, \
        f"the SDK client was constructed {len(built_count)} times; it must be built exactly once"


@contextlib.contextmanager
def monkeypatched_genai(record: list):
    """Count `genai.Client(...)` constructions without opening a transport."""

    class FakeClient:
        def __init__(self, **kwargs):
            # A real `genai.Client` builds an `httpx` transport, which is slow enough that
            # several threads sit inside this constructor at once. The sleep restores that
            # window: without it the check-and-assign is effectively atomic under the GIL for a
            # trivial `__init__`, and the test passes even with the lock removed — which is to
            # say it would assert nothing. Verified both ways.
            time.sleep(0.02)
            record.append(self)

    original = embed_module.genai.Client
    embed_module.genai.Client = FakeClient
    try:
        yield
    finally:
        embed_module.genai.Client = original
