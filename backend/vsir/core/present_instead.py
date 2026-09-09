"""``present_instead`` (Spec §7.2.4, C7, F16) — a capped prefix lookup, labelled *"different part"*.

The disclosure beside an `absent` verdict: *"K73 is not on this page. K78 is."* It exists because
the alternative is worse in both directions — an agent told only *"absent"* about a code it read off
a schematic will often try again with the same wrong string, and an agent given a *nearest match*
will cite it.

So the mechanism is deliberately weak, and every part of that weakness is the point:

* **A prefix, never a distance.** The only question asked of the inventory is *"which observed
  tokens start with this?"* (:meth:`~vsir.core.observed_tokens.Inventory.starting_with`). There is
  no edit distance, no similarity library and no ranking anywhere in this system (§7.6), so
  ``K73`` can surface ``K78`` — they share the prefix ``k7`` — and can never surface ``Q78``,
  ``K8`` or anything that differs before the prefix ends.
* **Truncation is bounded.** At most :data:`MAX_TRUNCATION` characters come off the claim before
  the search gives up, and no prefix shorter than :data:`MIN_PREFIX` is ever tried. Without the
  floor, ``K73`` would fall back to the prefix ``k`` and disclose every contactor in the document,
  which is noise dressed as help.
* **It is capped at five and it can never be the answer.** The claim itself is excluded, the list
  is truncated to :data:`PRESENT_INSTEAD_CAP`, and no caller may present it as a match: the label
  is :data:`PRESENT_INSTEAD_LABEL` — *"different part"* — and never *"did you mean"*. The §12.4
  eval asserts on all 100 near misses that the fake never appears in its own
  ``present_instead``, which is F16 stated as a test.

The inventory this reads is display-only and unreachable from `lookup` (§6.8): a `lookup` that
could consult it could return a near miss as a hit, which is the injury the whole design exists to
prevent.
"""
from __future__ import annotations

from vsir.core.observed_tokens import Inventory
from vsir.core.tok import tok

#: §7.2.4 — *"capped at 5"*.
PRESENT_INSTEAD_CAP = 5

#: How the disclosure must be presented. Not *"did you mean"*, not *"closest match"*: this is a
#: statement about what the page carries, never a suggestion that the claim was nearly right.
PRESENT_INSTEAD_LABEL = "different part"

#: No prefix shorter than this is tried. Two characters of a code is already thin; one is a letter.
MIN_PREFIX = 2

#: How many characters may come off the end of the claim while looking for a shared prefix. This is
#: **not** an edit distance in disguise: a truncation can only ever reach tokens that agree with the
#: claim from the first character onwards, so it cannot wander the way a distance can.
MAX_TRUNCATION = 2


def claim_key(claim: str) -> str:
    """The claim as a single lowercase token — the form the inventory is keyed on.

    ``"K73"`` → ``"k73"``, ``"SF 1.1A"`` → ``"sf11a"``. Whitespace and punctuation come out because
    :func:`~vsir.core.tok.tok` is what built the inventory in the first place, and the two must key
    the same way or a prefix would never match anything.
    """
    return "".join(tok(claim))


def present_instead(claim: str, inventory: Inventory,
                    cap: int = PRESENT_INSTEAD_CAP) -> list[str]:
    """Observed tokens that share a prefix with ``claim``, at most ``cap`` of them.

    Returns ``[]`` — not a guess — when nothing shares a long enough prefix. An empty disclosure
    beside an `absent` verdict is the honest common case: most absent codes are simply not in the
    document at all.
    """
    key = claim_key(claim)
    if len(key) < MIN_PREFIX:
        return []

    shortest = max(MIN_PREFIX, len(key) - MAX_TRUNCATION)
    for length in range(len(key), shortest - 1, -1):
        found = [token for token in inventory.starting_with(key[:length]) if token != key]
        if found:
            # The longest prefix that finds anything wins: it is the most specific true statement
            # available, and stopping there is what keeps the list short without ranking it.
            return found[:cap]
    return []
