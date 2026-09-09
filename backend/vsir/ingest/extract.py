"""Step 06 — the S2 response schema (Spec §5.2). **The only VLM extraction schema there is.**

Rewritten from ``impl/app/segment.py`` rather than ported: the shape changed. ``units[]`` became
``sections[]``, ``identifiers[]`` became ``codes[]``, and ``summaries`` and ``topics`` are new. What
went with the old shape is everything that encoded knowledge of *this corpus* — ``STRICT_KINDS``,
``key_for_unit``, ``Unit.kind``, ``attrs``, ``refs[]`` (measured at zero reads anywhere in `impl`)
and ``_is_safety()``'s hardcoded keyword list. §5.2 is categorical about it: **no identifier
grammar, no classification enum, no regex taxonomy and no per-corpus keyword list** anywhere in
extraction or derivation.

The one structural rule worth restating, because it is what makes stitching possible:
``sections[]`` carries **presence per page, never extent**. The model says "this page belongs to
the emergency stop chain"; it never says where that section starts and ends. Extent is computed
after the window folds are gone (§6.1 step 08), which is why a section can straddle a fold and
survive it (F8).

``page_index`` is 1-based **within this excerpt**, not within the book. Turning it into an absolute
page is §6.4's two-check offset proof, and it is the single most dangerous line in the pipeline: get
it wrong and every page, citation and summary shifts by one with nothing raising.

This module carries the schema and its hash at M2a. The client, the prompts, the content-addressable
cache and the extraction call itself arrive with U008 (§4.1: ``vlm/client.py``, ``vlm/cache.py``,
``vlm/stub.py``, ``vlm/prompts/``); ``S2_SCHEMA_HASH`` is here now because ``extract_key`` cannot be
computed without it (§6.3).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field


class Summary(BaseModel):
    """2-3 sentences on what is SPECIFIC to this page, in one language (D5).

    The binding prompt rule of §5.2 is a property of this field: *"Do not describe the document
    generally."* A summary that describes the manual rather than the page makes every page's dense
    vector look like every other page's, and the `captions` surface stops discriminating at all.
    """

    model_config = ConfigDict(extra="forbid")

    lang: str = ""
    text: str = ""


class SectionRef(BaseModel):
    """A section this page belongs to. Presence, never extent (§5.2)."""

    model_config = ConfigDict(extra="forbid")

    title: str = ""
    is_start: bool = False


class PageOut(BaseModel):
    """One page of a window, as the model reports it."""

    model_config = ConfigDict(extra="forbid")

    #: 1-based **within this excerpt**, not within the book (§6.4).
    page_index: int = 0
    #: The page label as printed, VERBATIM. Model-read, and cross-checked against the text (§6.5).
    printed_page_no: str = ""
    page_kind: str = "prose"
    lang: list[str] = Field(default_factory=list)
    sections: list[SectionRef] = Field(default_factory=list)
    summaries: list[Summary] = Field(default_factory=list)
    #: Every code, tag, part or reference number, VERBATIM. Nothing here reaches a lexical index
    #: except through ``vlm_codes``, which is opt-in and permanently ``verified: false`` (I2, D3).
    codes: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)


class WindowOut(BaseModel):
    """One window's worth of pages. The verbatim response is what gets cached (§6.3)."""

    model_config = ConfigDict(extra="forbid")

    pages: list[PageOut] = Field(default_factory=list)


def schema_hash(schema: Mapping[str, Any] | type[BaseModel]) -> str:
    """A stable digest of the response schema the extraction was demanded in.

    `impl` put a hand-maintained ``SCHEMA_VERSION`` integer in the key, which is only correct while
    somebody remembers to bump it. Hashing the schema itself cannot be forgotten: add a field and
    every window re-bills, which is the honest answer, because the model was asked a different
    question and its old answer does not contain the new field.
    """
    document = schema.model_json_schema() if isinstance(schema, type) else dict(schema)
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


#: The value that goes into ``extract_key`` (§6.3). Computed, never written down by hand.
S2_SCHEMA_HASH = schema_hash(WindowOut)
