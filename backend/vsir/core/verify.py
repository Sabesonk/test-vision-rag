"""``verify_claims(claims, page_ids)`` (Spec §7.2.4, F2, and the mechanism I8 gates on at M6).

The move that makes the guarantee of §1.1 enforceable: *"is this code actually printed on the page
you are about to cite it from?"* Two decisions make it work, and both are the spec's.

**Per `(claim, page)`, not per claim.** A draft that cites `p001–p002` must not be able to let a
code from the neighbouring page through (I8). So every pair is checked, :func:`page_checks` returns
the whole matrix, and the folded verdict's ``page_ids`` says exactly which pages the answer is
about — the pages it is *present* on, or the pages the absence was actually asserted over.

**Three states, and `unverifiable` is never folded into `absent`.** Telling an agent *"that code
is not on the page"* about a page nobody could read is the failure this vocabulary exists to
prevent: it converts our blind spot into the agent's confident denial. A page with no text layer,
an untrusted extraction, or a revision that is not current is `unverifiable` with a named reason,
forever if need be (R2) — and the badge is the deliverable, not certainty.

**The same filter as `lookup`.** §13 M1 is explicit: *"the same filter, per `(claim, page)`"*. This
module builds no matcher of its own; it calls :func:`~vsir.core.exact.exact_filter` scoped to one
page and counts. That is what makes F2 structural — the tool that found a page and the check that
confirms it cannot disagree, because there is one code path and it is asked the same question.

**One inverted import, deliberately.** `core/` otherwise never imports from `serve/`, and this
module imports ``ClaimVerdict`` and ``VerifyResult`` from `serve/envelope.py` because §7.1 puts
them there and §4.1 keeps the response models under `serve/`. The alternative is a second
declaration of the same three-state vocabulary in `core/` — one source of truth becoming two, for
the vocabulary whose whole purpose is that `unverifiable` and `absent` never blur. The wrapper of
U015 adds the envelope, the budget and the HTTP status around this result and changes nothing in
it.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from vsir.core import ids
from vsir.core.exact import exact_filter
from vsir.core.observed_tokens import Inventory, from_records, is_searchable
from vsir.core.present_instead import present_instead
from vsir.serve.envelope import ClaimVerdict, VerifyResult

#: §5.7 — a page whose text layer cannot be trusted cannot answer, and says so by name.
UNCHECKABLE_TRUST = {"no_text": "no_text", "untrusted": "untrusted"}

#: I7 — a page that is not current cannot answer. `unverifiable` rather than `absent`, because the
#: page was not checked: the code may well be printed on it. The answer gate (I8, U022) rejects a
#: draft carrying an unverified code, which is the correct outcome for one citing a superseded or
#: an unpublished page — and it is an outcome it can only reach if this reads `unverifiable` and
#: not `absent`.
NOT_CURRENT = "not_current"

#: The three states of §7.2.4, in fold order. `present` wins over everything: one page carrying the
#: code makes the claim true of the set. `absent` beats `unverifiable` only when at least one page
#: was actually checked, and the verdict then names those pages.
PRESENT, ABSENT, UNVERIFIABLE = "present", "absent", "unverifiable"


class PageNotFound(LookupError):
    """A ``page_id`` that is not in the collection.

    §7.1: *"A missing `page_id` is a `404 page_not_found`"* — never a verdict. An `absent` about a
    page that does not exist would be a statement about nothing, and `unverifiable` would suggest
    the page might carry the code after all.
    """

    def __init__(self, page_ids: Sequence[str]) -> None:
        super().__init__(f"not in the collection: {list(page_ids)}")
        self.page_ids = list(page_ids)


def _page_scope(page_id: str) -> dict[str, Any]:
    """The exact page, as indexed facets: ``{doc_id, revision, page_no}``.

    All three come out of the ``page_id`` itself, so the caller has already named the revision and
    there is nothing for `is_current` to disambiguate. Publication state is read off the retrieved
    payload instead (see :data:`NOT_CURRENT`), which is a fact about the page rather than a filter
    that would silently make it unaddressable.
    """
    doc_id, revision, page_no = ids.parse_page_id(page_id)
    return {"doc_id": doc_id, "revision": revision, "page_no": page_no}


def page_payloads(client: Any, collection: str,
                  page_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """``page_id → payload``, in one round trip. Raises :class:`PageNotFound` for any that is not
    there.

    Retrieved by ``point_id``, which is ``uuid5(page_id)`` (I1) — an exact address rather than a
    filter, so a malformed citation is a parse error and a missing page is a 404, in both cases
    before any claim has been checked.
    """
    wanted = list(dict.fromkeys(page_ids))
    if not wanted:
        return {}
    by_point = {ids.point_id(page_id): page_id for page_id in wanted}
    records = client.retrieve(collection, ids=list(by_point), with_payload=True,
                              with_vectors=False)
    found = {by_point[str(record.id)]: (record.payload or {}) for record in records}
    missing = [page_id for page_id in wanted if page_id not in found]
    if missing:
        raise PageNotFound(missing)
    return found


def _uncheckable_reason(payload: Mapping[str, Any]) -> str | None:
    """Why this page cannot be checked, or ``None`` if it can be."""
    if not payload.get("is_current", False):
        return NOT_CURRENT
    if not payload.get("has_text", False):
        return "no_text"
    return UNCHECKABLE_TRUST.get(str(payload.get("text_trust") or "no_text"))


def check(client: Any, collection: str, claim: str, page_id: str,
          payload: Mapping[str, Any]) -> tuple[str, str]:
    """One ``(claim, page)`` pair → ``(state, reason)``.

    The one exact-match code path, scoped to one page. ``reason`` is empty for `present` and
    `absent`: a verdict that says why it could not look is useful, and a verdict that explains
    itself when it did look is noise.
    """
    reason = _uncheckable_reason(payload)
    if reason:
        return UNVERIFIABLE, reason
    query = exact_filter(claim, _page_scope(page_id), field="text")
    hit = client.count(collection, count_filter=query, exact=True).count
    return (PRESENT if hit else ABSENT), ""


def page_checks(client: Any, collection: str, claims: Sequence[str], page_ids: Sequence[str],
                *, payloads: Mapping[str, Mapping[str, Any]] | None = None,
                ) -> dict[str, dict[str, tuple[str, str]]]:
    """The whole matrix: ``claim → page_id → (state, reason)``.

    This — not the folded verdict — is what the answer gate consumes (I8, U022): *"is this code
    verified on the page this sentence cites?"* is a question about a pair, and a per-claim summary
    cannot answer it for a draft that cites two pages.

    ``payloads`` lets a caller that has already retrieved the pages hand them in, so a `verify`
    costs one retrieve and not two.
    """
    if payloads is None:
        payloads = page_payloads(client, collection, page_ids)
    ordered = list(dict.fromkeys(page_ids))
    return {
        claim: {page_id: check(client, collection, claim, page_id, payloads[page_id])
                for page_id in ordered}
        for claim in dict.fromkeys(claims)
    }


def _fold(states: Mapping[str, tuple[str, str]], claim: str,
          inventory: Inventory | None) -> ClaimVerdict:
    """One claim's pages → one verdict (§7.2.4).

    * **present** — at least one page carries it; ``page_ids`` names those pages and only those.
    * **absent** — at least one page was checked and none carried it; ``page_ids`` names the pages
      the absence is asserted about, so a caller can see that it is not necessarily the whole set
      they asked about. This is also the only verdict that carries ``present_instead``.
    * **unverifiable** — nothing could be checked. ``reason`` is the shared reason where the pages
      agree, and ``mixed`` where they do not, because a single page's reason would be a lie about
      the others.
    """
    present_on = [page_id for page_id, (state, _) in states.items() if state == PRESENT]
    if present_on:
        return ClaimVerdict(status=PRESENT, page_ids=present_on)

    checked = [page_id for page_id, (state, _) in states.items() if state == ABSENT]
    if checked:
        return ClaimVerdict(
            status=ABSENT,
            page_ids=checked,
            present_instead=present_instead(claim, inventory) if inventory else [],
        )

    reasons = {reason for _, reason in states.values() if reason}
    return ClaimVerdict(status=UNVERIFIABLE,
                        reason=reasons.pop() if len(reasons) == 1 else ("mixed" if reasons else ""))


def local_inventory(payloads: Mapping[str, Mapping[str, Any]]) -> Inventory | None:
    """The observed-token inventory of **the pages named in this call**.

    §6.8 keeps the canonical inventory per document, on the run's control point, and U011 writes
    it; before that exists — and whenever a caller wants the tighter statement — this is the
    honest local reading of *"present instead"*: the code-like tokens on the very pages the claim
    was checked against, rather than anything else in the binder. Both are prefix lookups over
    observed text; this one cannot disclose a code from a page the caller never asked about.

    Only the **searchable** pages of the set contribute (§5.7): a page this call is about to answer
    `unverifiable` for must not be the source of what is there "instead" either.
    """
    by_doc = from_records([payload for payload in payloads.values() if is_searchable(payload)])
    if len(by_doc) != 1:
        # Pages from two documents share no inventory, and merging them would let a code from one
        # binder be disclosed as what is "instead" on a page of another.
        return None
    return next(iter(by_doc.values()))


def verify_claims(client: Any, collection: str, claims: Sequence[str], page_ids: Sequence[str],
                  *, inventory: Inventory | None = None) -> VerifyResult:
    """Every claim, checked against every named page, folded into one verdict each.

    Returns the ``result`` half of the Family B envelope (§7.1): a `verify` in which every claim is
    `absent` is a perfectly good ``status: ok``, because the call ran and the answer is no. The
    envelope, the budget and the HTTP status are the tool wrapper's (U015); nothing about the
    verdict changes there.

    ``inventory`` overrides the default :func:`local_inventory` with the document-level inventory
    of §6.8 once U011 writes it.
    """
    payloads = page_payloads(client, collection, page_ids)
    matrix = page_checks(client, collection, claims, page_ids, payloads=payloads)
    disclosure = inventory if inventory is not None else local_inventory(payloads)
    return VerifyResult(claims={claim: _fold(states, claim, disclosure)
                                for claim, states in matrix.items()})
