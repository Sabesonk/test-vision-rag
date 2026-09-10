"""The page record (Spec §5.3). Ported from ``impl/app/pagemodel.py`` — the **record shape only**.

`impl`'s own metadata contract (`pipeline-guide/METADATA-CONTRACT.md`) states the rule this shape
rests on, and it is worth keeping in front of anyone adding a field:

    A field belongs in FACETS only if its values form a small, closed set — something a user
    could pick from a dropdown. If you need it to rebuild the row, it is PROVENANCE. If nobody
    narrows or finds by it, it is CONTENT.

So the zones are shaped differently **on purpose**. Qdrant *can* filter a nested key; it just runs
unindexed and skips the filterable-HNSW path, which is a silent recall loss rather than an error
(F10). Keeping the flat and nested zones visibly different is what makes that mistake reviewable.

Three changes from `impl`, each deliberate:

* **``text`` moves from nested ``content`` to a flat, indexed field.** It is the exact-match
  surface now (§5.3, §5.5), and `ingest/probe.py` is its only writer (I2).
* **There is no ``image_path``** — register item A5, where a stale path made ``read()`` return 503
  for every page. Rasters are re-rendered on demand (§4.2), so no record depends on a file that
  may not exist on the instance serving the request (§15 Factor VI).
* **``units``, ``refs`` and ``identifiers`` are gone.** `sections[]` carries presence per page and
  never extent (§5.2), `refs[]` was measured at zero reads anywhere in `impl` (§2.5 B), and the
  identifier machinery is struck (C1).

``is_current`` defaults to **False**. A record is not queryable until the publish gates flip it,
and a default of True would make I7 a matter of remembering rather than a property of the type.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: Bumping this is a release: it is stamped on every run record and every envelope (§15 Factor V).
SCHEMA_VERSION = 1

#: §5.2 — the page-level facet that makes "the wiring diagrams in this manual" possible.
PAGE_KINDS = ("prose", "table", "schematic", "exploded", "cover", "toc", "index", "blank")

#: §5.7 — both `untrusted` and `no_text` count as unsearchable for `lookup`.
TextTrust = Literal["ok", "degraded", "untrusted", "no_text"]

#: The two levels that make a page unsearchable (§5.7), in one place because three modules need the
#: same rule: `lookup` excludes these pages from `hits`, `verify` returns `unverifiable` for them,
#: and the observed-token inventory does not take codes from them. `degraded` is **not** here — it
#: is a text layer with problems, not one that cannot be read.
UNSEARCHABLE_TRUST: tuple[str, ...] = ("untrusted", "no_text")


class Summary(BaseModel):
    """One page summary, in one language (D5). Never a blended multi-language string."""

    model_config = ConfigDict(extra="forbid")

    lang: str
    text: str


class StoredSection(BaseModel):
    """A section this page belongs to, as stitching resolved it (§6.1 step 07).

    ``page_range`` is the section's extent *after* stitching. The model never supplies it: S2
    reports presence per page and nothing else, which is what lets stitching survive a window
    fold (§5.2).
    """

    model_config = ConfigDict(extra="forbid")

    section_id: str
    title: str = ""
    series_id: str = ""
    page_range: tuple[int, int] | None = None
    is_start: bool = False


class MovedCode(BaseModel):
    """One code reattributed to this page from a neighbour, and where it came from (§6.5, F6).

    A pair, not a string. The injury F6 names is *"cites a page for a code that is on its
    neighbour"*, and the repair is only auditable if the record says **which** page the sighting
    moved off: a bare code would record that something moved and lose the one fact a reviewer
    needs to check the move.
    """

    model_config = ConfigDict(extra="forbid")

    #: Verbatim, as the model reported it (§5.2). Never normalised on the way through.
    code: str
    from_page_id: str


class PageContent(BaseModel):
    """Zone D — returned, never filtered. Nested under ``content`` so that stays true."""

    model_config = ConfigDict(extra="forbid")

    printed_page_no: str = ""
    label_verified: bool = False
    interpolated: bool = False
    #: Populated **only** where the page's printed label is ambiguous (§6.5, F5): two readings the
    #: page itself cannot arbitrate between. Then `printed_page_no` is empty, because the
    #: alternative is a silent pick — and a silent pick is what makes an agent follow a
    #: cross-reference to the wrong page.
    label_candidates: list[str] = Field(default_factory=list)
    summaries: list[Summary] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    sections: list[StoredSection] = Field(default_factory=list)
    codes: list[str] = Field(default_factory=list)
    codes_in_text: list[str] = Field(default_factory=list)
    moved_from: list[MovedCode] = Field(default_factory=list)
    #: §5.7 — `None` where `has_text` is false, and every aggregate ignores those pages.
    grounded_rate: float | None = None
    flags: list[str] = Field(default_factory=list)


class Provenance(BaseModel):
    """Zone E — never queried, and enough to rebuild the row if the index is lost.

    ``release_id`` and ``schema_version`` are what make an answer traceable to the exact code and
    configuration that produced it; ``extract_key`` / ``embed_key`` / ``read_keys`` are the
    content-addressable cache keys of §6.3, so a cached artefact can always be told apart from a
    freshly billed one (register B1/B4).
    """

    model_config = ConfigDict(extra="forbid")

    page_id: str
    run_id: str = ""
    release_id: str = ""
    schema_version: int = SCHEMA_VERSION
    extract_key: str = ""
    embed_key: str = ""
    read_keys: list[str] = Field(default_factory=list)
    probe_version: str = ""
    vlm_model: str = ""
    prompt_version: str = ""
    dpi: int = 0


class PageRecord(BaseModel):
    """One page, one point (I1). The payload of that point is :meth:`to_payload`.

    The vectors are not part of the payload: they travel beside it in the upsert (``ingest/index``),
    because a vector is not something a filter or a response ever reads.
    """

    model_config = ConfigDict(extra="forbid")

    # ── FLAT · FACETS — indexed keyword / integer / bool ─────────────────────────────────────────
    doc_id: str
    revision: str
    #: Written False by step 10; only the publish gates flip it, and every tool injects True (I7).
    is_current: bool = False
    doc_type: str = "unknown"
    subjects: list[str] = Field(default_factory=list)   # machine/model — document level
    tags: list[str] = Field(default_factory=list)       # uploader/filename — document level
    #: Left as a plain `str` on purpose: the value comes from the model, so it is the derivation
    #: step's job to decide what to do with an off-list one (U009), not the storage layer's.
    page_kind: str = "prose"
    lang: list[str] = Field(default_factory=list)
    page_no: int
    #: **Arrays.** A page that straddles two sections carries both ids, and a scope matches if any
    #: element matches. A single scalar per page is exactly how F8 happens.
    section_id: list[str] = Field(default_factory=list)
    series_id: list[str] = Field(default_factory=list)
    has_text: bool = False
    text_trust: TextTrust = "no_text"
    run_id: str = ""

    # ── FLAT · FULL TEXT — indexed text (§5.5) ───────────────────────────────────────────────────
    #: PyMuPDF's extraction of the **full** page. `ingest/probe.py` is the only writer (I2), and it
    #: never reads from a crop, which is what closes F15.
    text: str = ""
    #: `" ".join(codes)` — opt-in, and every hit from it is labelled `verified: false` (D3).
    vlm_codes: str = ""

    # ── NESTED ───────────────────────────────────────────────────────────────────────────────────
    content: PageContent = Field(default_factory=PageContent)
    provenance: Provenance

    @property
    def page_id(self) -> str:
        """The page id, single-sourced from provenance where §5.3 puts it."""
        return self.provenance.page_id

    def to_payload(self) -> dict[str, Any]:
        """The Qdrant payload: flat facets and text, then the two nested zones."""
        payload = self.model_dump(mode="json", exclude={"content", "provenance"})
        payload["content"] = self.content.model_dump(mode="json")
        payload["provenance"] = self.provenance.model_dump(mode="json")
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PageRecord":
        """Rebuild a record from a payload. Round-trips :meth:`to_payload` with no field loss."""
        return cls.model_validate(payload)
