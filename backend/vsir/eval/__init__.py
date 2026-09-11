"""Evaluation corpora and the commands that run them (Spec §12.3, §12.4, §12.6).

Net new, and recorded in the plan as a deliberate extension of §4.1's layout (SA-5): the spec's
tree enumerates no `eval/` package while §12.3, §12.4 and §12.6 all require evaluations that must
be runnable as `vsir` subcommands (§15 Factor XII). This is where the corpus a command evaluates
*against* is assembled — never where a rule about correctness lives, which stays in `core/`.

At M1 there was one member: the synthetic corpus of §13, which is hand-written page text with no
PDF, no VLM and no spend. `acceptance` and `abstention` (§12.3, §12.4) joined it at M3, `legacy`
and `grounded_rate` at M2b, and the corpus report of §12.6 (U026) does at M8.

The one thing that lives here rather than in a member is :func:`current_payloads`, and the
:func:`searchable_payloads` narrowing over it, because every eval needs the same reading of "what
is actually in the index".
"""
from __future__ import annotations

from typing import Any

from vsir.core.observed_tokens import is_searchable

#: How many points an eval will scroll out of a collection in one call. The corpora these commands
#: run against are one document — 30 hand-written pages, 55 real ones, 142 in the ported baseline —
#: and a collection bigger than this is one an eval should be scoped at rather than swept, so the
#: ceiling is deliberate and the count is reported rather than silently truncated.
SCROLL_LIMIT = 4096


def current_payloads(client: Any, collection: str, *, doc_id: str = "",
                     limit: int = SCROLL_LIMIT) -> list[dict]:
    """The payloads of the **current** pages of ``collection``, searchable or not.

    Read out of the index rather than off the page records, for the reason §6.8 gives: the
    inventory that backs `present_instead` in production is built from what was *indexed*, so if a
    payload and a record could disagree, an eval reading the records would be measuring something
    the caller cannot search.

    ``is_current`` is the only filter, because it is the only one a tool also applies
    unconditionally (I7). A page with no text layer is still a page of the document: §5.7's
    `grounded_rate` distribution and §12.6's `searchable_ratio` are both *about* those pages, so
    an eval that dropped them here would report a corpus the operator does not have.
    """
    points, _next_page = client.scroll(collection_name=collection, limit=limit,
                                       with_payload=True, with_vectors=False)
    return [point.payload for point in points
            if point.payload and point.payload.get("is_current")
            and (not doc_id or point.payload.get("doc_id") == doc_id)]


def searchable_payloads(client: Any, collection: str, *, doc_id: str = "",
                        limit: int = SCROLL_LIMIT) -> list[dict]:
    """:func:`current_payloads`, narrowed to the pages a caller can actually search.

    ``is_searchable`` drops what §5.7 says `lookup` cannot search and `verify` cannot check — a
    page with no text layer, and one whose text layer is untrusted. A code observed only there is
    not one the near-miss eval can reason about: it must not seed a near miss, and it must not
    volunteer itself as a "different part".
    """
    return [payload for payload in current_payloads(client, collection, doc_id=doc_id, limit=limit)
            if is_searchable(payload)]
