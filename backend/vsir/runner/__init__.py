"""The agentic runner of Spec §8 — the loop that narrows, triages, looks, drafts and is gated.

Five modules, and the order they are read in is the order a question moves through them:

* :mod:`vsir.runner.triage` — Loop 0. Every skim candidate marked `relevant` / `uncertain` /
  `irrelevant` from its summary row, **for free, before any money is spent** (§8.2), plus the five
  safeguards and the state machine they bind;
* :mod:`vsir.runner.route` — §8.1a's deliberate `fetch`-versus-`read` choice: who looks at the
  pixels, the calling agent or a sub-model;
* :mod:`vsir.runner.prompt` — the system prompt, which states the same rules to a model that the
  machine enforces in code (§8.2 requires both);
* :mod:`vsir.runner.loop` — §8.1's machine, executed, and §8.3's six correction loops;
* :mod:`vsir.runner.answer` — §8.4's server-side answer gate (I8) and §8.5's constrained
  abstention wording.

**Only two things here can spend anything, and neither of them decides to.** The loop's look step
calls `read`, which bills a model call and is bounded by `VSIR_READS_PER_QUESTION`; everything
else — the descent, the triage, the route, the gate's `verify` calls, the abstention — is free.
Triage and routing are settled *before* the paid step by construction rather than by discipline:
`read` is reachable in :mod:`~vsir.runner.loop` from exactly one method.

**Nothing here composes prose.** The answer's words are the sub-model's bounded extract or the
calling agent's own draft, rendered only after the gate cleared every code in it against the page
it is cited on. A function in this package that paraphrased a technical answer would be composing
one, which §7.6 refuses, and a paraphrase is also where a cleared code turns into an uncleared one.
"""
