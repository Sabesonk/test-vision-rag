"""`POST /search` — the flat retrieval surface: **data out, never an answer.**

Two consumers, one surface. An operator asking *why did page 40 come third?* — the question the
fusion's knobs exist for. And a caller that wants this service as a **search engine**: one
request, ranked pages with their content, and its own reasoning done elsewhere. Both want the
same thing from this module, which is the retrieval and nothing on top of it: no model call, no
judgement about whether the rows answer anything, no prose. `POST /ask` is the surface that
answers, and it is the only one (§7.4, §8.4).

**Why one call here is worth several of the tool ladder.** The eight tools of §7.2 are moves for
an agent that is *deciding* — and every decision costs the caller an inference turn, which is
seconds and a growing context. A consumer that has already decided it will reason for itself is
paying that for nothing. So this surface collapses the ladder: `include` returns each row's
summary, extraction, topics, codes, labels and sections beside its rank, and a caller that would
otherwise have run `skim_pages` then `fetch` runs neither.

**What it does not collapse is the honesty of the row.** Every row still states ``text_trust``
and ``has_text``, and that is load-bearing rather than decorative: on a scanned page ``text`` is
empty because *nobody could read the page*, not because the page is blank, and a consumer that
composes from these snippets without reading the flag produces a confident wrong part number on
exactly the documents this corpus is hardest about (§5.7, F4, R2). ``codes`` here are the model's
**claims** (D3), never verdicts — `verify` is the tool that settles a code against a page, and it
is free.


**Why this is not a ninth tool.** §7.2 fixes the agent's surface at eight, and the argument is the
one the MCP resources note makes: the eight are **moves**, and an agent choosing among nine where
one of them is "the same search, but with the lexical branch turned off" is being offered a knob,
not a move. Neither of this surface's consumers is choosing a move — the operator is turning a
knob and the search-engine caller is not using the ladder at all. So it lives here, off the tool
table, absent from MCP, and free.

That is also the whole reason `include` may return page text where a `skim_*` row may not (P2).
A triage row withholds content so an agent cannot answer from the search result instead of
choosing a page and paying for it; a caller that reached *this* path has declared it is doing its
own reasoning, and withholding the text would not make it safer — it would make it call `fetch`
twenty-five times for the same bytes. The bound that remains is size, not trust: `text_chars`
caps each row and states when it truncated.

**It is the same retrieval.** `_candidates()` is called directly, exactly as the three `skim_*`
rungs call it, with `weights` and `k` passed through. There is no second search, no second
fusion and no second scope filter — if this surface ranked differently from `skim_pages`, one of
the two would be lying about what the index does, and the whole point of a tuning surface is that
what you tune is what runs.

**What it adds, and the one thing it still refuses.** It publishes `surface_ranks` — each branch's
own ordinal position for each row — which `_candidates` has always computed and `PageHit` has
always discarded, keeping only the branch *names* in `why`. That is the honest form of *"why is
this here"*: dense put it 1st, lexical 7th, captions never found it.

There is still **no score**, and that is not an oversight to be corrected later (§7.6, and the
conformance grep that fails the build on a field named `score`). A magnitude invites a threshold,
a threshold turns *"ranked ninth"* into *"no results"*, and a fabricated abstention is the one
failure this system is built to make impossible. `_total()` — the RRF arithmetic — stays private
in `skim.py` for the same reason its own docstring gives: *"a number that escapes into a response
is a score somebody eventually displays."* Ordinals are published; the magnitude that ordered
them is not.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from qdrant_client.http import models as qm

from vsir.config import RRF_K, SURFACE_WEIGHTS
from vsir.config import DPI_INDEX
from vsir.core import ids
from vsir.core.exact import UnknownScopeKey, exact_filter
from vsir.core.indexed import INDEXED, TEXT_FIELDS, reject_unknown_keys
from vsir.core.record import UNSEARCHABLE_TRUST, TextTrust
from vsir.core.status import Status
from vsir.serve.caps import MAX_SKIM_LIMIT, ToolError, as_tool_error, validate_skim_limit
from vsir.serve.envelope import ImageRef, NextMoves, SupersededIn
from vsir.serve.tools.lookup import absence, image_ref
from vsir.serve.tools.skim import WHY, WHY_ORDER, _candidates, _next_moves

#: The facets a caller may filter on — `INDEXED` minus the two text surfaces, which are reachable
#: only through `lookup` and `verify`. Published in the schema so a generated client carries the
#: vocabulary instead of discovering it from a `filter_unknown_key` at run time.
FILTER_KEYS: tuple[str, ...] = tuple(k for k in INDEXED if k not in TEXT_FIELDS)

#: The three branches, under the names a caller uses. `page` is the dense vector's name in
#: :data:`~vsir.config.SURFACE_WEIGHTS`; `dense` is what §7.2.1 calls it in `why`. Both are
#: accepted so a caller can copy a name out of a `why` list and put it straight into `weights`.
BRANCHES: tuple[str, ...] = ("dense", "lexical", "captions")

#: `dense` → `page`, and the two sparse surfaces to themselves.
_INTERNAL = {"dense": "page", "page": "page", "lexical": "lexical", "captions": "captions"}

#: Photographs one query may fuse. A bound with its own code, like every other bound here: the
#: parts all go into **one** `Content`, so every image is input to a single embedding call, and a
#: caller that posted forty would be paying for one very large request whose vector describes an
#: average of everything on a workbench. Four is a technician's panel, nameplate, wiring detail
#: and error display — past that the query has stopped being about one thing.
MAX_QUERY_IMAGES = 4

#: How many phrases one `require_phrases` / `exclude_phrases` list may carry. Each one is an
#: indexed phrase condition ANDed into every branch's filter, so the cost is real but modest; the
#: bound exists because a caller sending forty terms has stopped filtering and started writing a
#: query, and the two want different surfaces.
MAX_PHRASE_TERMS = 10

#: A bound on `k`, with its own code. RRF's `k` damps the head of each branch; at 0 the top rank
#: dominates absolutely and at a few thousand every rank is nearly equal, so both ends are a
#: different retrieval rather than a tuned one.
MAX_RRF_K = 1000

#: The per-row content parts a caller may ask for. **`text` is the one that is not free** — it is
#: not in `skim.ROW_PAYLOAD`, so it costs one bounded `retrieve` over the rows actually returned.
#: The other five are already projected by `_candidates` and thrown away today.
PARTS: tuple[str, ...] = ("summary", "text", "topics", "codes", "labels", "sections")

#: The default per-row cap on returned page text, in characters. A 1,440-page manual's page can
#: carry several thousand characters of extraction; twenty-five of them unbounded is a multi-megabyte
#: response that a caller asked for by typing `"text"`. Truncation is **stated per row**
#: (`text_truncated`), never silent — a consumer that reasoned over a page it thought it had all of
#: is the failure this field exists to prevent.
DEFAULT_TEXT_CHARS = 2000

#: The hard ceiling on `text_chars`, past which a caller wants `fetch` (which returns one page's
#: whole text and states its trust) rather than a search row.
MAX_TEXT_CHARS = 20000

#: How deep `offset` may page into the fused list. `BRANCH_DEPTH` bounds the candidate pool each
#: branch contributes, so the fused list has an end — and paging past it returns nothing because
#: there is nothing, not because the corpus is exhausted. `available` reports the edge on every
#: response, and this bound refuses the offsets that could only ever be empty.
MAX_OFFSET = 200


#: Everything, spelled out, so a reader sees each parameter in context. Deliberately the **first**
#: example: it is what Swagger drops into its request box.
EVERY_PARAMETER = {
    "query": "reset procedure K158",
    "scope": {"doc_id": "SICK-DETECTOR-BOX", "page_kind": ["prose", "table"], "lang": "en"},
    "exclude_scope": {"page_kind": ["cover", "toc"]},
    "page_from": 10, "page_to": 60,
    "exclude": ["SICK-DETECTOR-BOX@3.0#p007"],
    "require_phrases": ["safety output"],
    "exclude_phrases": ["draft"],
    "include": ["summary", "text", "codes", "labels", "sections", "topics"],
    "text_chars": 2000, "limit": 10, "offset": 0,
    "weights": {"dense": 1, "lexical": 1, "captions": 0.4}, "k": 60,
}

#: The smallest body that works. Omitting `include` returns every content part.
MINIMAL = {"query": "response time of the safety output"}

#: An operator finding out *why* a page ranked where it did, by running one branch alone.
ISOLATE_ONE_BRANCH = {"query": "safety output", "include": [],
                      "weights": {"dense": 0, "lexical": 1, "captions": 0}}

#: A photograph with words. An image-only query runs the dense branch alone (D12).
WITH_A_PHOTOGRAPH = {"query": "this connector", "images": ["<base64 jpeg>"], "limit": 5}

#: The four, named for the UI's dropdown — a label a reader can choose between beats "Example 2".
REQUEST_EXAMPLES = {
    "every_parameter": {
        "summary": "Every parameter, in context",
        "description": "All fourteen controls. Only `query` (or an image) is required; every "
                        "other field here is showing its own default or a plausible value.",
        "value": EVERY_PARAMETER},
    "minimal": {
        "summary": "The minimum",
        "description": "Just something to search for. `include` omitted returns all six content "
                        "parts.",
        "value": MINIMAL},
    "isolate_one_branch": {
        "summary": "Tuning — run one branch alone",
        "description": "A branch weighted 0 is switched off. `include: []` returns metadata only. "
                        "This is how an operator finds out why a page ranked where it did.",
        "value": ISOLATE_ONE_BRANCH},
    "with_a_photograph": {
        "summary": "With a photograph",
        "description": "Images fuse with the text into **one** query vector. An image can never "
                        "reach the exact surface: it may find a page, never confirm a code.",
        "value": WITH_A_PHOTOGRAPH},
}


class SearchRequest(BaseModel):
    """The flat surface's body: every knob the fusion has, and nothing the tools do not already do.

    ``extra="forbid"`` for the reason every request model here does it: a misspelt parameter that
    was silently ignored is how a caller is told, with a straight face, that the corpus does not
    contain what it asked about. A wrong key names itself in the refusal.

    **The only required content is something to search for** — `query`, an image, or both. Every
    other field has a default that is the sensible one, and `include` omitted means *all* of it.
    """

    # **The fully-populated body is first, and that ordering is load-bearing.** Swagger renders
    # `examples[0]` into its Try-it-out box, so a minimal example in this slot makes a
    # fourteen-parameter surface look like it takes one field — which is exactly how a reader
    # concludes there are no other controls. The route publishes these again as *named* examples
    # (`openapi_extra` in `serve/app.py`) so the UI offers a labelled dropdown rather than
    # "Example 1"; this list is what a plain schema reader sees.
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        EVERY_PARAMETER,
        MINIMAL,
        ISOLATE_ONE_BRANCH,
        WITH_A_PHOTOGRAPH,
    ]})

    query: str = Field(default="", description="The text to search for. Optional only when "
                                               "`image` is given.")
    image: str = Field(default="", description="A single base64 photograph — the one-image case. "
                                               "Use `images` for more than one; giving both is a "
                                               "typed refusal rather than a silent choice.")
    images: list[str] = Field(
        default_factory=list, json_schema_extra={"maxItems": MAX_QUERY_IMAGES},
        description="Several base64 photographs, **fused with `query` into one combined query "
                    "vector** — not one search per image. Every part goes into a single embedding "
                    "call, so *\"this panel, this nameplate, and the words 'wiring detail'\"* is "
                    "one query about one thing. Order is preserved and is part of the query. "
                    f"At most {MAX_QUERY_IMAGES}.\n\nAny photograph switches the search "
                    "multimodal: an image-only query runs the **dense branch alone**, because "
                    "there is no text to build a sparse vector from — `branches_run` will say so. "
                    "A photograph can never reach the exact surface (I2, I3): it may *find* a "
                    "candidate page, it can never *confirm* a printed code.")
    scope: dict[str, Any] = Field(
        default_factory=dict,
        json_schema_extra={"propertyNames": {"enum": list(FILTER_KEYS)}},
        description="The facets every branch searches inside. A scalar matches that value, a "
                    "list matches **any** member — which is what makes `section_id` and "
                    "`series_id` work, since a page straddling two sections is in scope for "
                    "either.\n\n"
                    "**The keys, in full:** `doc_id` (a binder), `revision`, `is_current`, "
                    "`doc_type`, `subjects`, `tags`, `page_kind` (`prose` · `table` · `diagram` · "
                    "`cover` · `toc`), `lang`, `page_no` (an exact page — use `page_from`/"
                    "`page_to` for a range), `section_id` (hand back a row's own, or a row's "
                    "`next.expand`), `series_id` (a section followed across revisions), "
                    "`has_text`, `text_trust` (`ok` · `degraded` · `untrusted` · `no_text`), "
                    "`run_id`. Nothing else: `text` and `vlm_codes` are searched through `query` "
                    "and through `lookup`, never as a filter.\n\n"
                    "A key outside that list is `filter_unknown_key` (400) naming it, never a "
                    "filter that quietly did not apply. `is_current: true` is injected unless you "
                    "override it, so a retired revision is never searched by accident.\n\n"
                    "`GET /documents` lists the `doc_id`s and revisions actually held.",
        examples=[{"doc_id": "SICK-DETECTOR-BOX", "page_kind": ["table", "diagram"]}])
    exclude: list[str] = Field(default_factory=list, description="Page ids to suppress.")
    limit: int = Field(
        default=10, json_schema_extra={"minimum": 1, "maximum": MAX_SKIM_LIMIT},
        description=f"Rows to return from this page of the ranking, 1…{MAX_SKIM_LIMIT}. Outside "
                    f"that it is `limit_out_of_range` — refused rather than clamped, because a "
                    f"caller handed 25 of the 100 rows it asked for would believe it had seen "
                    f"100.")
    weights: dict[str, float] | None = Field(
        default=None,
        description="Per-branch weight over `dense`, `lexical`, `captions`. **A branch weighted "
                    "0 is switched off** and contributes nothing, not even its name in `why` — "
                    "so `{\"lexical\": 1, \"dense\": 0, \"captions\": 0}` is a lexical-only "
                    "search and `{\"dense\": 1, \"lexical\": 0, \"captions\": 0}` is dense-only. "
                    "Omitted uses the release defaults, which is what every `skim_*` runs.",
        examples=[{"dense": 0, "lexical": 1, "captions": 0}])
    k: int = Field(default=RRF_K, json_schema_extra={"minimum": 0, "maximum": MAX_RRF_K},
                   description=f"RRF's damping constant (default {RRF_K}). Smaller lets one "
                               f"branch's top hit dominate; larger flattens the branches toward "
                               f"each other.")
    include: list[str] | None = Field(
        default=None,
        json_schema_extra={"items": {"type": "string", "enum": list(PARTS)}},
        description="Per-row content to return, any of `summary`, `text`, `topics`, `codes`, "
                    "`labels`, `sections`.\n\n"
                    "**Omit it and you get all six** — this surface exists to hand a consuming "
                    "system the data, and defaulting to nothing meant a caller who did not know "
                    "the parameter existed got rows with `content: null` and no way to guess why. "
                    "Pass `[]` explicitly for metadata only, which is what a tuning call wants.\n\n"
                    "`text` is the page's full extraction, capped by `text_chars`, and it is the "
                    "one part that costs a second bounded lookup. Every row carries `text_usable` "
                    "and `text_trust` beside its content, because an empty `text` on a scanned "
                    "page means nobody could read the page — not that it is blank (§5.7). Asking "
                    "for content does not make this a `read`: nothing is interpreted, nothing is "
                    "billed, no model is called.",
        examples=[["summary", "text", "codes"], []])
    text_chars: int = Field(
        default=DEFAULT_TEXT_CHARS,
        json_schema_extra={"minimum": 1, "maximum": MAX_TEXT_CHARS},
        description=f"Characters of page `text` per row, 1…{MAX_TEXT_CHARS} (default "
                    f"{DEFAULT_TEXT_CHARS}). Truncation sets `content.text_truncated` on the row "
                    f"rather than passing a clipped page off as a whole one.")
    offset: int = Field(
        default=0, json_schema_extra={"minimum": 0, "maximum": MAX_OFFSET},
        description=f"Rows to skip in the fused ranking, 0…{MAX_OFFSET}. The ordering is "
                    f"deterministic (§16), so paging is stable across calls. The fused list has "
                    f"an **end** — each branch contributes a bounded candidate pool — so check "
                    f"`available`: an empty page at a high offset means the pool ran out, not "
                    f"that the corpus did.")
    page_from: int | None = Field(
        default=None,
        description="Lowest `page_no` to search, inclusive. A range the `scope` vocabulary cannot "
                    "spell: `scope` matches a value or any-of a list, never an interval.")
    page_to: int | None = Field(
        default=None, description="Highest `page_no` to search, inclusive.")
    require_phrases: list[str] = Field(
        default_factory=list,
        json_schema_extra={"maxItems": MAX_PHRASE_TERMS},
        description="Keyword filter: every phrase here **must be printed on the page**, or the "
                    "page cannot appear at any rank. Terms are ANDed.\n\n"
                    "This is a *filter*, not a query. Words in `query` influence ranking and a "
                    "page can rank well without carrying all of them; a phrase here is a hard "
                    "requirement. It goes through the same exact-match path as `lookup`, so "
                    "matching is **phrase** matching — `\"safety output\"` needs those words "
                    "adjacent and in that order, not merely both somewhere on the page — and each "
                    "term also matches its whitespace variants, so `\"SF 1.1A\"` finds "
                    "`\"SF1.1A\"`.\n\n"
                    "**It can only ever match a page whose text could be read.** A page with no "
                    "text layer, or one whose extraction is untrusted, carries nothing for a "
                    "phrase to match, so every such page is excluded — silently, because it was "
                    "never a candidate. Compare `pages_searched` with `searchable_pages` to see "
                    "how many pages that removed, and do not read an empty result as *'the "
                    "corpus does not contain this'* when the difference is large: that is the "
                    "one mistake this whole service is built to prevent (§5.7, F4).",
        examples=[["safety output"], ["response time", "SF 1.1A"]])
    exclude_phrases: list[str] = Field(
        default_factory=list,
        json_schema_extra={"maxItems": MAX_PHRASE_TERMS},
        description="The negation of `require_phrases`: a page printing any of these is dropped.\n\n"
                    "Note the deliberate asymmetry with `require_phrases`. A page with no text "
                    "layer cannot be shown to carry a phrase, so it is **kept** here and "
                    "**dropped** there. Both directions are the safe one: an exclusion errs "
                    "towards showing you a page you may not want, and a requirement never claims "
                    "a page qualifies on evidence nobody could read.",
        examples=[["superseded", "draft"]])
    exclude_scope: dict[str, Any] = Field(
        default_factory=dict,
        description="The negation of `scope`, over the same `INDEXED` keys — "
                    "`{\"page_kind\": [\"cover\", \"toc\"]}` searches everything that is "
                    "neither. A key outside `INDEXED` is `filter_unknown_key`, exactly as in "
                    "`scope`: a negation that quietly did not apply returns a *larger* answer "
                    "that looks like a filtered one.",
        examples=[{"page_kind": ["cover", "toc"]}])


class NextAction(BaseModel):
    """One operation this row affords, with the arguments already assembled.

    **The point is that a consuming system does not compose a call.** It reads `target` and posts
    `arguments` verbatim. A page id contains an ``@`` and a ``#`` (§5.1), so every hand-built URL
    or body is a chance to get the encoding wrong and produce a request that is well-formed and
    addresses nothing — which then looks like an empty result rather than a client bug.

    ``spends`` is the field to branch on before calling: exactly one operation in this service
    bills a model call, and it is never reached by accident.
    """

    model_config = ConfigDict(extra="forbid")

    action: str = Field(description="What this does: `fetch_material`, `comprehend`, "
                                    "`check_codes`, `expand_section`, `open_page_image`.")
    method: str = Field(default="POST")
    target: str = Field(description="The path to call, ready to use.")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="The body to post, already assembled for this page.")
    spends: bool = Field(
        default=False,
        description="True only for `comprehend` (`read`), the one operation in this service that "
                    "bills a vision call. Everything else here is free.")
    detail: str = Field(default="", description="What you get back, and when to prefer it.")


class SectionRef(BaseModel):
    """One section this page belongs to, after stitching (§6.1 step 07).

    A typed row rather than a loose object, because a consuming system reads `page_range` as two
    integers and `section_id` as the value it can pass straight back as a `scope`.
    """

    model_config = ConfigDict(extra="forbid")

    section_id: str
    title: str = ""
    series_id: str = Field(default="", description="The id that survives a revision boundary — "
                                                    "use it to follow a section across revisions.")
    page_range: list[int] | None = Field(
        default=None, description="`[first, last]` pdf page numbers of the section after "
                                  "stitching, or null where stitching could not settle one.")


class SkippedBranch(BaseModel):
    """A retrieval branch that did not run, and why — so a thin result is explicable.

    The single most common support question about a fused search is *"why didn't it find X?"*, and
    the answer is very often that the branch which would have found it never ran. An image-only
    query has no text to build a sparse vector from; a query that is only an identifier has
    nothing left to embed once the code goes to the phrase filter; a branch weighted `0` is off.
    Stating it removes the guesswork rather than leaving it to be inferred from `branches_run`.
    """

    model_config = ConfigDict(extra="forbid")

    branch: str
    reason: str = Field(description="`no_query_text`, `nothing_left_to_embed`, or `weighted_zero`.")
    detail: str


class QueryInterpretation(BaseModel):
    """How this service read the query — the explanation behind the row set.

    A caller sends one string; this service splits it in two before anything is retrieved, and the
    split changes the answer completely. `"reset K158"` becomes the **phrase filter** `K158` — an
    exact match over the one code path, so only pages that actually print it can rank — and the
    prose `reset`, which is what reaches the embedding. A consuming system that cannot see the
    split cannot tell a scoping result from a semantic one, and will misreport both.
    """

    model_config = ConfigDict(extra="forbid")

    identifiers: list[str] = Field(
        default_factory=list,
        description="Codes lifted out of the query and required as an exact phrase. Two are "
                    "ANDed. A page that does not print them cannot appear at any rank, however "
                    "semantically close — so an unexpected identifier here is the usual reason a "
                    "result is narrower than expected.")
    identifier_matching: str = Field(
        default="phrase",
        description="Always `phrase`: `\"SF 1.1A\"` matches the ordered phrase and never the "
                    "pages that merely carry `sf` and `1` somewhere.")
    embedded_text: str = Field(
        default="", description="What was left for the embedding after the identifiers came out. "
                                "Empty with an image is legal; empty with neither is "
                                "`query_required`.")
    branches_run: list[str] = Field(default_factory=list)
    branches_skipped: list[SkippedBranch] = Field(default_factory=list)
    required_phrases: list[str] = Field(
        default_factory=list,
        description="The keyword filters in force — every one of these had to be printed on a "
                    "page for it to appear at all. The first thing to check when a result is "
                    "narrower than expected, and the reason a scanned page cannot be in it.")
    excluded_phrases: list[str] = Field(
        default_factory=list, description="Phrases whose presence dropped a page.")
    query_images: int = Field(
        default=0,
        description="Photographs fused into **one** query vector. Above 0 the search is "
                    "multimodal; with no text it also means the dense branch ran alone, and every "
                    "row's `why` is `[\"dense\"]` — weaker evidence than a `lexical` hit. An "
                    "image can never reach the exact surface: it may find a page, never confirm a "
                    "code.")


class RowContent(BaseModel):
    """The page's own content, returned because `include` asked for it — never interpreted.

    **Every field is `null` unless its part was requested**, and that is the whole discipline of
    this model: `text: null` means *you did not ask*, while `text: ""` means *the page's
    extraction is empty* — which on a scanned page means nobody could read it. Collapsing those
    two into one falsy default is how a consuming system concludes a page is blank when it simply
    never requested the text (§7.1's argument, applied one level down from `status`).

    **Why content is served here and not on a `skim_*` row.** P2 keeps page text off a triage row
    so an agent cannot answer from the search result instead of choosing a page and paying for it.
    This surface is not a tool: a caller that reached it has declared it is doing its own
    reasoning, and withholding the text would only make it call `fetch` twenty-five times.

    What keeps the content honest is the row's `text_usable` and `text_trust`. Nothing here is
    verified — a code in `codes` is one the model claimed. `verify` settles that, and it is free.
    """

    model_config = ConfigDict(extra="forbid")

    summary: str | None = Field(
        default=None,
        description="The page summary in the language `scope.lang` asked for, else the page's "
                    "dominant one (D5). `null` = not requested.")
    summary_lang: str | None = Field(
        default=None, description="Which language `summary` is in — stated rather than left to be "
                                  "guessed from the words.")
    text: str | None = Field(
        default=None,
        description="The page's extracted text, capped by `text_chars`. `null` = not requested; "
                    "`\"\"` = requested and the page has none, which on a page with no text "
                    "layer means **nobody could read it**, not that it is blank. Gate on the "
                    "row's `text_usable` before using this.")
    text_truncated: bool | None = Field(
        default=None, description="Whether `text` was cut at `text_chars`. `null` = not requested.")
    text_chars_total: int | None = Field(
        default=None,
        description="The page's full extraction length, so a truncated row says how much it is "
                    "missing. `null` = not requested.")
    topics: list[str] | None = Field(default=None, description="`null` = not requested.")
    codes: list[str] | None = Field(
        default=None,
        description="Codes the model reported on this page — **claims, not evidence** (D3). "
                    "Verbatim, exactly as the model emitted them and never normalised (§5.2). "
                    "Not a verdict: `verify` is the tool that settles a code against a page, and "
                    "it is free. `null` = not requested; `[]` = none reported.")
    codes_in_text: list[str] | None = Field(
        default=None,
        description="The subset of `codes` the page's own extraction backs — **lowercased, "
                    "whitespace-collapsed and sorted** (§6.8), because that is the form "
                    "membership was decided in. `codes` is verbatim, so **compare the two "
                    "case-insensitively**: `\"SF 1.1A\"` is backed when this list holds "
                    "`\"sf 1.1a\"`. Matching them exactly would find nothing and read as *'the "
                    "text backs none of these codes'*, which is the opposite of the truth.")
    printed_page_no: str | None = Field(
        default=None,
        description="The label printed on the page. Empty where the label is ambiguous — then "
                    "`label_candidates` carries every reading. `null` = not requested.")
    label_verified: bool | None = Field(
        default=None, description="The page's own text layer prints this label (§6.5).")
    interpolated: bool | None = Field(
        default=None,
        description="The label was inferred from the pages either side, not read off this one "
                    "(§6.5). Treat such a label as weaker evidence when citing.")
    label_candidates: list[str] | None = Field(
        default=None,
        description="Populated only where the page's printed label is ambiguous, and then "
                    "`printed_page_no` is empty rather than a silent pick (F5).")
    sections: list[SectionRef] | None = Field(
        default=None,
        description="The sections this page belongs to after stitching. A page straddling two "
                    "carries both. `null` = not requested.")


class SearchRow(BaseModel):
    """One page, with the positions that put it there — and no magnitude (§7.6)."""

    model_config = ConfigDict(extra="forbid")

    rank: int = Field(description="Ordinal position after fusion, 1-based. **A position, not a "
                                  "confidence**: rank 1 does not mean 'correct', and rank 9 does "
                                  "not mean 'no'.")
    page_id: str = Field(description="The addressable id — `{doc_id}@{revision}#p{page_no}`. Pass "
                                     "it to `fetch`, `read` or `verify` verbatim; it contains "
                                     "`@` and `#`, so use the assembled `actions` rather than "
                                     "building a URL from it.")
    doc_id: str = Field(default="", description="Parsed from `page_id`, so a consumer does not "
                                                "have to split the id itself.")
    revision: str = Field(default="", description="The revision this page belongs to. Every row "
                                                  "is from a current revision unless you "
                                                  "overrode `is_current` in `scope`.")
    page_no: int = Field(default=0, description="The pdf page number — the position in the file, "
                                                "which is **not** the printed label.")
    printed_page_no: str = Field(
        default="",
        description="The label printed on the page, which frequently disagrees with `page_no`: "
                    "no fixed offset exists in this corpus because numbering restarts at "
                    "chapters. Cite this, address by `page_id`.")
    page_kind: str = Field(default="", description="`prose`, `table`, `diagram`, `cover`, `toc`, "
                                                    "…  — filterable via `scope.page_kind`.")
    why: list[str] = Field(default_factory=list,
                           description="The branches that found this page, in a fixed order.")
    surface_ranks: dict[str, int] = Field(
        default_factory=dict,
        description="Each branch's **own** ordinal for this page — `{\"dense\": 1, "
                    "\"lexical\": 7}`. A branch absent here did not return the page at all, "
                    "which is a different fact from returning it last. This is what the fusion "
                    "actually consumed.")
    best_rank: int = Field(description="The best position any single branch gave it.")
    text_trust: TextTrust = Field(
        default="no_text",
        description="How far this page's extracted text may be believed (§5.7). `ok` — believe "
                    "it. `degraded` — partly unreliable. `untrusted` — a phrase match inside it "
                    "is not evidence. `no_text` — there is no text layer, so nobody could read "
                    "the page. The last two are **unsearchable**: a claim about such a page comes "
                    "back `unverifiable`, never `absent`, because the page was not read, which is "
                    "a different fact from the code not being on it (I2). A stored value outside "
                    "these four is reported as `no_text`, the conservative direction — an unknown "
                    "state is never rendered as trust.")
    text_usable: bool = Field(
        default=False,
        description="**The one field to gate on before using `content.text`.** True when "
                    "`text_trust` is `ok` or `degraded`; false for `untrusted` and `no_text`, the "
                    "two §5.7 calls unsearchable. It is not the same as `has_text`: an "
                    "`untrusted` page *has* text and the text may not be believed. A consumer "
                    "that composes an answer from `text` without checking this produces a "
                    "confident wrong result on exactly the pages this corpus is hardest about.")
    has_text: bool = Field(
        description="Whether the page has a text layer at all. Derived from `text_trust`, which "
                    "is exact rather than approximate: `core/health.py` returns `no_text` **iff** "
                    "the page has none, and its own docstring records that `no_text` is final and "
                    "nothing promotes it. Not read from the payload's own `has_text`, because "
                    "`ROW_PAYLOAD` does not project that field — reading it there returned `false` "
                    "for every row, which is the most misleading answer this surface could give.")
    grounded_rate: float | None = None
    section_id: list[str] = Field(
        default_factory=list,
        description="Every section this page belongs to — a page straddling two carries both. "
                    "Hand one straight back as `scope.section_id` to search inside it.")
    image: ImageRef = Field(
        description="A **reference** to the page raster, never the pixels: `url` at the index "
                    "dpi, `thumb_url` for a list, and both already percent-encoded. `width` and "
                    "`height` stay 0 until something renders — reporting a size here would mean "
                    "rendering the page to answer a search. For the bytes themselves call "
                    "`fetch`, which is free.")
    image_url: str = Field(
        default="",
        description="Shorthand for `image.url`, kept so a caller that only wants to show the page "
                    "does not have to reach into the reference.")
    next: NextMoves = Field(
        description="Where to go from this page without inventing anything: `expand` is a "
                    "**scope** to hand straight back (the section this page is in), `neighbours` "
                    "are the page ids either side, and `references` is reserved for printed "
                    "cross-references — empty, because scraping them out of page text at query "
                    "time is the one thing that makes a citation follow to the wrong page.")
    actions: list[NextAction] = Field(
        default_factory=list,
        description="The operations available on this page, arguments already assembled. Read "
                    "`spends` before calling: only `comprehend` bills.")
    content: RowContent | None = Field(
        default=None,
        description="Present only when `include` asked for something. Absent — not an empty "
                    "object — when it did not, so a caller can tell *\"I did not ask\"* from "
                    "*\"the page has none\"*.")


class SearchResult(BaseModel):
    """The ranked page list, why it looks the way it does, and what was searched to produce it.

    **Read `status` first.** An empty `rows` is never just "no results": it is one of four
    different facts with four different next actions, and a consuming system that collapses them
    will report "not in the documents" about a page nobody could read (§7.1, F4).
    """

    model_config = ConfigDict(extra="forbid")

    status: Status = Field(
        description="What kind of result this is — **the field to branch on**.\n\n"
                    "* `ok` — rows were ranked. Use them.\n"
                    "* `not_found` — the scope was searched and nothing matched. Safe to abstain, "
                    "but check `query_interpretation.identifiers` first: an identifier lifted out "
                    "of the query is a hard filter, and a typo in it empties the result.\n"
                    "* `not_searchable` — pages were in scope but **none had usable text**. Do "
                    "NOT conclude the content is absent; these pages need vision. "
                    "`pages_without_text` is the count.\n"
                    "* `out_of_scope` — no page matched the filters at all, so the corpus was "
                    "never really asked. Widen `scope`, drop `exclude_scope`, or check the "
                    "`page_from`/`page_to` range.\n"
                    "* `found_only_in_superseded` — nothing current matched, but a retired "
                    "revision does. `superseded` names it; re-ask with that `revision`.\n\n"
                    "`error` never appears in this body: a failure is a typed HTTP refusal with "
                    "its own code, because an outage rendered as an absence becomes the caller's "
                    "fabricated confidence.")
    query_interpretation: QueryInterpretation = Field(
        description="How the query was read before anything was retrieved — the explanation "
                    "behind this row set, and the first thing to inspect when the rows surprise "
                    "you.")
    superseded: list[SupersededIn] = Field(
        default_factory=list,
        description="Populated only with `found_only_in_superseded`: the retired revisions that "
                    "would have matched. It carries **no page content** — a superseded page is "
                    "not current, and returning its content here would disclose a revision the "
                    "corpus has replaced. Re-ask by scope.")
    rows: list[SearchRow]
    total: int = Field(description="Pages the branches were allowed to rank — the scope, narrowed "
                                   "by the identifiers and by `exclude`. Not the length of `rows`.")
    returned: int
    offset: int = Field(default=0, description="The offset applied, echoed back.")
    available: int = Field(
        default=0,
        description="How many rows the fusion produced in total — the end of the pageable list. "
                    "`offset + returned < available` means there is another page; equal means "
                    "there is not. This is a property of the **candidate pool**, not of the "
                    "corpus: `total` is how many pages were in scope, and `available` is how many "
                    "of them the branches actually ranked.")
    include: list[str] = Field(default_factory=list,
                               description="The content parts returned per row, echoed back.")
    query_images: int = Field(
        default=0,
        description="Photographs fused into the query vector. Mirrors "
                    "`query_interpretation.query_images`.")
    branches_run: list[str] = Field(
        description="Which branches actually ran. Mirrors `query_interpretation.branches_run`; "
                    "`query_interpretation.branches_skipped` is where the ones that did not say "
                    "why.")
    weights: dict[str, float] = Field(description="The weights in force, defaults included.")
    k: int
    effective_scope: dict[str, Any] = Field(
        description="The scope actually applied, echoed back — this service is stateless, so the "
                    "caller is told what it searched rather than asked to remember.")
    pages_searched: int = Field(
        default=0, description="Pages the scope selected — the denominator behind every count "
                               "here, and what separates `out_of_scope` (0) from `not_found`.")
    searchable_pages: int = Field(
        default=0,
        description="Pages in scope whose text may be believed. `0` with `pages_searched > 0` is "
                    "exactly `not_searchable`: the corpus was asked and nothing was readable.")
    pages_without_text: int = Field(
        default=0,
        description="Pages in scope with no text layer. The lexical and captions branches cannot "
                    "reach them at all, which is the first thing to check when a lexical-only "
                    "search looks empty.")


def resolve_weights(asked: Mapping[str, float] | None) -> dict[str, float]:
    """Caller weights → the internal surface names, defaults filled in.

    A name outside the three is a typed refusal rather than a silently ignored key: a caller who
    weighted `"sparse"` at 1.0 and got the defaults back would conclude the branch does nothing.
    """
    resolved = dict(SURFACE_WEIGHTS)
    if not asked:
        return resolved
    unknown = sorted(set(asked) - set(_INTERNAL))
    if unknown:
        raise ToolError(
            "unknown_branch",
            f"no retrieval branch {unknown} — this release fuses {list(BRANCHES)} "
            f"(`dense` is the fused image+text vector; `lexical` and `captions` are the two "
            f"sparse surfaces). A weight on a name that does not exist would be silently ignored",
            unknown=unknown, branches=list(BRANCHES))
    for name, weight in asked.items():
        if weight < 0:
            raise ToolError(
                "weight_negative",
                f"branch {name!r} was weighted {weight}: a negative weight is not 'less "
                f"important', it is a branch voting against its own results. Use 0 to switch a "
                f"branch off",
                branch=name, weight=weight)
        resolved[_INTERNAL[name]] = float(weight)
    if not any(resolved.values()):
        raise ToolError(
            "no_branch_enabled",
            "every branch is weighted 0, which is a search with nothing to search with. Leave "
            "`weights` out for the release defaults, or give at least one branch a weight",
            weights=dict(asked))
    return resolved


def resolve_images(body: "SearchRequest") -> list[str]:
    """The base64 photographs this query fuses, from whichever field carried them.

    Both fields at once is **refused** rather than merged or silently preferred: a caller who put
    a photograph in each and got one of them searched would have no way to tell which.
    """
    if body.image and body.images:
        raise ToolError(
            "image_and_images",
            "`image` is the one-photograph case and `images` is the general one — passing both "
            "leaves it ambiguous which was searched. Put every photograph in `images`",
            image=True, images=len(body.images))
    wanted = [body.image] if body.image else list(body.images)
    if len(wanted) > MAX_QUERY_IMAGES:
        raise ToolError(
            "too_many_query_images",
            f"a query fuses at most {MAX_QUERY_IMAGES} photographs into one vector, got "
            f"{len(wanted)}. They all go into a single embedding call, so past that the vector "
            f"describes an average of everything photographed rather than one question",
            limit=MAX_QUERY_IMAGES, requested=len(wanted))
    return wanted


def validate_k(k: int) -> None:
    if k < 1 or k > MAX_RRF_K:
        raise ToolError(
            "rrf_k_out_of_range",
            f"RRF's k damps the head of each branch and is between 1 and {MAX_RRF_K}, got {k}. "
            f"Outside that it is a different retrieval rather than a tuned one",
            minimum=1, limit=MAX_RRF_K, requested=k)


def validate_include(parts: Sequence[str]) -> None:
    """Every requested part is one this surface serves, named in the refusal (§7.3).

    Refused rather than ignored, for `extra="forbid"`'s reason one level down: a caller who typed
    `"summaries"` and got a row with no summary would conclude the *page* had none.
    """
    unknown = [part for part in parts if part not in PARTS]
    if unknown:
        raise ToolError("unknown_content_part",
                        f"include takes any of {list(PARTS)}, got {unknown}",
                        parts=list(PARTS), requested=unknown)


def validate_text_chars(text_chars: int) -> None:
    """1…:data:`MAX_TEXT_CHARS`. Past the ceiling the caller wants `fetch`, which is also free."""
    if text_chars < 1 or text_chars > MAX_TEXT_CHARS:
        raise ToolError("text_chars_out_of_range",
                        f"text_chars is between 1 and {MAX_TEXT_CHARS}, got {text_chars}",
                        minimum=1, limit=MAX_TEXT_CHARS, requested=text_chars)


def validate_offset(offset: int) -> None:
    """0…:data:`MAX_OFFSET` — the pageable depth, refused rather than clamped.

    An offset past the pool can only return nothing, and a silent empty page there is
    indistinguishable from *"the corpus has no more"* — the fabricated absence §7.1 exists to
    prevent, arriving through the one parameter that looks harmless.
    """
    if offset < 0 or offset > MAX_OFFSET:
        raise ToolError("offset_out_of_range",
                        f"offset is between 0 and {MAX_OFFSET}, got {offset}",
                        minimum=0, limit=MAX_OFFSET, requested=offset)


def page_range_conditions(page_from: int | None, page_to: int | None) -> list[qm.Condition]:
    """``page_no`` as a half- or fully-bounded interval — the one filter shape `scope` cannot spell.

    An inverted range is a typed refusal and not an empty result: ``page_from=40, page_to=10``
    selects no page, and returning *"nothing matched"* for it would report a caller's typo as a
    fact about the corpus (§7.1).
    """
    if page_from is None and page_to is None:
        return []
    if page_from is not None and page_to is not None and page_from > page_to:
        raise ToolError("page_range_inverted",
                        f"page_from {page_from} is above page_to {page_to} — that range selects "
                        f"no page, and an empty answer would report it as a fact about the corpus",
                        page_from=page_from, page_to=page_to)
    return [qm.FieldCondition(key="page_no", range=qm.Range(gte=page_from, lte=page_to))]


def phrase_conditions(phrases: Sequence[str], *, field: str) -> list[qm.Condition]:
    """Keyword filters as indexed phrase conditions, through the **one** exact-match code path.

    :func:`~vsir.core.exact.exact_filter` owns `variants()` and the phrase semantics, and there is
    exactly one of it in this codebase (I3, F1). Assembling `MatchPhrase` here instead would be a
    second matcher: a place where a spelling could be forgotten, and a forgotten spelling is a
    page that silently stops being findable by a filter that looks like it worked. So each term
    becomes one nested `exact_filter` — an OR over that term's spellings — and the terms are ANDed
    by being separate conditions.

    An empty term is refused rather than dropped: a caller that sent `["", "safety"]` and got the
    results of `["safety"]` was filtered on something it did not ask for.
    """
    conditions: list[qm.Condition] = []
    for index, phrase in enumerate(phrases):
        if not phrase.strip():
            raise ToolError(
                "phrase_empty",
                f"{field}[{index}] is empty — an empty phrase matches every page, so a filter "
                f"that quietly dropped it would return a wider answer than was asked for",
                field=field, position=index)
        conditions.append(exact_filter(phrase))
    return conditions


def validate_phrase_terms(phrases: Sequence[str], *, field: str) -> None:
    """At most :data:`MAX_PHRASE_TERMS` terms, refused rather than truncated."""
    if len(phrases) > MAX_PHRASE_TERMS:
        raise ToolError(
            "too_many_phrase_terms",
            f"{field} takes at most {MAX_PHRASE_TERMS} phrases, got {len(phrases)} — past that a "
            f"caller is writing a query rather than filtering one, and `query` is the parameter "
            f"for that",
            field=field, limit=MAX_PHRASE_TERMS, requested=len(phrases))


def exclusion_conditions(exclude_scope: Mapping[str, Any] | None) -> list[qm.Condition]:
    """``exclude_scope`` as ``must_not`` conditions, gated by `INDEXED` exactly as `scope` is.

    The gate matters more here than on `scope`, because the failure is inverted: an unknown key in
    a *negation* that was quietly dropped returns a **larger** result set that looks like a
    filtered one, and nothing in the response would show it (I6, F10).
    """
    if not exclude_scope:
        return []
    unknown = reject_unknown_keys(exclude_scope)
    if unknown:
        raise as_tool_error(UnknownScopeKey(unknown))
    conditions: list[qm.Condition] = []
    for key, value in exclude_scope.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            members = [member for member in value if member is not None]
            if members:
                conditions.append(qm.FieldCondition(key=key, match=qm.MatchAny(any=list(members))))
        else:
            conditions.append(qm.FieldCondition(key=key, match=qm.MatchValue(value=value)))
    return conditions


def raster_cache_url(page_id: str) -> str:
    """The page-image path, from the module that owns the route's grammar and its encoding."""
    from vsir.serve.raster_cache import page_image_url

    return page_image_url(page_id, dpi=DPI_INDEX)


def _actions(page_id: str, sections: Sequence[str], query: str) -> list[NextAction]:
    """The operations available on one page, with the arguments already built.

    Ordered as the ladder is: look before you comprehend, and the one that spends is last. The
    arguments are assembled here rather than described, because a `page_id` carries an ``@`` and a
    ``#`` and a consumer that builds its own body will eventually encode one of them wrong — and a
    request that addresses nothing comes back looking like an empty result rather than a bug.
    """
    actions = [
        NextAction(action="open_page_image", method="GET",
                   target=raster_cache_url(page_id),
                   detail="the page raster, rendered on demand. Free, and never persisted."),
        NextAction(action="fetch_material", target="/tools/fetch",
                   arguments={"page_ids": [page_id], "include": ["image", "text", "summary"],
                              "dpi": DPI_INDEX, "inline": True},
                   detail="the pixels, the extracted text and the summary of this page — material "
                          "instead of an answer, so you can reason over it yourself and ask a "
                          "follow-up without paying. Free; at most 5 pages per call."),
        NextAction(action="check_codes", target="/tools/verify",
                   arguments={"claims": ["<the code you are about to cite>"],
                              "page_ids": [page_id]},
                   detail="is each code actually printed on this page? `present`, `absent` (with "
                          "what is there instead) or `unverifiable`. Free, and the only thing in "
                          "this service that settles a code."),
    ]
    # **The query travels with the scope, or the action is not offered at all.** `/search`
    # refuses a body with nothing to search for (`query_required`), so a scope on its own is a
    # call that 400s — and an affordance whose whole promise is "post this verbatim" must not hand
    # back one of those. An image-only search has no text to carry here, so the action is omitted
    # and the row's `next.expand` still carries the scope for a caller that will re-send its image.
    if sections and query.strip():
        actions.append(NextAction(
            action="expand_section", target="/search",
            arguments={"query": query, "scope": {"section_id": list(sections)}},
            detail="the same query against the rest of the section(s) this page belongs to."))
    actions.append(NextAction(
        action="comprehend", target="/tools/read",
        arguments={"page_ids": [page_id], "question": "<your question about this page>"},
        spends=True,
        detail="**bills a vision call.** A directed read of at most 3 chosen pages at a pinned "
               "220 dpi. Prefer `fetch_material` when you can look at the page yourself; use "
               "this to delegate a bounded sub-answer."))
    return actions


def _summary_for(content: Mapping[str, Any], scope: Mapping[str, Any]) -> tuple[str, str]:
    """``(text, lang)`` — `skim._summary`'s rule, and deliberately the same one.

    The requested language is ``scope["lang"]`` because `lang` is an indexed facet and the scope is
    where a caller says which one it wants; the fallback is the page's first summary, which is its
    dominant language (§5.2).
    """
    summaries = [one for one in (content.get("summaries") or []) if isinstance(one, Mapping)]
    if not summaries:
        return "", ""
    wanted = scope.get("lang")
    wanted_list = [wanted] if isinstance(wanted, str) else list(wanted or [])
    for language in wanted_list:
        for one in summaries:
            if str(one.get("lang") or "") == language:
                return str(one.get("text") or ""), language
    first = summaries[0]
    return str(first.get("text") or ""), str(first.get("lang") or "")


def _page_text(client: Any, collection: str, point_ids: Sequence[Any]) -> dict[Any, str]:
    """The flat ``text`` field for the rows being returned — one bounded call, never a scan.

    `text` is **not** in `skim.ROW_PAYLOAD`, and adding it there would make all three `skim_*`
    rungs fetch a full page extraction per candidate for a field none of them returns (P2). So it
    is fetched here instead, by point id, for at most `limit` rows that are already chosen — which
    is one round trip whose size the `limit` bound already governs.
    """
    if not point_ids:
        return {}
    points = client.retrieve(collection, ids=list(point_ids),
                             with_payload=["text"], with_vectors=False)
    return {point.id: str((point.payload or {}).get("text") or "") for point in points}


def _content_of(payload: Mapping[str, Any], scope: Mapping[str, Any], parts: Sequence[str],
                full_text: str, text_chars: int) -> RowContent:
    """One row's content block — only the parts asked for, and the trust that qualifies them."""
    content = payload.get("content") or {}
    block = RowContent()
    if "summary" in parts:
        block.summary, block.summary_lang = _summary_for(content, scope)
    if "text" in parts:
        block.text_chars_total = len(full_text)
        block.text = full_text[:text_chars]
        block.text_truncated = len(full_text) > text_chars
    if "topics" in parts:
        block.topics = [str(one) for one in (content.get("topics") or [])]
    if "codes" in parts:
        block.codes = [str(one) for one in (content.get("codes") or [])]
        block.codes_in_text = [str(one) for one in (content.get("codes_in_text") or [])]
    if "labels" in parts:
        block.printed_page_no = str(content.get("printed_page_no") or "")
        block.label_verified = bool(content.get("label_verified"))
        block.interpolated = bool(content.get("interpolated"))
        block.label_candidates = [str(one) for one in (content.get("label_candidates") or [])]
    if "sections" in parts:
        block.sections = [
            SectionRef(section_id=str(one.get("section_id") or ""),
                       title=str(one.get("title") or ""),
                       series_id=str(one.get("series_id") or ""),
                       page_range=(list(one["page_range"]) if one.get("page_range") else None))
            for one in (content.get("sections") or []) if isinstance(one, Mapping)]
    return block


def _interpretation(found: Any, weights: Mapping[str, float], images: Sequence[bytes],
                    has_query: bool, body: "SearchRequest") -> QueryInterpretation:
    """Why this row set — the split, the branches that ran, and the reason for each that did not.

    The skip reasons are the two conditions `_candidates` actually branches on plus the weight
    switch, read back off the same values it used, so this cannot describe a search different
    from the one that ran.
    """
    ran = set(found.branches)
    skipped: list[SkippedBranch] = []
    for internal, public in (("page", "dense"), ("lexical", "lexical"), ("captions", "captions")):
        if internal in ran:
            continue
        if weights.get(internal, 1.0) == 0:
            skipped.append(SkippedBranch(
                branch=public, reason="weighted_zero",
                detail="you set this branch's weight to 0, so it was not run at all"))
        elif public == "dense":
            skipped.append(SkippedBranch(
                branch=public, reason="nothing_left_to_embed",
                detail="the query decomposed to identifiers only — embedding the code anyway "
                       "would blur an exact match into a similarity"))
        else:
            skipped.append(SkippedBranch(
                branch=public, reason="no_query_text",
                detail="this branch is a sparse vector built from text, and the query carried "
                       "none" if not has_query else
                       "the query had no tokens this branch could build a vector from"))
    return QueryInterpretation(
        identifiers=list(found.split.identifiers),
        embedded_text=found.split.embedded,
        branches_run=[WHY.get(name, name) for name in found.branches],
        branches_skipped=skipped,
        required_phrases=list(body.require_phrases),
        excluded_phrases=list(body.exclude_phrases),
        query_images=len(images),
    )


def search(client: Any, collection: str, body: SearchRequest, *, embedder: Any,
           images: Sequence[bytes] = (), runs_collection: str = "") -> SearchResult:
    """One flat search. The same `_candidates` the three `skim_*` rungs run.

    ``runs_collection`` is the control plane, and it buys exactly one thing: a scope holding no
    current page can answer `found_only_in_superseded` instead of `out_of_scope` (F9). Without it
    this surface would tell a consuming system the corpus has nothing while a retired revision
    holds the page — and that consumer has no second move to discover otherwise.
    """
    validate_skim_limit(body.limit)
    validate_k(body.k)
    # `None` is "you did not say" and means every part; `[]` is an explicit "none".
    parts = list(PARTS) if body.include is None else list(body.include)
    validate_include(parts)
    validate_text_chars(body.text_chars)
    validate_offset(body.offset)
    weights = resolve_weights(body.weights)
    # Both lists are built before the first round trip, so a caller's bad range or unknown negated
    # key is refused without spending an embedding call on it (§7.3, F18).
    validate_phrase_terms(body.require_phrases, field="require_phrases")
    validate_phrase_terms(body.exclude_phrases, field="exclude_phrases")
    # **Scope conditions narrow what was searched; content conditions search it.** A page range
    # and a negated facet change which pages were ever candidates, so they belong in the scope
    # denominator. A required phrase does not: a keyword filter that matched nothing has *searched*
    # the scope, and reporting that as `out_of_scope` would send the caller to widen a scope that
    # was never the problem. So the phrases go to the branch filter only, beside the identifiers
    # `decompose()` already puts there, and an empty result is the `not_found` it actually is.
    extra_must = page_range_conditions(body.page_from, body.page_to)
    extra_must_not = exclusion_conditions(body.exclude_scope)
    branch_must = phrase_conditions(body.require_phrases, field="require_phrases")
    branch_must_not = phrase_conditions(body.exclude_phrases, field="exclude_phrases")

    found = _candidates(client, collection, rung="search", query=body.query, image=None,
                        scope=body.scope, exclude=body.exclude, embedder=embedder,
                        weights=weights, k=body.k, images=list(images),
                        runs_collection=runs_collection,
                        extra_must=extra_must, extra_must_not=extra_must_not,
                        branch_must=branch_must, branch_must_not=branch_must_not)

    # The page of the fused ranking this call returns. `fused` is untruncated and deterministically
    # ordered (§16), so slicing it is a stable page rather than a re-run of the search.
    window = list(found.fused[body.offset:body.offset + body.limit])
    # One bounded fetch for the flat `text` field, and only when a caller asked for it.
    texts = (_page_text(client, collection, [row.point_id for row in window])
             if "text" in parts else {})

    rows: list[SearchRow] = []
    for row in window:
        payload = found.payloads.get(row.point_id) or {}
        page_id = str((payload.get("provenance") or {}).get("page_id") or "")
        content = payload.get("content") or {}
        # A stored value outside the four is reported as `no_text`: an unknown state must never
        # be rendered as trust, and the caller's `text_usable` gate then reads false.
        stored = str(payload.get("text_trust") or "")
        trust = stored if stored in ("ok", "degraded", "untrusted", "no_text") else "no_text"
        sections = [str(value) for value in (payload.get("section_id") or [])]
        doc_id, revision, page_no = "", "", 0
        if page_id:
            try:
                doc_id, revision, page_no = ids.parse_page_id(page_id)
            except ValueError:                   # a payload this malformed is a data bug, and the
                pass                              # row still addresses by its own `page_id`
        rows.append(SearchRow(
            rank=row.rank,
            page_id=page_id,
            doc_id=doc_id,
            revision=revision,
            page_no=page_no,
            printed_page_no=str(content.get("printed_page_no") or ""),
            page_kind=str(payload.get("page_kind") or ""),
            why=row.why,
            # `WHY` maps the internal surface name onto the one §7.2.1 publishes, so a caller can
            # copy a key straight back into `weights` without learning that dense is called
            # `page` underneath.
            surface_ranks={WHY.get(surface, surface): position
                           for surface, position in sorted(
                               row.surface_ranks.items(),
                               key=lambda item: WHY_ORDER.index(WHY.get(item[0], item[0]))
                               if WHY.get(item[0], item[0]) in WHY_ORDER else 99)},
            best_rank=row.best_rank,
            text_trust=trust,
            text_usable=trust not in UNSEARCHABLE_TRUST,
            has_text=trust not in ("", "no_text"),
            grounded_rate=content.get("grounded_rate"),
            section_id=sections,
            image=image_ref(page_id) if page_id else ImageRef(url="", dpi=DPI_INDEX),
            image_url=raster_cache_url(page_id) if page_id else "",
            # The same affordances a `skim_pages` row carries, from the same function — a second
            # implementation would let the two surfaces disagree about what the section of a page
            # is (§7.2.1, F8).
            next=_next_moves(payload, found.stats.pages),
            actions=_actions(page_id, sections, body.query) if page_id else [],
            # Absent rather than empty when nothing was asked for — see `SearchRow.content`.
            content=(_content_of(payload, found.scope, parts,
                                 texts.get(row.point_id, ""), body.text_chars)
                     if parts else None),
        ))

    return SearchResult(
        # **The same rule the three rungs use**, through the same function (`lookup.absence`).
        # A second implementation here would be a second opinion about what an empty result means,
        # and the two would drift — so `/search` and `skim_pages` cannot disagree about whether a
        # scope was unsearchable or merely empty (§7.1).
        status=Status.OK if rows else absence(found.stats.pages, found.searchable_pages,
                                              superseded=found.superseded),
        query_interpretation=_interpretation(found, weights, images, bool(body.query.strip()),
                                             body),
        superseded=list(found.superseded),
        rows=rows,
        total=found.total,
        returned=len(rows),
        offset=body.offset,
        available=len(found.fused),
        include=parts,
        query_images=len(images),
        branches_run=[WHY.get(name, name) for name in found.branches],
        weights={name: weights[_INTERNAL[name]] for name in BRANCHES},
        k=body.k,
        effective_scope=dict(found.scope),
        # Straight off `ScopeStats`, which already carries both — `pages_no_text` is the field
        # §7.1 calls "the blind spot made visible", and recomputing it from a subtraction here
        # would be a second answer to the question the envelope already answers.
        pages_searched=found.stats.pages,
        searchable_pages=found.searchable_pages,
        pages_without_text=found.stats.pages_no_text,
    )


__all__ = ["BRANCHES", "DEFAULT_TEXT_CHARS", "FILTER_KEYS", "MAX_OFFSET", "MAX_PHRASE_TERMS",
           "MAX_QUERY_IMAGES", "REQUEST_EXAMPLES", "phrase_conditions", "validate_phrase_terms",
           "MAX_RRF_K", "MAX_TEXT_CHARS", "PARTS", "QueryInterpretation", "RowContent",
           "SectionRef", "SkippedBranch", "SearchRequest", "SearchResult", "SearchRow",
           "exclusion_conditions", "page_range_conditions", "resolve_images", "resolve_weights",
           "search", "validate_include", "validate_k", "validate_offset", "validate_text_chars"]
