"""Evaluation corpora and the commands that run them (Spec §12.3, §12.4, §12.6).

Net new, and recorded in the plan as a deliberate extension of §4.1's layout (SA-5): the spec's
tree enumerates no `eval/` package while §12.3, §12.4 and §12.6 all require evaluations that must
be runnable as `vsir` subcommands (§15 Factor XII). This is where the corpus a command evaluates
*against* is assembled — never where a rule about correctness lives, which stays in `core/`.

At M1 there is one member: the synthetic corpus of §13, which is hand-written page text with no
PDF, no VLM and no spend. `vsir eval acceptance` / `vsir eval abstention` (U016) and the corpus
report of §12.6 (U026) join it later.
"""
