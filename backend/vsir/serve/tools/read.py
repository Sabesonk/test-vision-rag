"""
COMPREHEND — ``read(page_ids, question)`` (Spec §7.2.6). **The one tool that spends.**

Ported with changes from ``impl/app/retrieve.py::read``, and the changes are most of it.

What survives is the shape of the move: pages the caller already chose, one question, a bounded
answer, and codes stamped by **us** against the page's own text rather than claimed by the model.
`impl`'s docstring says why in one sentence — *"that is the fence against a plausible wrong part
number in a corpus where 8,414 code pairs differ by one character"* — and that sentence is the
reason this tool exists at all.

Five things are different, and each one closes something that was open:

* **There is a raster to reason over.** `impl`'s `read()` returned a 503 for **every** page,
  because the ``image_path`` on the record was written relative to the ingesting process's cwd and
  never resolved for a reader (register **A5**). There is no ``image_path`` here (§5.3): the page
  is re-rendered on demand from the document store through `serve/raster_cache.py`, which is
  U018's path and is the same one `GET /pages/{page_id}/image` serves.
* **The stamp is `verify`'s, not a second implementation of it.** `impl` stamped
  ``text_layer_backed`` from ``backs(raw, tokens)`` over a locally built ``token_set()`` — its own
  tokeniser, its own adjacency joins, and no relationship to the index anything else searched.
  Here every code goes through :func:`~vsir.core.verify.verify_claims`, which asks
  :func:`~vsir.core.exact.exact_filter` the question `lookup` asks, scoped to one page. One
  vocabulary — `present | absent | unverifiable` — one meaning, one code path (§7.2.4, F2).
* **`unverifiable` exists.** A boolean cannot say *"nobody could read this page"*, so `impl` said
  ``text_layer_backed: false`` about a scanned page — which reads as *"the model made that code
  up"*. On a page with no text layer **every** code here is `unverifiable`, forever if need be
  (R2), and that is the honest answer rather than a gap.
* **`sufficient` is mandatory.** `impl` returned an empty extract for *"the pages do not answer
  this"* and for *"the answer is no"* alike, and the two are the difference between looking again
  and stopping (§7.2.6).
* **Nothing is withheld and nothing is classified.** ``withheld[]``, ``id_class`` and the
  identifier grammar behind them are struck (§2.5 B): a code that failed its check is
  **returned, stamped**, never removed. Dropping it hides the transcription error from the only
  party that can act on it, and there is no grammar here that could decide what kind of thing a
  code names (§5.2 *Prohibited*).

**The dpi is pinned at 220 and is not a parameter** (§7.2.6, §4.2). It is an input to ``read_key``,
so a caller that could raise it could bill the same question three times and get three cache
misses for one answer. `fetch` is where a caller chooses a dpi, and `fetch` is free.

**Retrieval judgment never happens here** (§7.6). This module chooses no page, ranks nothing,
suggests nothing and returns no `next`: it is handed pages and a question, and it answers about
those pages or says it cannot. The caller chose them and the runner (U021, U022) decides what to
do about `sufficient: false` — an engine that picked its own evidence would be the answerer.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vsir import logging as vsir_logging
from vsir.config import DPI_ANSWER, Config
from vsir.core.record import UNSEARCHABLE_TRUST
from vsir.core.verify import ABSENT, PRESENT, UNVERIFIABLE, verify_claims
from vsir.ingest.extract import schema_hash
from vsir.serve import raster_cache
from vsir.serve.audit import Usage, page_ids_of
from vsir.serve.caps import validate_read_pages, validate_read_question
from vsir.serve.envelope import PageProvenance, Provenance, ReadCode, ReadResult, ToolEnvelope
from vsir.vlm import READ, Backend, ControlPlaneStore, Entry, Request, VlmSchemaInvalid, read_key

_log = vsir_logging.get_logger(__name__)


class ReadOut(BaseModel):
    """What the vision model is asked for, and the **only** thing it is allowed to decide.

    Three fields, and the two that are not here matter as much as the three that are: there is no
    per-code verification flag, because the model does not get to say whether it read a code
    correctly (I2, §7.2.6 Loop 1); and there is nothing in which it could name another page,
    because choosing pages is the caller's job (§7.6).

    ``extra="forbid"``: a paid response carrying a field this release did not ask for is something
    to refuse rather than to drop, exactly as it is for the S2 schema.
    """

    model_config = ConfigDict(extra="forbid")

    #: The bounded answer from these pages, empty when they do not contain one.
    extract: str = ""
    #: Every code read **on these pages** and used in the extract, verbatim. Stamped afterwards.
    codes: list[str] = Field(default_factory=list)
    #: Required, with **no default** (§7.2.6). A default would have to be one of the two answers
    #: the field exists to separate, and the safe-looking one — `False` — turns every response a
    #: model returned without it into *"wrong pages"*, which sends the agent looking again for
    #: something it has already been told.
    sufficient: bool


#: The value that goes into ``read_key`` (§6.3). Computed from the schema, never written by hand,
#: for the reason `extract.S2_SCHEMA_HASH` is: add a field and every read re-bills, which is the
#: honest answer, because the model was asked a different question.
READ_SCHEMA_HASH = schema_hash(ReadOut)

#: The disclosures a `read` can carry, and the whole list (§7.2.6's ``flags``). Closed, like
#: derivation's, because a flag nothing sets is a promise the response does not keep — and
#: **server-derived**, every one: the model has no field in which to raise one.
FLAG_NO_TEXT_LAYER = "no_text_layer"
FLAG_UNTRUSTED_TEXT = "untrusted_text"
FLAG_UNVERIFIED_CODES = "unverified_codes"
READ_FLAGS: tuple[str, ...] = (FLAG_NO_TEXT_LAYER, FLAG_UNTRUSTED_TEXT, FLAG_UNVERIFIED_CODES)


def parse(entry: Entry) -> ReadOut:
    """The verbatim body → a validated :class:`ReadOut`, or a typed refusal.

    A `read` is **not** bisected the way a window is (§6.2): there is no window to split, the
    caller named the pages, and the repair for a response that did not parse is to make the call
    again — not to answer about half the pages. So this raises, the dispatcher maps it onto a
    `502` under its own code, and the caller sees that the model answered unusably rather than
    that the pages hold nothing (§11.3).
    """
    try:
        return ReadOut.model_validate_json(entry.body)
    except ValidationError as failure:
        raise VlmSchemaInvalid(
            f"the read response does not validate against the schema this key was built from "
            f"({failure.error_count()} error(s), first: {failure.errors()[0].get('loc')} "
            f"{failure.errors()[0].get('msg')})",
            cache_key=entry.key, errors=failure.error_count(),
        ) from failure


def pages_of(page_ids: Sequence[str]) -> list[str]:
    """The caller's page list, de-duplicated with its order preserved.

    §7.3 bounds **pages**, and one page named twice is one page rendered once and one question
    asked once — so the bound is checked on what this leaves, and so is ``read_key``. The order is
    the caller's because it is the order the rasters are sent in, and a model shown the same pages
    in a different order is being asked a different question (§6.3).
    """
    return list(dict.fromkeys(page_ids))


def precheck(page_ids: Sequence[str], question: str) -> None:
    """Every bound that can be settled from the request alone (§7.3), before a cent is committed.

    Called by the dispatcher **before** the budget is charged, which is the whole reason it is a
    separate function: `read` is the one tool that spends, so a caller that named four pages must
    not have a read taken off its quota to be told it named four pages. Everything here is a
    property of the request — no store, no render, no model.
    """
    validate_read_pages(pages_of(page_ids))
    validate_read_question(question)


def _question_part(question: str, page_ids: Sequence[str]) -> str:
    """The call's one text part: the question, and which pages are in front of the model.

    Derived entirely from inputs that are already on ``read_key`` — the question itself and the
    pages whose image hashes the key is built from — so there is nothing in the call that the
    receipt does not describe. A timestamp, a run id or a session id here would make two identical
    calls different calls that the key still called the same (§6.3, F11).
    """
    listed = "\n".join(f"{ordinal}. {page_id}" for ordinal, page_id in enumerate(page_ids, 1))
    return f"Question: {question}\n\nThe pages above, in order:\n{listed}"


def _stamp(client: Any, collection: str, codes: Sequence[str],
           page_ids: Sequence[str]) -> list[ReadCode]:
    """Loop 1 (§7.2.6): every emitted code, phrase-checked against the pages, in emission order.

    The check is :func:`~vsir.core.verify.verify_claims` and nothing else — the same call
    `POST /tools/verify` makes, with the same folding and the same `present_instead` disclosure.
    An import-graph assertion in the L0 suite proves there is no second phrase-checker here,
    because a second one would be free to disagree with the index it is checking (F2).

    Codes are de-duplicated in emission order: a model that names ``K158`` in two sentences has
    read one code, and two identical stamps would let a caller count the evidence twice.
    """
    wanted = [code for code in dict.fromkeys(code.strip() for code in codes) if code]
    if not wanted:
        return []
    verdicts = verify_claims(client, collection, wanted, list(page_ids)).claims
    return [
        ReadCode(
            raw=code,
            status=verdicts[code].status,
            page_ids=list(verdicts[code].page_ids),
            present_instead=list(verdicts[code].present_instead),
            reason=verdicts[code].reason,
        )
        for code in wanted
    ]


def _flags(stamps: Sequence[ReadCode], payloads: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """The read's disclosures, from :data:`READ_FLAGS` and from the facts of this call."""
    trusts = {str(payload.get("text_trust") or "no_text") for payload in payloads.values()}
    raised = []
    if not all(payload.get("has_text", False) for payload in payloads.values()):
        raised.append(FLAG_NO_TEXT_LAYER)
    if trusts & (set(UNSEARCHABLE_TRUST) - {"no_text"}):
        raised.append(FLAG_UNTRUSTED_TEXT)
    if any(stamp.status != PRESENT for stamp in stamps):
        raised.append(FLAG_UNVERIFIED_CODES)
    return raised


def read(client: Any, cfg: Config, page_ids: Sequence[str], question: str, *,
         backend: Backend,
         provenance: Provenance,
         reads_remaining: int = 0) -> tuple[ToolEnvelope[ReadResult], Usage]:
    """One directed vision read of the named pages, and what it consumed for the audit line.

    Stateless in the way that matters: ``client`` and ``cfg`` are the store and the release's
    configuration, ``backend`` is the model boundary the release's ``VSIR_VLM`` chose, and
    ``provenance`` and ``reads_remaining`` come from the request context the caller owns. Nothing
    survives the call — the rasters live in the renderer's LRU and the response lives in the
    control plane under its key, and neither is on this instance's disk (§4.2, §15 Factor VI).

    The order is deliberate and it is the order the money is protected in:

    1. **the bounds**, from the request alone — the same :func:`precheck` the dispatcher already
       ran, repeated here because a tool must be correct when called directly (the MCP surface,
       `vsir read`, and U022's runner all reach this function);
    2. **resolution and the render**, which can still refuse — a page that is not in the corpus is
       a `404` and a document whose bytes are not mounted is a `503`, before any call is made;
    3. **the cache**, keyed on the pixels, the model, the prompt version, the dpi, the schema
       **and the question** (§6.3). A new question is a miss (F19) and an identical one costs
       nothing;
    4. **the call**, and only if steps 1–3 left one to make;
    5. **the stamp**, which is free and never optional (§7.2.6 Loop 1).
    """
    wanted = pages_of(page_ids)
    precheck(wanted, question)

    payloads = raster_cache.resolve_payloads(client, cfg, wanted)
    resolved = raster_cache.attach_sources(client, cfg, payloads)
    rasters = [raster_cache.raster(resolved[page_id], dpi=DPI_ANSWER) for page_id in wanted]

    key = read_key([raster.sha256 for raster in rasters], vlm_model=cfg.vlm_model,
                   prompt_version=cfg.prompt_version, dpi=DPI_ANSWER,
                   schema_hash=READ_SCHEMA_HASH, question=question)
    store = ControlPlaneStore(client, cfg.runs_collection)
    entry = store.get(READ, key)
    if entry is None:
        entry = backend.generate(Request(
            namespace=READ, key=key, stage="read", schema=ReadOut,
            images=tuple(raster.png for raster in rasters),
            hint=_question_part(question, wanted),
            label=f"read {len(wanted)} page(s)",
        ))
        store.put(entry, vlm_model=cfg.vlm_model, prompt_version=cfg.prompt_version)

    out = parse(entry)
    stamps = _stamp(client, cfg.pages_collection, out.codes, wanted)
    result = ReadResult(
        extract=out.extract,
        codes=stamps,
        sufficient=out.sufficient,
        flags=_flags(stamps, payloads),
        page_provenance=[
            PageProvenance(page_id=page_id,
                           text_trust=str(payloads[page_id].get("text_trust") or "no_text"))
            for page_id in wanted
        ],
    )

    # A cache hit consumed **nothing**, and the audit line has to say so in the fields an
    # operator sums. Reporting the original call's token counts beside `cache_hit: true` reads as
    # *"this call cost 2,858 input tokens"*, so a month of re-reads bills, in the ledger, exactly
    # as much as a month of first reads — which is the opposite of the fact §7.4 wants recorded.
    # The tokens are on the line of the call that actually bought them, once.
    usage = {} if entry.origin == "cache" else (entry.usage or {})
    _log.info("read", tool="read", pages=len(wanted), dpi=DPI_ANSWER, cache_key=key,
              origin=entry.origin, sufficient=out.sufficient, flags=result.flags,
              codes=len(stamps),
              # The distribution, never the codes and never the question: §15.1's retention row
              # keeps document content and caller content off the event stream, and the audit
              # line of §7.4 is the record that says what this call cost.
              present=sum(1 for stamp in stamps if stamp.status == PRESENT),
              absent=sum(1 for stamp in stamps if stamp.status == ABSENT),
              unverifiable=sum(1 for stamp in stamps if stamp.status == UNVERIFIABLE))
    return ToolEnvelope[ReadResult](
        # `ok` because the **call** ran (§7.1). `sufficient: false` is an answer, not an absence:
        # forced through Family A it would be an empty result and indistinguishable from an
        # outage, which is the confusion the two envelope families exist to end.
        status="ok",
        result=result,
        reads_remaining=reads_remaining,
        provenance=provenance,
    ), Usage(
        page_ids=page_ids_of(wanted),
        dpi=DPI_ANSWER,
        input_tokens=int(usage.get("prompt_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        # The one fact §7.4 wants about spend that the token counts do not carry: this call was
        # answered from a response already bought, so it cost nothing and billed nothing.
        cache_hit=entry.origin == "cache",
    )
