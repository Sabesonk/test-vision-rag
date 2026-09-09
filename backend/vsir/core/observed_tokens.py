"""The observed-token inventory (Spec §6.8, C7) — **display-only**, and structurally unreachable
from `lookup` and `verify`.

`present_instead` is the disclosure beside an `absent` verdict: *"K73 is not on this page; K78 is"*.
plan2 specified it as a "prefix filter on observed tokens" and gave it nowhere to live (C7), so
this module is that home — the set of tokens the **text layer** actually carries, per document.

Three properties make it safe, and all three are structural rather than a matter of care:

* **It is built from ``text`` and from nothing else.** Not from `vlm_codes`, not from
  `content.codes`. A code the model claimed and the text layer never backed is absent from this
  inventory, so it can never be disclosed as the thing that is there instead (I2). That is why
  :func:`from_records` reads ``record.text`` and no other field.
* **A prefix lookup is not a distance.** The only query this structure answers is *"which observed
  tokens start with this string?"* — :meth:`Inventory.starting_with`, a binary search over a sorted
  tuple. There is no edit distance, no similarity, no ranking, so a near-miss code cannot be
  returned *as* a match (F16, §7.6). The capping at 5 and the *"different part"* labelling belong
  to `core/present_instead.py` (U006), which is the only consumer.
* **Only a searchable page contributes.** §5.7 makes `untrusted` and `no_text` unsearchable for
  `lookup` and unverifiable for `verify`, and the same rule applies here: a page whose text layer
  nobody may be told is evidence must not be volunteering codes either. Left in, a garbled
  extraction's debris — ``rai1`` for *"rail"* — would come back beside an `absent` verdict as a
  *"different part"*, which is noise presented as knowledge. :func:`is_searchable` is the
  predicate, applied at the call site so it is visible rather than implied.
* **The code-like heuristic is display-only** — §6.8, verbatim: *a token containing at least one
  digit*, and *unreachable from `lookup` and `verify`, enforced by module boundary*. Nothing in
  `serve/tools/lookup.py` imports this module, and an import-graph test asserts it. The heuristic
  is allowed to be crude precisely because a miss costs a disclosure, never an answer: a caller
  sees one fewer suggestion beside a verdict that was already `absent`.

**Where it lives at rest.** §6.8 stores the inventory as payload on the document's control point in
`vsir_runs` (D9) and holds it in an in-process LRU cache for the prefix lookup — the writer and the
cache arrive with U011. At M1 there is no PDF and no run, so the inventory is built from the seeded
pages by :func:`from_records`, which is what makes `present_instead` testable before any document
has been ingested.
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from typing import Iterable, Mapping

from vsir.core.record import UNSEARCHABLE_TRUST
from vsir.core.tok import tok


def is_code_like(token: str) -> bool:
    """§6.8's heuristic: a token containing at least one digit.

    Deliberately not a grammar. §5.2 prohibits an identifier grammar anywhere in extraction or
    derivation, and this is the reason the crude version is the right one: ``k158``, ``0020`` and
    ``5b`` are in, ``emergency`` and ``quantity`` are out, and no per-corpus regex decides which
    shapes of code the system is able to talk about.
    """
    return any(character.isdigit() for character in token)


def is_searchable(record: object) -> bool:
    """Whether this page's text may contribute observed tokens (§5.7).

    ``has_text`` and a ``text_trust`` outside :data:`~vsir.core.record.UNSEARCHABLE_TRUST` — the
    same two conditions `lookup` filters on and `verify` refuses on, so the inventory can never
    disclose a code from a page the caller is not allowed to be shown a hit from.
    """
    if isinstance(record, Mapping):
        has_text, trust = record.get("has_text", False), record.get("text_trust", "no_text")
    else:
        has_text = getattr(record, "has_text", False)
        trust = getattr(record, "text_trust", "no_text")
    return bool(has_text) and str(trust) not in UNSEARCHABLE_TRUST


@dataclass(frozen=True)
class Inventory:
    """One document's observed code-like tokens, sorted and unique.

    Frozen and self-contained: it holds no client, no collection name and no page ids, so it can be
    cached, serialised to the §6.8 export line, or rebuilt from the index without changing anything
    that reads it.
    """

    doc_id: str
    #: Sorted, unique, lowercase, every one code-like. Sorted because a prefix lookup over a sorted
    #: sequence is a binary search, and because the export line must be stable between runs.
    tokens: tuple[str, ...]

    def __contains__(self, token: str) -> bool:
        index = bisect_left(self.tokens, token)
        return index < len(self.tokens) and self.tokens[index] == token

    def __len__(self) -> int:
        return len(self.tokens)

    def starting_with(self, prefix: str) -> tuple[str, ...]:
        """Every observed token beginning with ``prefix``, in sorted order.

        The **whole** query surface of this module. An empty prefix returns nothing rather than the
        entire inventory: "every code in the document" is not a disclosure about a claim, and a
        caller that asked for it by accident should get silence rather than a dump.
        """
        if not prefix:
            return ()
        prefix = prefix.lower()
        start = bisect_left(self.tokens, prefix)
        found: list[str] = []
        for token in self.tokens[start:]:
            if not token.startswith(prefix):
                break
            found.append(token)
        return tuple(found)


def from_texts(doc_id: str, texts: Iterable[str]) -> Inventory:
    """Build one document's inventory from its pages' extracted text.

    ``texts`` is the ``text`` payload field of the document's pages — the surface `ingest/probe.py`
    owns (I2). A page with no text layer contributes nothing, which is correct rather than a gap:
    there is no observed token on a page nothing was observed from.
    """
    observed = {token for text in texts for token in tok(text) if is_code_like(token)}
    return Inventory(doc_id=doc_id, tokens=tuple(sorted(observed)))


def from_records(records: Iterable[object]) -> dict[str, Inventory]:
    """Group :class:`~vsir.core.record.PageRecord`-shaped objects by ``doc_id`` and build each one.

    Typed loosely on purpose: the input is anything carrying ``doc_id`` and ``text``, so a payload
    dict scrolled straight out of Qdrant works as well as a record — the inventory is a projection
    of two fields and has no reason to demand the whole model.
    """
    texts: dict[str, list[str]] = {}
    for record in records:
        if isinstance(record, Mapping):
            doc_id, text = str(record.get("doc_id", "")), str(record.get("text", ""))
        else:
            doc_id, text = str(getattr(record, "doc_id", "")), str(getattr(record, "text", ""))
        texts.setdefault(doc_id, []).append(text)
    return {doc_id: from_texts(doc_id, pages) for doc_id, pages in sorted(texts.items())}
