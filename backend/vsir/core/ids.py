"""Identifiers (Spec §5.1). Ported from ``impl/app/pagemodel.py``'s id functions.

What survives is the shape — ``{doc_id}@{revision}#p{NNN}`` — and, load-bearingly, the
**deterministic** ``point_id``: because it is a hash of the page id rather than a fresh uuid4, a
re-ingest of the same page overwrites its point instead of adding a second one, which is I1 and is
what makes F12 ("totals double") impossible rather than merely unlikely.

What does not survive: ``make_segment_id`` / ``split_segment_id``. The unit of everything is the
page now (§2.5 D2, `segment_id` → `page_id`), and the identifier grammar those keys indexed is
struck (C1).

**One correction of `impl`.** Its ``point_id`` hashed under a private namespace constant; §5.1
specifies ``uuid.NAMESPACE_URL``. The namespace is part of the id, so a later change would orphan
every point in the collection — it is pinned here, and a test asserts the exact value.
"""
from __future__ import annotations

import os
import re
import time
import uuid

#: §5.1 — the namespace `point_id` hashes under. Changing this orphans every existing point.
NAMESPACE = uuid.NAMESPACE_URL

#: Crockford base32: no I, L, O or U, so a transcribed run id cannot become a different run id.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID_TIME_CHARS = 10   # 48 bits of millisecond timestamp
_ULID_RAND_CHARS = 16   # 80 bits of randomness
ULID_LENGTH = _ULID_TIME_CHARS + _ULID_RAND_CHARS

_SLUG_SEPARATORS = re.compile(r"[^A-Za-z0-9]+")
#: Only the **canonical** spellings `page_id()` can emit: exactly three digits (`001`… `999`), or
#: four or more with no leading zero (`1000`…). `#p0001` is therefore *not* a page id, even though
#: it reads like one — see :func:`parse_page_id`.
_PAGE_ID = re.compile(r"^(?P<doc_id>.+)@(?P<revision>[^@#]+)#p(?P<page_no>\d{3}|[1-9]\d{3,})$")


def slug(raw: str) -> str:
    """A stable, url-safe slug. Case is preserved: `doc_id` is printed to people (§5.1)."""
    return _SLUG_SEPARATORS.sub("-", raw).strip("-")


def doc_id(stem: str) -> str:
    """The document's stable slug, from the manifest — never from content sniffing (§6.1)."""
    return slug(stem) or "doc"


def page_id(document: str, revision: str, page_no: int) -> str:
    """``"TC1E-SF@1.3#p001"``. ``page_no`` is the 1-based **absolute** page, offset already applied.

    Zero-padded to three digits and never truncated, so a 1,440-page manual sorts lexically for
    the first 999 pages and stays unambiguous after them (§5.1 "padded to 3+").
    """
    if page_no < 1:
        raise ValueError(f"page_no is 1-based: {page_no}")
    return f"{document}@{revision}#p{page_no:03d}"


def parse_page_id(value: str) -> tuple[str, str, int]:
    r"""``"TC1E-SF@1.3#p001"`` → ``("TC1E-SF", "1.3", 1)``. Raises on anything else.

    `resolve` accepts a saved citation from outside this service, so the parse refuses a malformed
    id rather than guessing at one (§7.2.3) — and **only the canonical spelling parses**.

    That last part is load-bearing, and it is not fussiness. ``#p0001`` and ``#p001`` are the same
    page to a human and to ``int()``, but they are different strings, so they hash to different
    ``point_id``\ s. A lenient parse plus a string-keyed hash is one page with several point ids:
    a re-ingest would add a second point instead of overwriting it (I1), and a citation spelled
    with an extra zero would address a point that does not exist — a silent miss rather than an
    error. So over-padding is refused here, and :func:`point_id` canonicalises through this
    function so a non-canonical string cannot reach the hash at all.
    """
    match = _PAGE_ID.match(value)
    if not match:
        raise ValueError(f"not a page_id: {value!r}")
    page_no = int(match["page_no"])
    if page_no < 1:
        raise ValueError(f"page_no is 1-based: {value!r}")
    return match["doc_id"], match["revision"], page_no


def section_id(document: str, revision: str, ordinal: int) -> str:
    """``"TC1E-SF@1.3#s007"`` — the section's ordinal **after stitching** (§5.1)."""
    if ordinal < 1:
        raise ValueError(f"section ordinal is 1-based: {ordinal}")
    return f"{document}@{revision}#s{ordinal:03d}"


def series_id(document: str, section_key: str) -> str:
    """``"TC1E-SF#s:emergency-stop"`` — the same section across revisions (§5.1, F8).

    **Deliberately without the revision.** That is the whole point: a scope expressed as a
    `series_id` survives a revision boundary, where a `section_id` cannot. ``section_key`` is the
    canonical section key that stitching derives (U009); this function only fixes the id's grammar.
    """
    key = slug(section_key).lower()
    if not key:
        raise ValueError("section_key must contain at least one alphanumeric character")
    return f"{document}#s:{key}"


def point_id(page: str) -> str:
    """The Qdrant point id for a page. Deterministic: a re-ingest overwrites (I1, F12).

    The page id is **canonicalised before hashing**, by round-tripping it through
    :func:`parse_page_id` and :func:`page_id`. For a canonical input that is the identity; for
    anything else it raises. Hashing the raw string instead would make ``#p0001`` a second point
    for the same page, which is the failure I1 exists to make impossible.
    """
    document, revision, page_no = parse_page_id(page)
    return str(uuid.uuid5(NAMESPACE, page_id(document, revision, page_no)))


def run_id(now_ms: int | None = None, randomness: bytes | None = None) -> str:
    """A ULID: 48 bits of millisecond time, then 80 bits of randomness, Crockford base32.

    Lexically sortable, so listing runs in id order lists them in time order without an index —
    and unlike ``impl``'s ``uuid4().hex[:8]`` (register E1), two runs started in the same
    millisecond still differ, and a run id carries when it started.
    """
    timestamp = int(time.time() * 1000) if now_ms is None else now_ms
    if not 0 <= timestamp < (1 << 48):
        raise ValueError(f"timestamp out of ULID range: {timestamp}")
    entropy = os.urandom(10) if randomness is None else randomness
    if len(entropy) != 10:
        raise ValueError(f"ULID randomness is 80 bits: got {len(entropy) * 8}")

    value = (timestamp << 80) | int.from_bytes(entropy, "big")
    digits = []
    for _ in range(ULID_LENGTH):
        value, remainder = divmod(value, 32)
        digits.append(_CROCKFORD[remainder])
    return "".join(reversed(digits))
