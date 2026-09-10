"""The runner's system prompt — Spec §8, stated to a model in the words the machine enforces.

This module renders text and does nothing else: no call, no state, no configuration read. It is
the **second** reader of :data:`~vsir.runner.triage.SAFEGUARDS`, and that is its whole design.
§8.2 requires the five safeguards to bind *"in the system prompt and in the runner's state
machine"*, and the only way two statements of a rule stay the same rule is for there to be one
statement: :mod:`vsir.runner.triage` holds the text, enforces it in code, and this module prints
it. A safeguard edited in one place is edited in both, and the suite asserts the prompt carries
all five.

**Why the prompt is not enough on its own, said in the prompt's own file.** R6: prompt-level rules
are advisory the moment a client drives the raw MCP surface. Everything that must not be optional
is server-side — the §7.3 caps, the budget, `read`'s per-code stamp and the answer gate of §8.4 —
and this text tells the model what the server will do to it rather than asking it to be careful.

**Deterministic by construction.** The same :class:`PromptInputs` renders byte-identical text, and
:func:`digest` is over those bytes. That is not tidiness: a prompt is a cache-key input wherever
a released prompt reaches a paid call (§6.3, F11), so a prompt that varied with dict ordering or
a timestamp would be a prompt whose cache hits were lies. Nothing here reads the clock, the
environment or a set.

**Text in Python, not a packaged ``.md``,** unlike ``vlm/prompts/``. Those three files are inputs
to a *billed* call and are pinned by digest to ``VSIR_PROMPT_VERSION``, so editing one without
releasing a version would serve frozen responses produced by instructions that no longer exist.
This prompt is composed per question from the tools a release actually serves and from the budget
in force, so it has no fixed bytes to pin — and putting it under the same version label would
re-key every frozen S2 response in the repository whenever a safeguard's wording changed.
:data:`RUNNER_PROMPT_VERSION` is its own label, moving on its own.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Sequence

from vsir.config import DPI_ANSWER, MAX_READ_PAGES
from vsir.runner import triage as triage_module
from vsir.runner.route import FETCH, READ
from vsir.serve.caps import MAX_FETCH_PAGES

#: This prompt's own version label, released with the code. Bump it when the text below changes
#: in a way a cached answer must not survive — it is an input to U022's `ask` key, and it is
#: deliberately **not** ``VSIR_PROMPT_VERSION``, which pins the three extraction prompts (§6.3).
RUNNER_PROMPT_VERSION = "runner-v1"


@dataclass(frozen=True)
class PromptInputs:
    """Everything the text varies on. A frozen value, so the same inputs are the same bytes.

    ``tools`` is the release's own table — the names this release actually serves — rather than
    §7.2's list, because a prompt that offers a tool the dispatcher answers `404 tool_not_found`
    for is a prompt that spends a turn discovering the release it is talking to.
    """

    #: The tool names served, in the order they are to be listed. The caller passes them sorted.
    tools: tuple[str, ...] = ()
    #: `VSIR_READS_PER_QUESTION` — the hard ceiling of §8.4, stated so the model can plan for it.
    reads_per_question: int = 3
    #: Whether the runner can look at a raster itself. Decides which route the text calls default.
    vision_capable: bool = True
    #: The documents in scope, if the caller has already narrowed. Empty means the whole corpus.
    scope: tuple[str, ...] = field(default_factory=tuple)


def _bullets(items: Sequence[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def safeguards() -> str:
    """The five rules of §8.2, numbered, from the one definition that also enforces them."""
    return "\n".join(f"{n}. **{name}** — {rule}"
                     for n, (name, rule) in enumerate(triage_module.SAFEGUARDS, start=1))


def build(inputs: PromptInputs) -> str:
    """The system prompt. Pure: same inputs, same bytes, no clock and no environment."""
    route_default = (
        f"**Default: `{FETCH}`.** You can see. Look at the page yourself — that is the move a "
        f"person makes on a schematic, and it costs no money at all."
        if inputs.vision_capable else
        f"**You cannot see a raster**, so the look step is `{READ}` — a sub-model looks for you "
        f"and returns a bounded extract with every code stamped. `{FETCH}` would hand you bytes "
        f"you cannot read."
    )
    scope = (f"You are scoped to: {', '.join(inputs.scope)}. Say so when you abstain."
             if inputs.scope else
             "No scope has been fixed for you. Narrow before you look, and echo back the scope "
             "you searched when you abstain.")
    return f"""\
You answer questions about technical documentation — manuals, schematics, safety lists — and the
one thing you may never do is state a code, part number, terminal or reference that is not
printed on the page you cite it on. A plausible wrong code in this corpus is worse than no
answer: thousands of codes differ from another real code by one character, and the reader acts on
what you say.

# The loop

1. **Narrow, for free.** `skim_documents` → `skim_sections` → `skim_pages`, or `lookup` when you
   already hold an exact code. The same move at three zoom levels; every rung is free.
2. **Triage the candidates, for free.** See below. This is the cheapest correction there is.
3. **Look, once, late.** One look at the page images, after narrowing — never before.
4. **Draft from what you saw.**
5. **Verify, then answer.** `verify(claims, page_ids)` after drafting, not before.

{scope}

# The tools this release serves

{_bullets(inputs.tools) if inputs.tools else "- (none registered)"}

# Triage — mark every candidate, in three states

Mark each row `relevant`, `uncertain` or `irrelevant` from its summary, its `why`, its
`grounded_rate` and its `text_trust` — before anything is spent. `relevant` goes to the look step,
`uncertain` goes to a pool you keep, `irrelevant` goes into `exclude` on the next skim.

Never mark in two states. The `uncertain` pool is what makes a rejection cost one more look
instead of a whole new search, and a summary that omitted the line that mattered is the ordinary
case, not the rare one.

{safeguards()}

# Where the answer comes from

No answer is composed from text alone. Narrowing is text-driven because it has to be cheap, but
the draft is written against a page image.

- `{FETCH}` — you look. Up to {MAX_FETCH_PAGES} pages, all of them in one context, follow-ups
  free, and you can crop a corner with `region` at a higher dpi. Costs nothing but your own
  context.
- `{READ}` — a sub-model looks. Up to {MAX_READ_PAGES} pages at the pinned dpi {DPI_ANSWER}, one
  independent extract per page, every code stamped `present` / `absent` / `unverifiable`, and a
  mandatory `sufficient`. It spends the budget; a follow-up re-bills the whole call.

{route_default}

Use `{READ}` to delegate: to keep your context small on a long trace, or when the caller cannot
see images. Not to see — you cannot ask it a second question for free.

# What it costs, and what stops you

- You have {inputs.reads_per_question} `{READ}` call(s) for this question. Every response carries
  `reads_remaining`; when it reaches zero the next one is refused `429 budget_exhausted`. There is
  no silent extra call, and never an answer composed from a page the sub-model said did not
  answer.
- Every code in your draft is checked server-side against the page you cited it on, before any
  prose is rendered: `present` renders, `unverifiable` renders badged *read from image, not
  text-verified*, anything else rejects the draft. Taking the `{FETCH}` route skips the automatic
  per-code stamp `{READ}` does, which is why the check is unconditional — do not read a code off a
  raster and assert it.
- Do not say *"not in these documents"* while image-only pages in scope are unexamined. Name the
  gap instead: the documents searched, and the count of image-only pages nobody looked at.
"""


def digest(text: str) -> str:
    """``sha256`` over the rendered bytes — what a cache key and an audit line carry."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
