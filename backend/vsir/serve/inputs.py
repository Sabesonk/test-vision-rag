"""The eight input schemas of §7.2 — one declaration, published to both transports (§7.5).

These were defined inline in `serve/app.py`, beside the table that referenced them, with their
per-field notes written as ``#:`` comments. That placement was deliberate and it stopped being
right for two reasons.

**A ``#:`` comment reaches Sphinx and not the wire.** `mcp/server.py` publishes
``spec.request.model_json_schema()`` as each tool's ``input_schema``, so the notes explaining that
``image`` is base64, that ``exclude`` is *pages already rejected*, that ``inline=false`` returns a
reference — the things an agent needs in order to choose a move — were visible to a developer
reading this source and invisible to the model calling the tool. Every one is now a
``Field(description=...)``, which lands in ``model_json_schema()`` and therefore in the MCP tool
listing **and** in `/openapi.json` at once. Nothing about validation changed; what changed is that
the declaration is now legible to its callers.

**One module, two transports, and a third on the way.** The models are the shared contract between
HTTP, MCP, and the typed client a console generates from `/openapi.json`. Keeping them in the
1,500-line module that also holds the lifespan, the metrics renderer and every route made "the
request contract" something you had to know where to find.

What did **not** move is where these are *validated*: one table, one dispatcher, one place that
charges the budget and writes the audit line, and both transports go through it (§7.5).

**Why there is not a single Pydantic constraint in this file.** No ``ge``, no ``le``, no
``max_length``, no ``pattern`` — and that is the design, not an omission. §7.3's bounds have to
produce **their own codes** (`dpi_not_allowed`, `dpi_requires_region`, `skim_limit_exceeded`,
`read_page_cap_exceeded`) because an agent switches on them, and `serve/caps.py` is where they
live. A ``Field(le=25)`` on ``limit`` would turn `skim_limit_exceeded` into a generic
``422 validation_error`` naming a JSON pointer — the same information, in a shape nothing can
branch on. So this module declares **shape and meaning**; `caps.py` declares bounds. A field that
looks unconstrained here is constrained one layer in, under a name the caller can act on.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from vsir.config import DPI_INDEX, LOOKUP_CAP
from vsir.serve.tools.fetch import INCLUDE_ALL, PART
from vsir.serve.tools.skim import SKIM_LIMIT

# ── the shared field types (§5.1–5.3) ────────────────────────────────────────────────────────────
# Annotated aliases rather than repeated `Field(...)` calls: `page_ids` means the same thing on
# `verify`, `fetch` and `read`, and three copies of its description is three places for one of
# them to go stale. They carry description and examples only — see the module note on constraints.

DocId = Annotated[str, Field(
    description="The revision-stable document id (§5.1) — derived from the source filename at "
                "ingest step 01, not a run id and not a UUID.",
    examples=["TC1E-SF"])]

Revision = Annotated[str, Field(
    description="The document revision (§5.1). The operator's declared value is authoritative; "
                "empty means the revision that is currently published.",
    examples=["2024-03"])]

PageIdList = Annotated[list[str], Field(
    description="Page ids, named outright — `<doc_id>@<revision>#p<page_no>` (§5.2). These come "
                "from a `skim_*`, `lookup` or `resolve` hit; they are never constructed by hand, "
                "and a page id that is not in the index is a `404 page_not_found` rather than an "
                "empty result (§7.1).",
    examples=[["TC1E-SF@2024-03#p59", "TC1E-SF@2024-03#p60"]])]

ScopeFilter = Annotated[dict[str, Any], Field(
    default_factory=dict,
    description="An `INDEXED` filter (§5.4) — `doc_id`, `doc_type`, `subjects`, `tags`, "
                "`page_no`. Narrowing only: it cannot widen a search and it cannot reach a "
                "retired revision. A key outside `INDEXED` is refused as `filter_unknown_key` "
                "(I6, F10) and never silently dropped. The effective scope is echoed back in "
                "every response, because this service is stateless (C11).",
    examples=[{"doc_id": "TC1E-SF"}, {"doc_type": "manual", "subjects": ["TC1E"]}])]

ExcludeList = Annotated[list[str], Field(
    default_factory=list,
    description="Page ids this caller has already looked at and rejected, so the next rung "
                "returns something new. The agent's state lives in the agent (C11) — this "
                "service remembers nothing between calls.",
    examples=[["TC1E-SF@2024-03#p12"]])]

QueryText = Annotated[str, Field(
    default="",
    description="What to search for, in the technician's own words. Optional **only** when "
                "`image` is given; a call with neither is refused as `query_required` (§7.3).",
    examples=["torque spec for the spindle clamp"])]

QueryImage = Annotated[str, Field(
    default="",
    description="A base64-encoded photograph to search *with* — a picture of a panel or a "
                "nameplate, which is where a technician actually starts (D12). Base64 rather "
                "than multipart because a JSON body is where both transports meet: an MCP client "
                "hands `tools/call` a JSON object and cannot post a file. A malformed value is a "
                "typed 400 naming this field. It can never reach the exact surface — a "
                "photograph may *find* a candidate page, it can never *confirm* a code (I2, I3).")]


class ToolRequest(BaseModel):
    """Base for every tool body. ``extra="forbid"``, so a misspelt parameter is a `400`.

    Silently ignoring an unknown field is how a caller passes ``include_unverified=True`` as
    ``includeUnverified`` and is told, with a straight face, that the corpus does not contain it.
    """

    model_config = ConfigDict(extra="forbid")


class LookupRequest(ToolRequest):
    """``lookup(label, scope?, include_unverified=False, cap=20)`` — §7.2.2. JUMP.

    These models are also the **MCP input schemas** (§7.5): `mcp/server.py` publishes
    ``model_json_schema()`` for each row of the table rather than hand-writing a JSON Schema per
    tool, so an MCP client and an HTTP client are validated against the same declaration and a
    new parameter cannot reach one surface without reaching the other.
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "examples": [{"label": "1QP7", "scope": {"doc_id": "TC1E-SF"}}]})

    label: str = Field(
        description="The printed identifier, exactly as it appears on the page — a component tag, "
                    "an alarm number, a part code. Matched as a phrase over its variants and "
                    "**never fuzzily**: a near miss is an absence, not a nearest match, because a "
                    "code that is one character out is a different part (I3, F1).",
        examples=["1QP7", "A-4021"])
    #: Not a typed model: `INDEXED` is the schema, and `core.exact` refuses a key outside it with
    #: `filter_unknown_key` (I6, F10). A Pydantic mirror of `INDEXED` would be a second source of
    #: truth for the one dict that has three jobs (§5.4).
    scope: ScopeFilter
    include_unverified: bool = Field(
        default=False,
        description="Also return pages where the label was read off the image but is **not** in "
                    "the page's text layer. These arrive in a separate `unverified_hits` block "
                    "and never merge with `hits` — a code read from a picture is not a code found "
                    "in the text, and a surface that interleaved them would undo the guarantee "
                    "the index exists to make (D3, I2).")
    cap: int = Field(
        default=LOOKUP_CAP,
        description=f"Maximum hits to return (default {LOOKUP_CAP}). Bounded in `caps.py` so the "
                    f"refusal carries its own code.")


class VerifyRequest(ToolRequest):
    """``verify(claims, page_ids)`` — §7.2.4. CHECK.

    No ``scope``: the pages are named outright, so there is nothing to filter. No ``image``
    either, and that is I2/I3 rather than an omission — a photograph may *find* a candidate page,
    it can never *confirm* a code.
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "examples": [{"claims": ["1QP7", "24 V DC"],
                      "page_ids": ["TC1E-SF@2024-03#p59"]}]})

    claims: list[str] = Field(
        description="The strings to check against those pages' text — the codes and values a "
                    "draft answer is about to assert. Each comes back stamped `present`, `absent` "
                    "or `unverifiable`, and `absent` is never the same as `unverifiable`: the "
                    "first is a fact about the page, the second is a fact about our ability to "
                    "read it. Every claim absent is still a **successful** call.",
        examples=[["1QP7", "24 V DC"]])
    page_ids: PageIdList


class SkimPagesRequest(ToolRequest):
    """``skim_pages(query, image=None, scope, exclude?, limit=10)`` — §7.2.1. NARROW, page rung.

    ``query`` is optional **when ``image`` is given**, and vice versa; neither is a typed
    ``query_required`` from the tool rather than a validation error here, because *"a search with
    nothing to search for"* is a bound on the move and belongs with the other bounds (§7.3).

    ``image`` is base64 because a JSON body is where both transports meet: an MCP client hands
    `tools/call` a JSON object and cannot post multipart. It is the **query** side of a search and
    it can never reach the exact surface — `lookup` and `verify` have no such field, and
    ``extra="forbid"`` makes adding one to their bodies a `400` rather than a photograph deciding
    whether a code is printed (I2, I3, D12).
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "examples": [{"query": "spindle clamp torque", "scope": {"doc_id": "TC1E-SF"},
                      "limit": 10}]})

    query: QueryText
    image: QueryImage
    scope: ScopeFilter
    exclude: ExcludeList
    limit: int = Field(
        default=SKIM_LIMIT,
        description=f"Rows to return (default {SKIM_LIMIT}). A triage list an agent chooses from, "
                    f"not a page of a result set — bounded in `caps.py` under "
                    f"`skim_limit_exceeded`.")


class SkimAggregateRequest(ToolRequest):
    """``skim_documents`` / ``skim_sections`` — §7.2.1, and `skim_pages`' body minus ``limit``.

    **No ``limit``**, and that is the signature §7.2.1 declares rather than an omission: the two
    aggregate rungs return at most ten *groups*, full stop. A caller who wants more rows wants a
    different rung — `skim_pages` with a `limit` — and a `limit` here would let one call ask for
    every document in the corpus, which is the triage this rung exists to do, undone.

    Two bodies rather than one shared model with a `granularity` field: the tool name is what an
    agent chooses between (§7.2.1), and the MCP schema published for each name has to be the
    schema of *that* tool.
    """

    query: QueryText
    image: QueryImage
    scope: ScopeFilter
    exclude: ExcludeList


class SkimDocumentsRequest(SkimAggregateRequest):
    """``skim_documents(query, image=None, scope?, exclude?)`` — §7.2.1. The widest rung."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "examples": [{"query": "hydraulic pump maintenance interval"}]})


class SkimSectionsRequest(SkimAggregateRequest):
    """``skim_sections(query, image=None, scope, exclude?)`` — §7.2.1.

    §7.2.1 writes this rung's ``scope`` without the `?` `skim_documents` has, and it still
    defaults to empty here — exactly as `skim_pages`' does, whose signature is written the same
    way. An unscoped call is answered and told so: `needs_scope` is the server's judgement on
    whether the scope was wide enough (§7.1), computed from the pages searched and not from
    whether the caller passed a dict, and refusing here would be a second, weaker version of it.
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "examples": [{"query": "alarm codes", "scope": {"doc_id": "TC1E-SF"}}]})


class ResolveRequest(ToolRequest):
    """``resolve(printed_label, doc_id?)`` — §7.2.3. FOLLOW.

    A citation, not a query: no scope, no image.
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "examples": [{"printed_label": "see Fig. 4-12", "doc_id": "TC1E-SF"}]})

    printed_label: str = Field(
        description="A cross-reference as the page prints it — *\"see Fig. 4-12\"*, *\"Table 7\"*, "
                    "*\"page 118\"*. Resolved to the page that **is** that thing, which is why "
                    "this is a different move from `lookup`: the printed number is the "
                    "document's own numbering and not our `page_no` (§5.2).",
        examples=["Fig. 4-12", "Table 7"])
    doc_id: DocId = Field(
        default="",
        description="Resolve within this document. Empty resolves within whichever document the "
                    "reference was found in; a cross-document reference is ambiguous without it.",
        examples=["TC1E-SF"])


class FetchRequest(ToolRequest):
    """``fetch(page_ids, include, dpi=150, region=None, inline=True)`` — §7.2.5. LOOK.

    No ``scope``: the pages are named outright, so there is nothing to filter — the same reason
    `verify` has none. No ``image`` either: this tool *returns* rasters, it does not search with
    one.

    ``include`` is a list of `Literal`s rather than a free list of strings, so a fourth part name
    is an `invalid_request` naming the field instead of a word this service silently ignores — a
    caller that asked for ``"summaries"`` and received a page with no summary would conclude the
    page has none.

    ``dpi`` and ``region`` are plain values here and are bounded in `serve/caps.py`, not by
    Pydantic: §7.3's bounds have to produce **their own** codes (`dpi_not_allowed`,
    `dpi_requires_region`, `region_invalid`) because an agent switches on them, and a Pydantic
    ``Literal[36, 72, …]`` would produce a generic validation error instead.
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "examples": [{"page_ids": ["TC1E-SF@2024-03#p59"], "include": ["image", "text"],
                      "dpi": 150, "inline": False}]})

    page_ids: PageIdList
    include: list[PART] = Field(
        default_factory=lambda: list(INCLUDE_ALL),
        description="Which parts of each page to return: `image` (the raster), `text` (the page's "
                    "own text layer, carried through unmodified — I2), `summary` (the derived "
                    "one). A name outside this set is refused rather than ignored.",
        examples=[["image", "text"]])
    dpi: int = Field(
        default=DPI_INDEX,
        description=f"Render resolution (default {DPI_INDEX}, the dpi the index was built at). "
                    f"Escalate for a detail, and above 220 a `region` is **required** — a full "
                    f"page at 400 dpi exceeds the megapixel bound and an E-size drawing exceeds "
                    f"it at 220. Bounded in `caps.py` under `dpi_not_allowed` and "
                    f"`dpi_requires_region`.")
    #: Normalised ``[x0, y0, x1, y1]`` (D6) — the crop, rendered on demand, stored nowhere.
    region: list[float] | None = Field(
        default=None,
        description="A crop, normalised `[x0, y0, x1, y1]` in 0..1 (D6) — rendered on demand and "
                    "stored nowhere. This is the caller's claim about where on the page the "
                    "answer is, which is why `read` has no such parameter and `fetch`, which is "
                    "free, does.",
        examples=[[0.1, 0.42, 0.55, 0.78]])
    #: **Default true**, because an agent needs the pixels in its context and an MCP client cannot
    #: follow a URL. ``false`` returns the reference only, which is what the console uses (§7.2.5).
    inline: bool = Field(
        default=True,
        description="`true` embeds the raster as base64 in the response, because an agent needs "
                    "the pixels in its context and an MCP client cannot follow a URL. `false` "
                    "returns an `ImageRef` — about sixty bytes that render nothing until "
                    "dereferenced — which is what a browser wants, so a UI is not moving "
                    "megabytes through JSON twice (§7.1).")


class ReadRequest(ToolRequest):
    """``read(page_ids, question)`` — §7.2.6. COMPREHEND, and **the one tool that spends**.

    **There is no `dpi`.** The pinned answer dpi of 220 is an input to ``read_key`` (§6.3), so a
    caller that could raise it could ask one question three times and miss the cache three times.
    ``extra="forbid"`` makes a hopeful ``"dpi": 400`` an `invalid_request` naming the field rather
    than a parameter this service silently ignores — which is the honest half of *"a caller cannot
    change it"*: refused, not quietly dropped.

    No `region` either, for the same reason and one more: a crop is a claim about where the answer
    is on the page, and it is the caller's claim. `fetch` is where a caller crops, and `fetch` is
    free (§7.2.5).
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "examples": [{"page_ids": ["TC1E-SF@2024-03#p59"],
                      "question": "What is the tightening torque for the spindle clamp?"}]})

    page_ids: PageIdList = Field(
        description="The pages to reason over — **at most three**, and never zero. This is the "
                    "call that costs money, so the pages are the caller's deliberate choice made "
                    "from a free `skim_*` or `lookup`; a `read` with no pages could only be "
                    "answered from what the model already believes, which is the one thing this "
                    "system exists to keep out of an answer (§1.1). Bounded in `caps.py` under "
                    "`read_empty` and `read_page_cap_exceeded`.",
        examples=[["TC1E-SF@2024-03#p59"]])
    question: str = Field(
        description="The question to answer from those pages, and part of `read_key` (§6.3) — so "
                    "the same question over the same pages is a cache hit and a new question "
                    "always misses. Every code the answer contains comes back stamped "
                    "`present`/`absent`/`unverifiable` against the pages' own text, and "
                    "`sufficient` says whether these pages answer it on their own.",
        examples=["What is the tightening torque for the spindle clamp?"])


__all__ = [
    "DocId", "ExcludeList", "FetchRequest", "LookupRequest", "PageIdList", "QueryImage",
    "QueryText", "ReadRequest", "ResolveRequest", "Revision", "ScopeFilter",
    "SkimAggregateRequest", "SkimDocumentsRequest", "SkimPagesRequest", "SkimSectionsRequest",
    "ToolRequest", "VerifyRequest",
]
