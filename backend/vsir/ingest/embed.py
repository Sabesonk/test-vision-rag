"""Step 09 — one page, one fused vector. Ported from ``impl/app/embedder.py`` (D4, §5.3).

This is the load-bearing port of the previous implementation, and the reason it is a port rather
than a rewrite is that three of its details are API facts nobody would re-derive:

1. **``task_type`` is rejected by this model.** There is no document/query mode, so the asymmetry
   between a short question and a whole page cannot be steered by a flag. It is closed on the
   *index* side instead, by interleaving the page's own text into its vector — which is what the
   composition below is for.
2. **A bare list in ``contents`` returns ONE aggregated embedding for the whole list.** Send eight
   pages that way and you get one blended vector instead of eight, silently. Each page is therefore
   wrapped in its **own** ``types.Content``, the returned count is verified, and there is a
   per-item fallback if the API ever changes that behaviour.
3. **``output_dimensionality`` is MRL truncation** (768 → 1536 → 3072). A wrong dimension raises
   rather than being quietly stored, and the dim is carried in the collection name and in the
   §6.6 fingerprint — comparing two dims is two collections, never two vectors in one.

The aggregation of (2) is the mechanism, used deliberately **within** a page and refused
**between** pages::

    WITHIN a page    7 parts  → 1 vector     wanted — it is how a page gets one position
    BETWEEN pages    8 pages  → 8 vectors    required — I1, one page one point

**The composition is §5.3's order, and each text part is its own ``Part``** — never a
concatenated blob, which is what D8 is about: a two-language page gets **two summary Parts**
rather than one blended string, so the model fuses structured parts rather than a pre-blended
one::

    doc_title · section_titles · summaries[] (one per language, D5) · topics · codes
             · text[:VSIR_EMBED_TEXT_CHARS] · the page raster @ dpi_index (150)

Four differences from `impl`, three of them register items:

* **The vectors are cached** by ``embed_key`` (register B5). `impl` has no key and no store, so an
  unrelated change re-buys every vector in the corpus — 142 pages today, 1,440 for the manual it
  cannot ingest. The store is the index itself: :func:`vsir.ingest.index.cached_vectors` reads the
  vector and the ``embed_key`` already on the page's point, and an unchanged composition is reused
  rather than re-billed. Nothing new is stored anywhere to make that work.
* **The model id is pinned at the point of spend** (register B6, F11), so a floating alias cannot
  reach the call even in a long-lived worker whose configuration never went through a boot check.
* **Truncation is counted.** `impl` cuts ``text[:4000]`` and ``units[:6]`` and neither is counted
  or flagged, so nothing would tell you when a corpus started losing page tails (register defect
  §5.3 of `08-embedding.md`). :class:`Composition` records exactly how many characters were
  dropped and the CLI prints it.
* **The printed page label is not a part.** `impl` prefixes ``page `` onto a label that already
  says ``Page 1 of 55`` and embeds the result on every page. §5.3's order does not carry the label
  at all, and a printed label is `resolve`'s question (§7.2.3), answered from an indexed facet
  rather than by nearest-neighbour — so the part goes, and its cosmetic defect with it.

**The backend is a dictionary lookup on ``VSIR_VLM``**, exactly as the VLM boundary is
(:mod:`vsir.vlm`) — one switch for "does this release make live model calls", so a run that stubs
S2 can never quietly spend on embeddings. The stub differs from :class:`~vsir.vlm.stub.StubBackend`
in one honest way: there are no frozen embeddings to replay, so it **computes** a deterministic
vector from the composition rather than reading one. That is safe here and would not be for S2,
because an embedding is not a claim about the page — it orders candidates, and every path that can
reach an *answer* goes through the exact surface, which is text the probe extracted (I2, I3).
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import random
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

from google import genai
from google.genai import types
from PIL import Image

from vsir import logging as vsir_logging
from vsir.config import (
    COMPOSITION_VERSION,
    DPI_INDEX,
    EMBED_BATCH_SIZE,
    EMBED_CONCURRENCY,
    EMBED_DIMS,
    EMBED_MAX_EDGE_PX,
    EMBED_QUERY_INSTRUCTION,
    FLOATING_SUFFIX,
    Config,
)
from vsir.core.record import PageRecord
from vsir.ingest import render
from vsir.vlm.cache import embed_key
from vsir.vlm.client import BACKOFF_CEILING_S, MAX_ATTEMPTS, RETRYABLE

_log = vsir_logging.get_logger(__name__)

#: The separator between the several titles or labels that share one ``Part``. Only ``summaries[]``
#: is one Part per element (D5); ``section_titles``, ``topics`` and ``codes`` are each a single
#: Part, because §5.3's order names them in the singular and a Part per topic would bury the
#: page's own text under a list of one-word fragments.
JOIN = " · "

#: What ``prepare_image`` emits, and the only mime type either side of the call ever sends.
IMAGE_MIME = "image/png"


class EmbedError(RuntimeError):
    """A typed refusal from the embedding boundary, with a machine-readable code.

    Same contract as the VLM boundary's (:class:`vsir.vlm.cache.VlmError`) and the renderer's: an
    operator switches on the code, and the details name what would have to change.
    """

    code = "embed_error"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        return {"error": self.code, "detail": self.message, **self.details}


class EmbedUnavailable(EmbedError):
    """The configured embedding backend cannot run: no credential, no such backend, no pin."""

    code = "embed_backend_unavailable"


class EmbedCallFailed(EmbedError):
    """The call did not come back, after the retry budget."""

    code = "embed_call_failed"


class EmbedDimMismatch(EmbedError):
    """The model returned a vector of a dimension the collection is not built for.

    Never stored. `impl` raises here too, and it is right to: a short vector in a cosine index is
    not a worse result, it is a rejected upsert at best and a silently different space at worst.
    """

    code = "embed_dim_mismatch"


# ── the composition (§5.3, D4) ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Composition:
    """One page, packed for the model: the ordered text parts and the raster that follows them.

    Kept as a value rather than built inline at the call site, for two reasons that are both about
    review: the *order* of the parts is a spec clause (§5.3) and belongs somewhere a test can read
    it, and ``embed_key`` is a digest of exactly this — so the thing that is keyed and the thing
    that is sent are the same object, and cannot drift into describing different requests.
    """

    page_id: str
    #: The text parts, in §5.3's order, each destined for its own ``types.Part``. Empty and
    #: whitespace-only parts are already gone: an empty Part is a token spent on nothing.
    parts: tuple[str, ...]
    #: The ``dpi_index`` raster, prepared (RGB PNG, long edge bounded). The **last** Part.
    image: bytes
    dpi: int = DPI_INDEX
    #: How many characters of ``text`` were carried, and how many were left behind. `impl` cuts
    #: silently; counting it is what makes a corpus that starts losing page tails visible.
    text_chars: int = 0
    text_dropped: int = 0
    #: One per language (D5). Recorded so a test can assert two languages produced two Parts
    #: without having to guess which of ``parts`` they are.
    summary_parts: int = 0

    @property
    def image_sha256(self) -> str:
        return hashlib.sha256(self.image).hexdigest()

    @property
    def canonical(self) -> str:
        """The ``composed string`` of §6.3's ``embed_key``: every input that can move the vector.

        JSON rather than a joined string, because a separator is ambiguous: two different part
        lists can concatenate to one string, and a key two compositions collide on would serve one
        page's vector as another's. The raster enters by digest — the pixels are an input to the
        embedding, so a re-render at a different dpi or a corrected page must miss the cache.

        ``dpi`` is deliberately **not** here: it cannot change without changing the pixels, so it
        is already carried by the digest, and an input that cannot change the answer only re-bills.
        """
        return json.dumps({"parts": list(self.parts), "image_sha256": self.image_sha256},
                          sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def key(self, embed_model: str) -> str:
        """``embed_key`` for this composition (§6.3): the receipt that stops a re-bill (B5)."""
        return embed_key(self.canonical, embed_model=embed_model,
                         composition_version=COMPOSITION_VERSION)

    def contents(self) -> types.Content:
        """The one ``types.Content`` this page is sent as: text Parts, then the raster **last**.

        One Content per page is not a style choice — a bare list would come back as a single
        aggregated vector for the whole batch (see the module docstring).
        """
        parts = [types.Part(text=part) for part in self.parts]
        parts.append(types.Part.from_bytes(data=self.image, mime_type=IMAGE_MIME))
        return types.Content(parts=parts)


def prepare_image(data: bytes, *, max_edge: int = EMBED_MAX_EDGE_PX) -> bytes:
    """Normalise to RGB PNG and bound the long edge — ported verbatim in intent from `impl`.

    The bound is what keeps tokens and cost predictable: an image part is billed by area, and a
    400 dpi A3 render is four times the page for none of the fidelity the text layer already has.
    """
    if max_edge < 1:
        raise ValueError(f"max_edge is a pixel count: {max_edge}")
    with Image.open(io.BytesIO(data)) as image:
        prepared = image.convert("RGB")
        if max(prepared.size) > max_edge:
            scale = max_edge / max(prepared.size)
            prepared = prepared.resize(
                (max(1, int(prepared.width * scale)), max(1, int(prepared.height * scale))),
                Image.LANCZOS,
            )
        buffer = io.BytesIO()
        prepared.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()


def _unique(values: Sequence[str]) -> list[str]:
    """Order-preserving de-duplication. A page in two sections of the same title says it once."""
    seen: set[str] = set()
    kept: list[str] = []
    for value in values:
        stripped = value.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            kept.append(stripped)
    return kept


def compose(record: PageRecord, raster: render.Raster, *, doc_title: str = "",
            text_chars: int, max_edge: int = EMBED_MAX_EDGE_PX) -> Composition:
    """Pack one finished page record into §5.3's ordered parts, plus its ``dpi_index`` raster.

    ``record`` is the **stitched** record (step 08): the section titles it carries are the ones
    stitching resolved, so a page that straddles a window fold contributes the whole section's
    title rather than the fragment one window happened to see (F8).
    """
    if raster.dpi != DPI_INDEX:
        raise EmbedError(
            f"the dense composition embeds the dpi_index raster ({DPI_INDEX}), got dpi "
            f"{raster.dpi}: dpi_answer is S2's and `read`'s, and mixing the two would make one "
            f"collection hold vectors of two different rasters (§4.2, SA-12)",
            page_id=record.page_id, dpi=raster.dpi, expected=DPI_INDEX,
        )
    if raster.page_no != record.page_no:
        raise EmbedError(
            f"raster is page {raster.page_no} and the record is page {record.page_no}: a page "
            f"embedded beside another page's pixels is the offset failure I4 exists to prevent",
            page_id=record.page_id, page_no=record.page_no, raster_page_no=raster.page_no,
        )
    if text_chars < 1:
        raise ValueError(f"VSIR_EMBED_TEXT_CHARS is a character count: {text_chars}")

    content = record.content
    parts: list[str] = []
    if doc_title.strip():
        parts.append(doc_title.strip())

    section_titles = _unique([section.title for section in content.sections])
    if section_titles:
        parts.append(JOIN.join(section_titles))

    # One Part per language, never one blended string (D5, D8). This is the whole of D8's ruling:
    # the objection was to blending summaries *into one string*, and separate Parts are exactly
    # what a multimodal embedding is designed to take — so one vector per page still holds.
    summaries = [summary.text.strip() for summary in content.summaries if summary.text.strip()]
    parts.extend(summaries)

    topics = _unique(content.topics)
    if topics:
        parts.append(JOIN.join(topics))

    codes = _unique(content.codes)
    if codes:
        parts.append(" ".join(codes))

    text = record.text.strip()
    carried = text[:text_chars]
    if carried:
        parts.append(carried)

    return Composition(
        page_id=record.page_id,
        parts=tuple(parts),
        image=prepare_image(raster.png, max_edge=max_edge),
        dpi=raster.dpi,
        text_chars=len(carried),
        text_dropped=max(0, len(text) - len(carried)),
        summary_parts=len(summaries),
    )


# ── the backends: one lookup on VSIR_VLM, no branch (§15 Factor X) ───────────────────────────────

@runtime_checkable
class Embedder(Protocol):
    """What both embedding backends are: a name, a pinned model, a dim, and three calls."""

    name: str
    model: str
    dim: int

    def embed_pages(self, compositions: Sequence[Composition]) -> list[list[float]]:
        """N compositions → N vectors, in order. Never one aggregate for the batch."""

    def embed_query(self, question: str) -> list[float]:
        """A technician's question, in the space the pages occupy."""

    def embed_query_image(self, image: bytes, text: str | None = None) -> list[float]:
        """A photographed panel as the **query** side of a search (D12, §7.2.1)."""


def _pinned(model: str) -> str:
    """Re-verify the embedding pin at the point of spend (F11, register B6).

    The same rule the VLM boundary applies to ``VSIR_VLM_MODEL``, applied here to
    ``VSIR_EMBED_MODEL`` — and it matters more, not less: a repointed embedding alias puts vectors
    from two different models in one cosine space, which produces worse neighbours and no error.
    That is the §6.6 fingerprint's job downstream; this is the half that stops it happening.
    """
    if not model:
        raise EmbedUnavailable("VSIR_EMBED_MODEL is not set", model=model)
    if model.endswith(FLOATING_SUFFIX):
        raise EmbedUnavailable(
            f"VSIR_EMBED_MODEL={model!r} ends in {FLOATING_SUFFIX}: pin the version (§4.3, F11). "
            f"A repointed alias mixes two models' vectors in one collection under a name that "
            f"claims otherwise, and the fingerprint would then agree with both",
            model=model, suffix=FLOATING_SUFFIX,
        )
    return model


def _checked_dim(dim: int) -> int:
    if dim not in EMBED_DIMS:
        raise EmbedUnavailable(
            f"dim {dim} is not one of {list(EMBED_DIMS)}: output_dimensionality is MRL truncation "
            f"and the dim is in the collection name (§5.5, §6.6)",
            dim=dim, allowed=list(EMBED_DIMS),
        )
    return dim


def _normalised(values: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values] if norm else list(values)


@dataclass(frozen=True)
class StubEmbedder:
    """Deterministic vectors, computed from the composition. Selected by ``VSIR_VLM=stub``.

    Unlike :class:`~vsir.vlm.stub.StubBackend` this does not replay a frozen response, because
    there is nothing to freeze that would be worth reading: an embedding is 1,536 floats, and a
    fixture of them would be unreviewable, unmergeable and no more truthful than a hash.

    So it is a **function of the composition**, which buys two properties the tests need. The same
    composition always yields the same vector, so a re-ingest is bit-identical and I1's "totals
    never double" is testable; and a *changed* composition yields a different vector, so a test can
    prove the composition is what is embedded — which is the one thing about this step that the
    spec constrains and a fixture could not check.

    Why that is safe here and would not be for S2: nothing downstream asserts what a vector means.
    It orders candidates for a human or an agent to look at, and every path that can reach an
    **answer** goes through the exact surface, which is text the probe extracted (I2, I3). A
    fabricated ``WindowOut``, by contrast, would put invented codes and summaries into records that
    the whole system then treats as observations — which is why D10 refuses one.
    """

    dim: int
    model: str
    name: str = "stub"

    @classmethod
    def from_config(cls, cfg: Config) -> "StubEmbedder":
        return cls(dim=_checked_dim(cfg.embed_dim), model=_pinned(cfg.embed_model))

    def _vector(self, seed: str) -> list[float]:
        """A unit vector of ``dim`` floats, derived from ``seed`` and nothing else."""
        material = f"{COMPOSITION_VERSION}|{self.model}|{self.dim}|{seed}".encode("utf-8")
        raw = bytearray()
        counter = 0
        while len(raw) < self.dim * 2:
            raw += hashlib.blake2b(material, digest_size=64,
                                   person=counter.to_bytes(8, "big")).digest()
            counter += 1
        values = [int.from_bytes(raw[index * 2:index * 2 + 2], "big") / 32767.5 - 1.0
                  for index in range(self.dim)]
        return _normalised(values)

    def embed_pages(self, compositions: Sequence[Composition]) -> list[list[float]]:
        vectors = [self._vector(composition.canonical) for composition in compositions]
        _log.info("embed_stub", call="embed_pages", pages=len(vectors), dim=self.dim,
                  model=self.model)
        return vectors

    def embed_query(self, question: str) -> list[float]:
        instruction = EMBED_QUERY_INSTRUCTION
        return self._vector(json.dumps({"query": f"{instruction}{question}"}, sort_keys=True,
                                       separators=(",", ":"), ensure_ascii=False))

    def embed_query_image(self, image: bytes, text: str | None = None) -> list[float]:
        payload = {"image_sha256": hashlib.sha256(image).hexdigest(),
                   "text": (text or "").strip()}
        return self._vector(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=False))


@dataclass
class GeminiEmbedder:
    """The live backend. Selected by ``VSIR_VLM=gemini`` and by nothing else (§15 Factor X)."""

    model: str
    dim: int
    batch_size: int = EMBED_BATCH_SIZE
    concurrency: int = EMBED_CONCURRENCY
    #: repr=False so no traceback, log line or error message can carry the credential (§15.1).
    credential: str = field(repr=False, default="")
    #: Injected in one place so a test can drive the count-mismatch fallback, the dim check and the
    #: retry ladder without a network. Production leaves it None and the SDK client is built here.
    transport: Callable[..., Any] | None = None
    sleep: Callable[[float], None] = time.sleep
    name: str = "gemini"
    #: The SDK client, built on first use by :meth:`_client` and held for the embedder's life. Not
    #: part of its identity, so it is excluded from `repr` and from comparison.
    _sdk_client: Any = field(default=None, repr=False, compare=False)

    @classmethod
    def from_config(cls, cfg: Config) -> "GeminiEmbedder":
        if not cfg.vlm_key:
            raise EmbedUnavailable(
                "VSIR_VLM=gemini needs VSIR_VLM_KEY: the embedding model is the same provider as "
                "the VLM and takes the same credential, which arrives from the platform secret "
                "store at runtime, never from the image (§15 Factor III)",
                model=cfg.embed_model,
            )
        return cls(model=_pinned(cfg.embed_model), dim=_checked_dim(cfg.embed_dim),
                   credential=cfg.vlm_key)

    # -- the one place the SDK is touched -------------------------------------------------------

    def _client(self) -> Any:
        """One SDK client per embedder, built on first use and kept.

        **Not one per call**, for the reason `vlm/client.py::GeminiBackend._client` records: the
        client owns an `httpx` transport and closes it when finalised, so as a temporary it can be
        collected while its own request is still in flight — `RuntimeError: Cannot send a request,
        as the client has been closed`. A document is one embedding call per batch of pages, so
        this is also where the connection pool starts paying for itself.
        """
        if self._sdk_client is None:
            self._sdk_client = genai.Client(api_key=self.credential)
        return self._sdk_client

    def _sdk(self, **call: Any) -> Any:
        return self._client().models.embed_content(**call)

    def _call(self, contents: list[types.Content]) -> Any:
        """One request. ``output_dimensionality`` is the **only** config field.

        There is deliberately no ``task_type``: ``gemini-embedding-2`` rejects it, and a caller who
        added it back would get a 400 on every page of a full-corpus run. The absence is asserted
        on the request payload by an L0 test rather than left as a comment.
        """
        transport = self.transport or self._sdk
        return transport(
            model=_pinned(self.model),
            contents=contents,
            config=types.EmbedContentConfig(output_dimensionality=self.dim),
        )

    def _vectors_of(self, response: Any) -> list[list[float]]:
        returned = getattr(response, "embeddings", None) or ()
        return [list(embedding.values) for embedding in returned]

    def _with_retry(self, call: Callable[[], Any], what: str) -> Any:
        """`impl`'s retry ladder, on the boundary's shared constants.

        A typed refusal of ours is re-raised before the retry test, not after: several of our codes
        contain a RETRYABLE substring and would otherwise be retried on the strength of their name.
        """
        last: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return call()
            except EmbedError:
                raise
            except Exception as failure:  # noqa: BLE001 - the SDK raises a wide range
                last = failure
                blob = f"{type(failure).__name__} {failure}".lower()
                if not any(marker in blob for marker in RETRYABLE) or attempt == MAX_ATTEMPTS:
                    raise EmbedCallFailed(
                        f"{what}: {type(failure).__name__}: {failure}",
                        attempts=attempt, model=self.model,
                    ) from failure
                delay = min(2.0 ** (attempt - 1), BACKOFF_CEILING_S) + random.random()
                _log.warning("embed_retry", call=what, attempt=attempt, attempts=MAX_ATTEMPTS,
                             delay_s=round(delay, 2), detail=type(failure).__name__)
                self.sleep(delay)
        raise EmbedCallFailed(f"{what}: {last}", attempts=MAX_ATTEMPTS, model=self.model)

    def _embed_contents(self, contents: list[types.Content], what: str) -> list[list[float]]:
        """N Contents → N vectors, with the count verified and a per-item fallback if it is not.

        The fallback is the whole reason this function exists rather than a one-line call. A bare
        list in ``contents`` returns **one** aggregated embedding, and if the API ever extends that
        behaviour to a list of ``Content`` objects, an aggregate would otherwise be written to the
        first page of the batch and the rest of the pages would simply be missing.
        """
        if not contents:
            return []
        response = self._with_retry(lambda: self._call(contents), what)
        vectors = self._vectors_of(response)

        if len(vectors) != len(contents):
            _log.warning("embed_count_mismatch", call=what, expected=len(contents),
                         returned=len(vectors), model=self.model,
                         detail="the API aggregated instead of embedding per item; "
                                "falling back to one call per page")
            vectors = []
            for content in contents:
                single = self._with_retry(lambda item=content: self._call([item]), what)
                returned = self._vectors_of(single)
                if len(returned) != 1:
                    raise EmbedCallFailed(
                        f"{what}: a single-item request returned {len(returned)} embeddings",
                        model=self.model, returned=len(returned),
                    )
                vectors.append(returned[0])

        for vector in vectors:
            if len(vector) != self.dim:
                raise EmbedDimMismatch(
                    f"{what}: the model returned dim {len(vector)} and this collection is built "
                    f"for {self.dim}. A dim change is a new collection plus a full re-embed plus "
                    f"an alias swap, never an in-place mix (§6.6)",
                    model=self.model, returned=len(vector), expected=self.dim,
                )
        return vectors

    def embed_pages(self, compositions: Sequence[Composition]) -> list[list[float]]:
        """One Content per page, ``batch_size`` per request, ``concurrency`` requests at a time."""
        if not compositions:
            return []
        batches = [list(compositions[start:start + self.batch_size])
                   for start in range(0, len(compositions), self.batch_size)]

        def run(batch: list[Composition]) -> list[list[float]]:
            return self._embed_contents([item.contents() for item in batch], "embed_pages")

        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            vectors = [vector for chunk in pool.map(run, batches) for vector in chunk]
        _log.info("embed_call", call="embed_pages", pages=len(vectors), batches=len(batches),
                  dim=self.dim, model=self.model)
        return vectors

    def embed_query(self, question: str) -> list[float]:
        """A text query. The optional instruction prefix is the only steer this model accepts."""
        instruction = EMBED_QUERY_INSTRUCTION
        text = f"{instruction}{question}" if instruction else question
        return self._embed_contents([types.Content(parts=[types.Part(text=text)])],
                                    "embed_query")[0]

    def embed_query_image(self, image: bytes, text: str | None = None) -> list[float]:
        """Ported from `impl` and wired for D12: an image as the query side of a search.

        The same call as the document side — this model has no query mode, so an image query lands
        in exactly the space the indexed pages occupy. Passing ``text`` puts both parts in **one**
        Content, which the model fuses into a single combined embedding (*"this photo, but the
        wiring detail"*): the aggregation behaviour avoided between pages, used deliberately here.

        **No instruction prefix** when the query is multimodal — Google advises against it, which
        is also why :data:`vsir.config.EMBED_QUERY_INSTRUCTION` is empty by default (D12, §7.2.1).
        """
        parts: list[types.Part] = []
        if text and text.strip():
            parts.append(types.Part(text=text.strip()))
        parts.append(types.Part.from_bytes(data=prepare_image(image), mime_type=IMAGE_MIME))
        return self._embed_contents([types.Content(parts=parts)], "embed_query_image")[0]


#: ``VSIR_VLM`` → the embedding backend that value selects, built unconditionally into the image
#: exactly as :data:`vsir.vlm.BACKENDS` is. One switch for "does this release make live model
#: calls": a run that replays S2 from a fixture cannot quietly spend on embeddings, and there is
#: no second variable to forget (§15 Factor X, D10).
EMBEDDERS: MappingProxyType = MappingProxyType({
    StubEmbedder.name: StubEmbedder.from_config,
    GeminiEmbedder.name: GeminiEmbedder.from_config,
})


def embedder(cfg: Config) -> Embedder:
    """The embedding backend ``VSIR_VLM`` names. One lookup, no branches."""
    try:
        build = EMBEDDERS[cfg.vlm]
    except KeyError:
        raise EmbedUnavailable(
            f"VSIR_VLM={cfg.vlm!r} names no embedding backend in this release "
            f"(available: {sorted(EMBEDDERS)})",
            vlm=cfg.vlm, available=sorted(EMBEDDERS),
        ) from None
    return build(cfg)


# ── step 09 (§6.1): the document's vectors, reusing every one that has not changed ───────────────

@dataclass(frozen=True)
class Embedding:
    """Step 09's output: the stamped records, their vectors, and what the run did not have to buy.

    ``records`` are the input records with ``provenance.embed_key`` filled in — the receipt that
    makes the *next* run free (register B5). Nothing else about them changes here.
    """

    records: tuple[PageRecord, ...]
    vectors: Mapping[str, list[float]]
    compositions: tuple[Composition, ...]
    #: ``page_id``s whose vector came back from the index unchanged, and those that cost a call.
    reused: tuple[str, ...] = ()
    billed: tuple[str, ...] = ()
    backend: str = ""
    model: str = ""
    dim: int = 0

    def composition(self, page_id: str) -> Composition:
        for composition in self.compositions:
            if composition.page_id == page_id:
                return composition
        raise KeyError(f"no composition for {page_id!r}")

    @property
    def text_dropped(self) -> int:
        """Characters of page text no composition carried. `impl` never counted these."""
        return sum(composition.text_dropped for composition in self.compositions)


def embed_document(backend: Embedder, records: Sequence[PageRecord], *, source: str | Path,
                   content_hash: str = "", doc_title: str = "", text_chars: int,
                   cached: Mapping[str, tuple[str, list[float]]] | None = None,
                   max_edge: int = EMBED_MAX_EDGE_PX) -> Embedding:
    """Compose every page, reuse every unchanged vector, and buy only the rest (§6.1 step 09).

    ``cached`` is ``{page_id: (embed_key, vector)}`` as the index already holds it
    (:func:`vsir.ingest.index.cached_vectors`) — the store is the index, so closing register B5
    adds no state anywhere (§15 Factor VI). A cached entry is reused only when its ``embed_key``
    equals the one this run computed, which means the composition, the composition version and the
    embedding model all match; anything else is a miss and is re-billed.
    """
    held = dict(cached or {})
    compositions: list[Composition] = []
    for record in records:
        raster = render.index_raster(source, record.page_no, content_hash=content_hash or None)
        compositions.append(compose(record, raster, doc_title=doc_title, text_chars=text_chars,
                                    max_edge=max_edge))

    keys = {composition.page_id: composition.key(backend.model) for composition in compositions}
    vectors: dict[str, list[float]] = {}
    reused: list[str] = []
    for composition in compositions:
        entry = held.get(composition.page_id)
        if entry and entry[0] == keys[composition.page_id] and len(entry[1]) == backend.dim:
            vectors[composition.page_id] = list(entry[1])
            reused.append(composition.page_id)

    outstanding = [item for item in compositions if item.page_id not in vectors]
    fresh = backend.embed_pages(outstanding)
    if len(fresh) != len(outstanding):
        raise EmbedCallFailed(
            f"embed_document asked for {len(outstanding)} vectors and got {len(fresh)}: a batch "
            f"that returns a different count than it was given is the aggregation failure the "
            f"per-item fallback exists to catch (D4)",
            expected=len(outstanding), returned=len(fresh), model=backend.model,
        )
    for composition, vector in zip(outstanding, fresh):
        if len(vector) != backend.dim:
            raise EmbedDimMismatch(
                f"{composition.page_id}: vector of dim {len(vector)}, collection is {backend.dim}",
                page_id=composition.page_id, returned=len(vector), expected=backend.dim,
            )
        vectors[composition.page_id] = list(vector)

    stamped = tuple(
        record.model_copy(update={
            "provenance": record.provenance.model_copy(
                update={"embed_key": keys[record.page_id]}),
        })
        for record in records
    )
    embedding = Embedding(
        records=stamped, vectors=vectors, compositions=tuple(compositions),
        reused=tuple(reused), billed=tuple(item.page_id for item in outstanding),
        backend=backend.name, model=backend.model, dim=backend.dim,
    )
    # A domain event, not `ingest_step`: the CLI owns the step stream for every step of §6.1, so
    # a module that logged one too would put the same step on the stream twice — and this function
    # is also called by the assertions, where it is a check rather than a step.
    _log.info("embed_document", backend=backend.name, model=backend.model, dim=backend.dim,
              pages=len(compositions), reused=len(reused), billed=len(outstanding),
              text_dropped=embedding.text_dropped, composition_version=COMPOSITION_VERSION)
    return embedding
