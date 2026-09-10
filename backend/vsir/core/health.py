"""Health signals (Spec §5.7) — net new. How much of a page's text layer may be believed.

`impl` has nothing like this. Its equivalent of "did the extraction work" was the allowlist gate's
`withheld` count, which is a different question with a different answer: the gate decided what a
caller was *allowed to find*, this decides what a caller is *told to trust*. The gate is struck
(§2.4, §2.5 B) and its replacement is disclosure — four signals, computed structurally, carried on
the record and surfaced by the tools.

**The `None`, which is the whole module.** `grounded_rate` is defined only where there is a text
layer to be grounded in. A scanned page has codes the model read off the raster and nothing to
check them against, so a numeric `0.0` there does not say "extraction is broken" — it says
"there was nothing to check". Scoring it 0 would drag the document median under §11.1's blocking
gate and quarantine exactly the scanned documents F4 requires to be *published and unsearchable*.
So the rate is `None` on `has_text == false`, and every aggregate here **ignores those pages**
rather than defaulting them to anything: :func:`median` takes the median of the pages that have a
rate, and returns `None` when none of them do.

**One question about membership, asked once.** Whether a code is printed on a page is
:func:`vsir.core.exact.printed_in` — a phrase over `variants()`, which is what `exact_filter` asks
the index (§5.6, I3). It is *not* a `token_set` intersection: `SF 1.2A` is three tokens under
Qdrant's WORD tokenizer and can never be an element of a token set, and §5.6 deleted `impl`'s
adjacent-token joins — the thing that used to paper over that — precisely because phrases replace
them. A set intersection would ground six of a typical page's ten codes and put a healthy
document under the 0.8 gate.

**The trust ladder is a pin, not configuration.** `ok`/`degraded`/`untrusted` come from two
thresholds that are code, reviewed and released: a deployment that could re-tune what "trusted"
means would be a deployment that could turn F14 back on by editing an env var.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median as _median
from typing import Iterable, Sequence

from vsir.core.exact import printed_in
from vsir.core.record import TextTrust
from vsir.core.tok import tok

#: At or above this share of its codes grounded, a page's text layer is `ok`. The same number
#: §11.1 gates the document median on, deliberately: two thresholds for one judgement would let a
#: page be individually trusted in a document the gate refuses to publish. **Provisional — set
#: from the M2b distribution (R4).**
TRUST_OK_MIN = 0.8

#: Below this, the text layer is `untrusted` and the page counts as unsearchable (§5.7, §11.3).
#: §5.7's own example is the shape of it: *40 seen · 0 grounded* on a page that has text is not a
#: page with a few OCR-ish slips, it is a page whose extraction did not work.
TRUST_UNTRUSTED_BELOW = 0.2


def grounded_codes(codes: Iterable[str], text: str) -> tuple[str, ...]:
    """The codes of ``codes`` that are printed on ``text``, verbatim and in the order given.

    One tokenisation of the page for the whole list: a 1,440-page manual with forty codes a page
    would otherwise tokenise the same text forty times.
    """
    tokens = tok(text)
    return tuple(code for code in codes if printed_in(tokens, code))


def codes_in_text(grounded: Iterable[str]) -> list[str]:
    """§6.8's export field: the grounded codes, whitespace-collapsed, lowercased and sorted.

    This **is** the old `verified_identifiers[]` (C8) — computed structurally from what the page
    prints, rather than decided by a curated allowlist. The collapsing is the only normalisation
    (§5.2): ``"SF  1.2A"`` and ``"SF 1.2A"`` are one entry, ``K73`` and ``K78`` never are.
    """
    return sorted({" ".join(code.split()).lower() for code in grounded if code.strip()})


def grounded_rate(seen: int, grounded: int, *, has_text: bool) -> float | None:
    """§5.7 — the share of the model's codes the text layer backs, or ``None`` where it cannot.

    A page that has text and no codes rates **1.0**, not 0.0 and not `None`: nothing was claimed,
    so nothing is unbacked. A page with no text layer rates `None` however many codes were read
    off its raster.
    """
    if not has_text:
        return None
    if seen <= 0:
        return 1.0
    if not 0 <= grounded <= seen:
        raise ValueError(f"grounded {grounded} is not within 0..{seen} codes seen")
    return grounded / seen


def page_trust(rate: float | None, *, has_text: bool) -> TextTrust:
    """One page's `text_trust` from its own `grounded_rate` (§5.7).

    ``no_text`` is final and nothing promotes it — `ingest/probe.py` decides that, and a page with
    no text layer has no rate to reconsider it with.
    """
    if not has_text:
        return "no_text"
    if rate is None:
        # has_text with no rate is not reachable through `grounded_rate` above; if a caller
        # constructs it anyway, the honest reading is that nothing was measured.
        return "degraded"
    if rate >= TRUST_OK_MIN:
        return "ok"
    return "degraded" if rate >= TRUST_UNTRUSTED_BELOW else "untrusted"


def median(rates: Iterable[float | None]) -> float | None:
    """The median over the pages that **have** a rate. ``None`` when none of them do.

    The `None`s are dropped rather than defaulted, which is the aggregate half of §5.7's rule. A
    fully scanned document therefore has no median at all — and §11.1 skips its `grounded_rate`
    gate entirely rather than failing it against a number nobody could measure.
    """
    measured = [rate for rate in rates if rate is not None]
    return float(_median(measured)) if measured else None


def searchable_ratio(has_text: Sequence[bool]) -> float:
    """§5.7 — pages with a text layer ÷ pages. The agent's blind spot, made a number.

    Zero pages is 0.0 rather than a division error: a document with no pages is not searchable,
    and the caller of `skim_documents` gets a number rather than a 500.
    """
    return (sum(1 for flag in has_text if flag) / len(has_text)) if has_text else 0.0


@dataclass(frozen=True)
class DocumentHealth:
    """The document-level reading of §5.7, computed once over the derived pages.

    Frozen and derived: it holds no client and no run, so the gates of §11.1 (U011), the
    `skim_documents` row of §7.2.1 (U019) and the demo all read the same numbers rather than each
    recomputing them slightly differently.
    """

    page_count: int
    pages_with_text: int
    searchable_ratio: float
    #: `None` where **no** page of the document has a text layer — see :func:`median`.
    grounded_median: float | None
    #: The document's own trust level, from the median. `no_text` when nothing has text.
    text_trust: TextTrust

    @property
    def fully_scanned(self) -> bool:
        """§11.1 — at 0.0 text coverage the `grounded_rate` gate is skipped, never failed (F4)."""
        return self.pages_with_text == 0

    @property
    def collapsed(self) -> bool:
        """§11.3 — the document's `grounded_rate` collapsed, so every page is untrusted."""
        return self.text_trust == "untrusted"


def document_health(rates: Sequence[float | None], has_text: Sequence[bool]) -> DocumentHealth:
    """The four document-level signals of §5.7 from the per-page ones.

    ``rates`` and ``has_text`` are page-parallel, and the pairing is checked rather than zipped
    short: a silent truncation here would compute a median over a prefix of the document.
    """
    if len(rates) != len(has_text):
        raise ValueError(f"{len(rates)} rate(s) for {len(has_text)} page(s): not page-parallel")
    with_text = sum(1 for flag in has_text if flag)
    grounded_median = median(rates)
    return DocumentHealth(
        page_count=len(has_text),
        pages_with_text=with_text,
        searchable_ratio=searchable_ratio(has_text),
        grounded_median=grounded_median,
        text_trust=page_trust(grounded_median, has_text=with_text > 0),
    )


def demote(page: TextTrust, document: TextTrust) -> TextTrust:
    """§11.3 — a page is never more trusted than the document it came from.

    The row is *"a document's `grounded_rate` collapses ⇒ its pages count as unsearchable"*. It
    has to reach the pages, because `lookup` filters and `verify` refuses per page (§5.7): a
    document-level number nothing on a page reflects would be a signal with no effect.
    ``no_text`` is never overwritten — a page with no text layer is already unsearchable and the
    reason it is unsearchable is a fact about that page, not about the document.
    """
    if page == "no_text":
        return page
    return "untrusted" if document == "untrusted" else page
