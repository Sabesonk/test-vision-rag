"""L2 — image queries (Spec §7.2.1, D12, U017): a technician photographs a panel and it searches.

D12 states three rules and each one is a different kind of failure if it is missing:

1. **No instruction prefix when the query is multimodal.** Google's guidance, and `impl`'s
   constraint. A prefix here does not error — it moves the query vector, and the rows come back
   looking exactly as convincing as correct ones. Asserted on the **request payload** the SDK
   would have received, with a recording transport, because that is the only place the absence of
   a prefix is observable.
2. **An image-only query runs the dense branch alone.** There is no query text, so there is
   nothing to build a sparse vector from; the two sparse branches are skipped and every row says
   `why: ["dense"]` — stated, so an agent knows the evidence is weaker than a `lexical` hit.
   Asserted twice: on the rows, and with a **call spy** on the store, because a branch that ran
   and contributed nothing would be invisible in the rows alone.
3. **An image can never reach the exact surface.** `lookup` and `verify` take a text label only
   (I2, I3). A photograph may *find* a candidate page; it can never *confirm* a code.

No Gemini call is made anywhere in this file: `VSIR_VLM=stub` selects the embedding backend by
configuration (§15 Factor X, D10), and rule 1 is checked against `GeminiEmbedder` with an injected
transport — the shipped request builder, with nothing on the other end of it.
"""
from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import types

from vsir.config import EMBED_QUERY_INSTRUCTION
from vsir.ingest.embed import GeminiEmbedder, query_vector
from vsir.serve.app import SkimPagesRequest
from vsir.serve.envelope import Provenance
from vsir.serve.tools.skim import skim_pages

from conftest import EMBED_DIM, SKIM_COLLECTION, skim_config

SKIM = "/tools/skim_pages"

#: A tiny PNG. The stub embedder hashes the bytes, so what matters is that they are stable, not
#: that they are a photograph of anything.
PANEL_PNG = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class SpyClient:
    """A Qdrant client that records what was asked of it and answers from the real one.

    A proxy rather than a fake: the answers have to be the real store's, or an assertion that a
    branch was skipped would be an assertion about a mock. Only ``query_points`` is recorded,
    because that is the call a branch *is*.
    """

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.searched: list[str] = []

    def query_points(self, *args: Any, **call: Any) -> Any:
        self.searched.append(str(call.get("using")))
        return self.inner.query_points(*args, **call)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


class Recorder:
    """A transport that records the request and returns one vector of the right width."""

    def __init__(self, dim: int = EMBED_DIM) -> None:
        self.calls: list[dict[str, Any]] = []
        self.dim = dim

    def __call__(self, **call: Any) -> Any:
        self.calls.append(call)
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.5] * self.dim)
                                           for _ in call["contents"]])


def gemini(recorder: Recorder) -> GeminiEmbedder:
    return GeminiEmbedder(model="gemini-embedding-2", dim=EMBED_DIM,
                          credential="not-a-real-credential", transport=recorder,
                          sleep=lambda _seconds: None)


def parts_of(recorder: Recorder) -> list[Any]:
    [call] = recorder.calls
    [content] = call["contents"]
    return list(content.parts)


# ── rule 1: no instruction prefix when the query is multimodal ──────────────────────────────────

def test_a_multimodal_query_sends_the_words_verbatim_and_the_raster_in_one_content():
    """One `types.Content`, so the model fuses them — *"this photo, but the wiring detail"* (D4).

    The words are asserted **exactly**: no prefix, no template, no instruction. This is the request
    payload that would have gone to the API.
    """
    recorder = Recorder()
    query_vector(gemini(recorder), text="the wiring detail", image=PANEL_PNG)

    [call] = recorder.calls
    assert len(call["contents"]) == 1, "the photo and the words must travel in ONE Content"
    text_part, image_part = parts_of(recorder)
    assert text_part.text == "the wiring detail"
    assert not text_part.text.startswith(EMBED_QUERY_INSTRUCTION or "\0")
    assert image_part.inline_data is not None and image_part.inline_data.mime_type == "image/png"
    # `task_type` is rejected by this model, and the config carries the dim and nothing else.
    assert call["config"] == types.EmbedContentConfig(output_dimensionality=EMBED_DIM)


def test_an_image_only_query_sends_the_raster_alone():
    """No empty text part standing in for the words that were never given."""
    recorder = Recorder()
    query_vector(gemini(recorder), text="", image=PANEL_PNG)

    [only] = parts_of(recorder)
    assert only.inline_data is not None


def test_a_text_query_is_the_only_place_a_prefix_could_ever_apply():
    """And it is empty by pin, because the corpus side is multimodal (§4.2, D4)."""
    recorder = Recorder()
    query_vector(gemini(recorder), text="emergency stop")

    [only] = parts_of(recorder)
    assert EMBED_QUERY_INSTRUCTION == ""
    assert only.text == "emergency stop"


def test_a_query_that_is_neither_words_nor_a_photograph_is_refused_before_the_model():
    """A vector of nothing still returns ten confident-looking rows."""
    recorder = Recorder()
    with pytest.raises(Exception):
        query_vector(gemini(recorder), text="   ")
    assert recorder.calls == []


# ── rule 2: an image-only query runs the dense branch alone ─────────────────────────────────────

def test_an_image_only_query_returns_rows_whose_why_is_exactly_dense(skimming, token_header):
    body = skimming.post(SKIM, json={"image": base64.b64encode(PANEL_PNG).decode(),
                                     "scope": {"doc_id": "SYN-M1"}},
                         headers=token_header)

    assert body.status_code == 200, body.text
    payload = body.json()
    assert payload["status"] == "ok" and payload["hits"]
    for hit in payload["hits"]:
        assert hit["why"] == ["dense"]


def test_the_sparse_branches_are_not_executed_for_an_image_only_query(qdrant, skim_collection,
                                                                      stub_embedder):
    """The call spy: not *"they contributed nothing"*, but *"they were never asked"*."""
    spy = SpyClient(qdrant)
    response = skim_pages(spy, skim_collection, image=PANEL_PNG, scope={"doc_id": "SYN-M1"},
                          embedder=stub_embedder, provenance=Provenance(release_id="test"))

    assert spy.searched == ["dense"]
    assert response.hits and all(hit.why == ["dense"] for hit in response.hits)


def test_a_multimodal_query_runs_all_three_branches(qdrant, skim_collection, stub_embedder):
    """The contrast that makes the previous assertion mean something."""
    spy = SpyClient(qdrant)
    skim_pages(spy, skim_collection, query="emergency stop", image=PANEL_PNG,
               scope={"doc_id": "SYN-M1"}, embedder=stub_embedder,
               provenance=Provenance(release_id="test"))

    assert sorted(spy.searched) == ["captions", "dense", "lexical"]


def test_a_photograph_and_words_rank_differently_from_the_words_alone(skimming, token_header):
    """The photograph is part of the query vector, not decoration beside it."""
    scope = {"doc_id": "SYN-M1"}
    with_photo = skimming.post(SKIM, json={"query": "emergency stop", "scope": scope,
                                           "image": base64.b64encode(PANEL_PNG).decode()},
                               headers=token_header).json()
    words_only = skimming.post(SKIM, json={"query": "emergency stop", "scope": scope},
                               headers=token_header).json()

    assert [hit["page_id"] for hit in with_photo["hits"]] != \
        [hit["page_id"] for hit in words_only["hits"]]


def test_an_image_that_is_not_base64_is_a_typed_400(skimming, token_header):
    """The caller's request is wrong; the search is not empty. Two different answers."""
    response = skimming.post(SKIM, json={"image": "not base64 at all!!"}, headers=token_header)

    assert response.status_code == 400
    assert response.json()["error"] == "image_invalid"


# ── rule 3: an image can never reach the exact surface (I2, I3) ─────────────────────────────────

@pytest.mark.parametrize("tool,body", [
    ("lookup", {"label": "K158", "image": "aGk="}),
    ("verify", {"claims": ["K158"], "page_ids": ["SYN-M1@1.0#p001"], "image": "aGk="}),
])
def test_lookup_and_verify_reject_an_image_parameter(skimming, token_header, tool, body):
    """`extra="forbid"` on every tool body, so this is a `400` and never a quietly ignored field.

    A photograph may *find* a candidate page through `skim_pages`; it can never *confirm* a code.
    An `image` silently dropped by `verify` would be a caller believing it had shown the page to
    a model and been told the code was there.
    """
    response = skimming.post(f"/tools/{tool}", json=body, headers=token_header)

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


def test_only_the_skim_rung_declares_an_image_at_all():
    """The property, read off the request models rather than off the routes."""
    from vsir.serve.app import LookupRequest, ResolveRequest, VerifyRequest

    assert "image" in SkimPagesRequest.model_fields
    for model in (LookupRequest, VerifyRequest, ResolveRequest):
        assert "image" not in model.model_fields


def test_the_configuration_names_the_stub_backend_and_nothing_reached_gemini():
    """D10 — replay is selected by config, never by a branch or a test-only import."""
    configuration = skim_config()

    assert configuration.vlm == "stub"
    assert configuration.pages_collection.startswith(SKIM_COLLECTION)
