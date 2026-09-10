"""The agentic runner of Spec §8 — the loop that narrows, triages, looks, drafts and is gated.

Three modules arrive with U021 and none of them spends anything, which is the point §8.2 makes in
one clause: *"for free, before any money is spent"*. :mod:`vsir.runner.triage` marks every skim
candidate `relevant` / `uncertain` / `irrelevant` and holds the five safeguards **and** the state
machine they bind; :mod:`vsir.runner.route` makes §8.1a's deliberate `fetch`-versus-`read` choice;
:mod:`vsir.runner.prompt` renders the system prompt that states the same rules to a model.

`loop.py` and `answer.py` — the loop that executes the machine and the server-side answer gate
(I8) — are U022's, and nothing here drafts, composes or renders prose.
"""
