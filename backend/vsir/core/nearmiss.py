"""The adversarial near-miss generator (Spec §12.4) — the safety test's input.

§12.4 is the one test whose failure means the system has produced the injury the whole design
exists to prevent: a code that is one character from a real one, presented as an answer. This
module manufactures those codes, and it does it from **whatever corpus is indexed** — the synthetic
seed at M1, the real fixture after M2b — by mutating one character of tokens taken from the
observed-token inventory (§6.8).

That is what resolves OQ-4 by design. The 8,414-near-pair list may or may not ever arrive; the eval
does not wait for it, and runs in CI from M1 onward. If the list does arrive it only widens the
sample.

**Three properties, each load-bearing:**

* **Exactly one character differs.** A substitution at one position, never an insertion, a deletion
  or a transposition — so every fake is the hardest possible case for a matcher that is even
  slightly fuzzy, and the assertion *"this must return nothing"* is unambiguous.
* **No fake is printed anywhere, in any spelling.** A mutation that lands on another real code is
  not a near *miss*, it is a code — and so is one that lands on a **phrase** the corpus prints.
  ``sf5`` mutates to ``sf1``, whose boundary-spaced variant is ``sf 1``, which is genuinely printed
  inside ``SF 1.1A``: `lookup` returns that page and is **right** to, because the phrase is there.
  Asserting on such a candidate would test the corpus rather than the system, so ``texts`` is how
  the generator is told what the corpus actually prints, and every variant of every candidate is
  checked against it (§5.6). Without ``texts`` the exclusion is the weaker token-level one, which
  is enough for a caller that only has an inventory.
* **It is deterministic.** No RNG and no seed: the same corpus produces the same 100 fakes in the
  same order, on every machine and every commit. A safety test that samples differently each run
  turns an intermittent defect into an intermittent build.

The generator carries the **source** beside each fake, because a near miss without the real code it
came from is unauditable: the first question when the eval fails is *"one character off what?"*
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Sequence

from vsir.core.exact import printed_in
from vsir.core.observed_tokens import Inventory
from vsir.core.tok import tok

#: The substitution alphabet: what a code can be misread as. Digits and lowercase letters, which
#: is exactly the character set Qdrant's WORD tokenizer leaves in a token (§5.6).
ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"

#: Sources shorter than this make poor near misses: a one- or two-character token has few
#: mutations and most of them are other real tokens (`3` → `4`).
MIN_SOURCE_LEN = 3

#: §12.4 asks for 100.
DEFAULT_SAMPLE = 100


@dataclass(frozen=True)
class NearMiss:
    """A fabricated code, and the real one it is one character from."""

    source: str
    fake: str
    #: 0-based index of the substituted character — enough to reproduce the case by hand.
    position: int


def mutations(token: str) -> Iterator[tuple[str, int]]:
    """Every one-character substitution of ``token``, in a fixed order.

    **Character-major, and positions from the last character backwards.** The order is the whole
    difference between a sample that is adversarial and one that is merely large:

    * the last character first, because ``K73`` for ``K78`` is what a misread code actually looks
      like, and because a late substitution shares the longest prefix with the real code — which
      is precisely the case where `present_instead` has something to say and therefore the case
      where F16 could be violated;
    * character-major, so consecutive draws from one source walk *backwards through its positions*
      rather than exhausting one position with 35 letters. A hundred fakes then differ at every
      position the corpus's codes have, instead of all differing at the same one.
    """
    for character in ALPHABET:
        for position in reversed(range(len(token))):
            if character != token[position]:
                yield token[:position] + character + token[position + 1:], position


def is_printed(candidate: str, printed: Sequence[Sequence[str]]) -> bool:
    """Whether any spelling of ``candidate`` occurs as a phrase in ``printed``.

    The same question `lookup` asks the index, asked locally — and asked through the same
    predicate derivation uses (:func:`~vsir.core.exact.printed_in`), so a "fabricated" code here
    and an ungrounded code at ingest cannot mean two slightly different things. ``printed`` is
    already tokenised because the eval checks a hundred candidates against the whole corpus.
    """
    return any(printed_in(sequence, candidate) for sequence in printed)


def near_misses(inventory: Inventory, n: int = DEFAULT_SAMPLE, *,
                texts: Iterable[str] = ()) -> tuple[NearMiss, ...]:
    """``n`` fabricated codes, spread round-robin across the inventory's longer tokens.

    Round-robin rather than token-by-token: taking the first 100 mutations of one token would test
    one code a hundred times. One mutation per source per pass means the sample covers as much of
    the corpus's shape as it can before it repeats a source.

    ``texts`` is the corpus's page text. Supply it wherever it is available — the eval scrolls it
    out of the index anyway — because it is what upgrades the exclusion from *"not a known token"*
    to *"not printed in any spelling"*.

    Returns fewer than ``n`` only when the inventory cannot produce that many — a corpus of two
    short codes has a limited supply — and a caller that needs exactly ``n`` should assert it
    rather than assume it.
    """
    printed = [tok(text) for text in texts]
    sources = [token for token in inventory.tokens if len(token) >= MIN_SOURCE_LEN]
    streams = {source: mutations(source) for source in sources}
    found: list[NearMiss] = []
    seen: set[str] = set()

    while len(found) < n and streams:
        for source in sources:
            stream = streams.get(source)
            if stream is None:
                continue
            for fake, position in stream:
                # A mutation that lands on a real code is not a near miss — skip it rather than
                # assert on it, or the eval would be testing the corpus instead of the system.
                if fake in inventory or fake in seen or is_printed(fake, printed):
                    continue
                seen.add(fake)
                found.append(NearMiss(source=source, fake=fake, position=position))
                break
            else:
                streams.pop(source, None)      # this source is exhausted
            if len(found) >= n:
                break
    return tuple(found)
