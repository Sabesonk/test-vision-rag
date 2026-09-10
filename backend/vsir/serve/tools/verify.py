"""CHECK — ``verify(claims, page_ids)`` (Spec §7.2.4). Net new; `impl` has nothing like it.

`impl` had one verification idea and it ran at **ingest** time: the allowlist gate, which decided
once whether a model-claimed identifier was backed by the text layer and dropped the rest into
`withheld.jsonl`. §2.5 B strikes it. Verification here is a **move the agent makes**, at the
moment it matters — about the code it is about to write, against the page it is about to cite.

This module is the wrapper and nothing else. Every verdict comes out of
:func:`~vsir.core.verify.verify_claims`, which asks :func:`~vsir.core.exact.exact_filter` the very
question `lookup` asks, scoped to one page. That is what makes **F2** structural rather than
tested: the tool that found a page and the check that confirms it cannot disagree, because there
is one code path and there is no second matcher here to drift from it.

**Family B, and that is the whole reason Family B exists** (§7.1). A `verify` in which all three
claims are legitimately `absent` is ``status: ok`` with three `absent` verdicts: the call ran, and
the answer is no. Forced through Family A it would be an empty result — indistinguishable from an
outage, and `empty_is_never_ok` would reject it outright. So ``status`` here says whether the
**call** ran, and the verdicts live in ``result``.

Two failures are deliberately *not* verdicts:

* a ``page_id`` that is not in the collection is a **404 `page_not_found`** (§7.1). An `absent`
  about a page that does not exist is a statement about nothing, and `unverifiable` would hint
  that the page might carry the code after all;
* a ``page_id`` that does not parse is a **400 `page_id_invalid`**. `resolve` accepts saved
  citations from outside this service (§7.2.3), so a malformed one is the caller's bug and gets
  named as such rather than silently addressing a point that does not exist.

**No image, ever.** `verify` takes a text label and a page id (I2, I3). A photograph may *find* a
candidate page through `skim_pages`; it can never *confirm* a code.
"""
from __future__ import annotations

from typing import Any, Sequence

from vsir import logging as vsir_logging
from vsir.core import ids
from vsir.core.verify import PageNotFound, verify_claims
from vsir.serve.caps import ToolError, validate_verify_pairs
from vsir.serve.envelope import Provenance, ToolEnvelope, VerifyResult

_log = vsir_logging.get_logger(__name__)


def _parsed(page_ids: Sequence[str]) -> None:
    """Every id is the canonical spelling of §5.1, or a typed 400 naming the ones that are not.

    Checked before the retrieve rather than caught out of it, so a malformed id and a missing page
    stay distinct: the first is a request this service cannot interpret, the second is a fact
    about the corpus, and a caller retries them differently.
    """
    malformed = []
    for page_id in page_ids:
        try:
            ids.parse_page_id(page_id)
        except ValueError:
            malformed.append(page_id)
    if malformed:
        raise ToolError(
            "page_id_invalid",
            f"not page ids of the form doc@revision#pNNN (§5.1): {malformed}",
            page_ids=malformed,
        )


def verify(client: Any, collection: str, claims: Sequence[str], page_ids: Sequence[str], *,
           inventory: Any | None = None,
           provenance: Provenance,
           reads_remaining: int = 0) -> ToolEnvelope[VerifyResult]:
    """Every claim, checked against every named page (§7.2.4).

    Stateless in the way that matters: ``client`` and ``collection`` are the store, ``provenance``
    and ``reads_remaining`` come from the request context the caller owns, and nothing survives
    the call. The HTTP route and the MCP server both call **this** function — they add transport
    and identity and not one line of behaviour (§7.5).

    ``page_ids`` is de-duplicated by `core.verify`, and the order the caller gave is the order the
    verdicts' ``page_ids`` come back in, so a draft citing `p001–p002` can see which of the two
    the evidence actually sits on (I8).

    ``inventory`` is **not** a request parameter and never will be: it chooses which observed
    tokens `present_instead` may disclose, and a caller that could widen that could read codes off
    pages it never asked about. Left unset, `core.verify` builds the local inventory of the named
    pages, which is the tightest honest reading. The answer gate passes the §6.8 document-level
    inventory here when it wants the broader one (U022).
    """
    claims = list(claims)
    page_ids = list(page_ids)
    validate_verify_pairs(claims, page_ids)
    _parsed(page_ids)

    try:
        result = verify_claims(client, collection, claims, page_ids, inventory=inventory)
    except PageNotFound as missing:
        # §7.1 — *"a missing `page_id` is a `404 page_not_found`"*. Not a verdict, and not an
        # empty result: the caller named a page this corpus does not hold, which is a different
        # problem from the code not being printed on it.
        raise ToolError(
            "page_not_found",
            f"not in {collection}: {missing.page_ids}. This is a refusal and not an `absent` "
            f"verdict — a verdict about a page that does not exist is a statement about nothing "
            f"(§7.1, §7.2.4)",
            http_status=404, page_ids=missing.page_ids,
        ) from None

    verdicts = result.claims
    # `debug`, not `info`: §7.4 writes an audit line for `read` and `fetch`, the two tools that
    # spend, and asks for nothing per call from a free one.
    _log.debug(
        "verify",
        tool="verify",
        claims=len(verdicts),
        pages=len(dict.fromkeys(page_ids)),
        # The distribution, not the verdicts: a per-claim line would put the caller's draft codes
        # on the event stream, and §15.1's retention row says the audit schema is never widened
        # with document content.
        present=sum(1 for verdict in verdicts.values() if verdict.status == "present"),
        absent=sum(1 for verdict in verdicts.values() if verdict.status == "absent"),
        unverifiable=sum(1 for verdict in verdicts.values() if verdict.status == "unverifiable"),
    )
    return ToolEnvelope[VerifyResult](
        # `ok` even when every verdict is `absent`. The call ran; the answer is no (§7.1).
        status="ok",
        result=result,
        reads_remaining=reads_remaining,
        provenance=provenance,
    )

