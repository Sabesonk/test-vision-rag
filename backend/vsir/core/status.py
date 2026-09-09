"""The status enum (Spec §7.1, I5) — six values, four of which are absences.

`impl`'s own docstring called an empty ``200`` *"the agent's designed abstention path"*. It is the
one thing this CR deliberately breaks (§2.5 D1), because those four absences are four different
instructions to the caller and collapsing them into an empty list makes the agent guess:

* ``not_found`` — searched, genuinely absent. Abstain… unless ``next.suggest`` says another *move*
  could still answer, which is how a phrasing accident stops becoming an abstention.
* ``not_searchable`` — the candidate pages have no text layer. Escalate to vision, do not conclude
  the part does not exist (F4).
* ``out_of_scope`` — no document matched the filters. Re-orient and widen; the corpus was never
  asked.
* ``found_only_in_superseded`` — it exists, in a revision that is not current. Surface the revision
  and let the caller decide (F9).
* ``error`` — retry or report, and **never** abstain. An outage returned as an absence is our
  failure rendered as the caller's fabricated confidence.
"""
from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    """The six values. There is no seventh, and no empty ``ok``."""

    OK = "ok"
    NOT_FOUND = "not_found"
    NOT_SEARCHABLE = "not_searchable"
    OUT_OF_SCOPE = "out_of_scope"
    FOUND_ONLY_IN_SUPERSEDED = "found_only_in_superseded"
    ERROR = "error"


#: The four absences — every one of them a `status` a Family A response can carry with no hits.
ABSENCES = (
    Status.NOT_FOUND,
    Status.NOT_SEARCHABLE,
    Status.OUT_OF_SCOPE,
    Status.FOUND_ONLY_IN_SUPERSEDED,
)

#: The vocabulary of a per-item check (§7.2.4, §7.2.6). Deliberately **not** a boolean, and
#: deliberately not this module's `Status`: "is this code on this page?" has three answers, and
#: `unverifiable` — no text layer to check against — is the one a boolean would have to lie about.
#: `verified` stays a boolean and only ever describes which surface a `lookup` hit came from.
CHECK_STATES = ("present", "absent", "unverifiable")
