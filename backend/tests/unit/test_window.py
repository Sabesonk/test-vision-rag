"""L0/L1 — steps 04-05, the ladder and the cache keys (Spec §6.2, §6.3, §6.4, F13).

Two things are being proved here, and they fail in opposite directions.

The **ladder** must never quietly do the thing it cannot do. `impl`'s third rung is a blind
30-page fold with a carry chain, and v1 does not implement it (§2.5 B), so a document that needs
one has to fail by name — a blind cut that straddles a safety function across a fold is F8, and it
raises nothing. Likewise a window that comes back truncated must bisect and re-bill: keeping the
partial answer loses 30 pages of a manual and reports success (F13).

The **keys** must never quietly serve the wrong answer. `extract_key` exists so that re-running on
identical pages costs nothing; it earns that only if every input that can change the model's answer
is in it. So the tests are one per input, each asserting the key *moves*, plus one asserting it
does not move for anything else.
"""
from __future__ import annotations

import pytest

from vsir.config import CAP_PAGES_PER_WINDOW, DPI_ANSWER, DPI_INDEX
from vsir.eval import synthetic_pdf as generator
from vsir.ingest import probe, render
from vsir.ingest import window as w
from vsir.ingest.extract import S2_SCHEMA_HASH, WindowOut, schema_hash

MODEL = "gemini-3.8-flash-001"
PROMPT = "s2-v1"
HASHES = ("a" * 64, "b" * 64, "c" * 64)


def _key(hashes=HASHES, *, model=MODEL, prompt=PROMPT, dpi=DPI_ANSWER, schema=S2_SCHEMA_HASH):
    return w.extract_key(hashes, vlm_model=model, prompt_version=prompt, dpi=dpi,
                         schema_hash=schema)


# ── the ladder ──────────────────────────────────────────────────────────────────────────────────

def test_the_synthetic_corpus_plans_exactly_three_windows(synthetic_pdf, expected):
    """AC: three windows, each with a distinct `extract_key` (§6.2, Level 1)."""
    probed = probe.run(synthetic_pdf)
    plan = w.plan(probed.page_count, toc=generator.toc_entries(), size_bytes=probed.size_bytes,
                  document=expected["doc_id"])

    assert plan.level == expected["ladder_level"]
    assert [[win.start, win.end] for win in plan.windows] == expected["windows"]
    assert plan.covers(probed.page_count)
    assert plan.parallel is True

    keys = {
        w.extract_key(render.page_hashes(synthetic_pdf, win.page_numbers, dpi=DPI_ANSWER,
                                         content_hash=probed.content_hash),
                      vlm_model=MODEL, prompt_version=PROMPT, dpi=DPI_ANSWER,
                      schema_hash=S2_SCHEMA_HASH)
        for win in plan.windows
    }
    assert len(keys) == len(plan.windows)


def test_a_document_inside_the_cap_is_one_window():
    plan = w.plan(CAP_PAGES_PER_WINDOW, size_bytes=1024)

    assert plan.level == 0
    assert plan.windows == (w.Window(1, CAP_PAGES_PER_WINDOW, 0),)
    assert plan.covers(CAP_PAGES_PER_WINDOW)


def test_a_file_too_large_to_send_whole_leaves_level_zero():
    """Ported from `impl`: the page count is not the only ceiling on one pass."""
    with pytest.raises(w.LadderLevel2Required):
        w.plan(10, size_bytes=w.MAX_INLINE_BYTES + 1)


def test_level_one_cuts_on_the_chapters_and_covers_the_front_matter():
    plan = w.plan(42, toc=[{"page_no": 15}, {"page_no": 29}], size_bytes=1024)

    assert plan.level == 1
    assert [(win.start, win.end) for win in plan.windows] == [(1, 14), (15, 28), (29, 42)]


def test_ladder_level_2_required_when_s1_found_no_chapter():
    """§6.2 — never a blind cut. The refusal names the document, so an operator can act on it."""
    with pytest.raises(w.LadderLevel2Required) as refusal:
        w.plan(1440, toc=[], size_bytes=1024, document="LTC1AV81-MANUAL")

    assert refusal.value.code == "ladder_level_2_required"
    assert "LTC1AV81-MANUAL" in str(refusal.value)
    assert refusal.value.details["page_count"] == 1440
    assert refusal.value.to_payload()["error"] == "ladder_level_2_required"


def test_ladder_level_2_required_when_one_chapter_is_over_the_cap():
    """`impl`'s check is all-or-nothing and register A6 leaves that open; what changes here is
    that falling through is a named refusal rather than a blind fold."""
    with pytest.raises(w.LadderLevel2Required) as refusal:
        w.plan(80, toc=[{"page_no": 1}, {"page_no": 41}], size_bytes=1024, document="D")

    assert refusal.value.details["oversized_chapters"] == ["1-40", "41-80"]


def test_a_toc_entry_the_model_could_not_index_cuts_nothing():
    """A printed contents page shows printed labels, not PDF indices, so `page_no` comes back 0."""
    assert w.chapter_ranges([{"page_no": 0}, {"page_no": 999}], 42) == ()
    assert w.chapter_ranges([w.TocEntry(page_no=0), w.TocEntry(page_no=15)], 42) == ((1, 14),
                                                                                     (15, 42))


def test_the_level_two_rung_cannot_be_reached_by_configuration():
    """§2.5 B — the exclusion that changes what the POC can ingest. It is a constant, not a flag."""
    assert w.MAX_LADDER_LEVEL == 1


# ── bisection (F13) ─────────────────────────────────────────────────────────────────────────────

def test_oversized_window_bisects(expected):
    """F13 — on MAX_TOKENS the window splits and re-bills. Never pad, never accept a partial.

    The page set is the invariant: the union of the halves is the original, with no gap and no
    duplicate, so the document is still covered exactly once.
    """
    plan = w.plan(42, toc=generator.toc_entries(), size_bytes=1024)
    oversized = plan.windows[1]

    after = plan.bisect(oversized, "max_tokens")

    assert len(after.windows) == len(plan.windows) + 1
    assert [(x.start, x.end) for x in after.windows] == [(1, 14), (15, 21), (22, 28), (29, 42)]
    assert after.page_numbers == plan.page_numbers
    assert after.covers(42)
    assert sorted(after.page_numbers) == list(dict.fromkeys(after.page_numbers))
    assert [x.bisected_from for x in after.windows] == ["", "max_tokens", "max_tokens", ""]


def test_a_bisected_window_re_bills(synthetic_pdf):
    """The halves get new keys for free: `extract_key` is built from the page image hashes."""
    probed = probe.run(synthetic_pdf)
    plan = w.plan(probed.page_count, toc=generator.toc_entries(), size_bytes=probed.size_bytes)
    parent = plan.windows[0]
    left, right = w.bisect_window(parent, "truncated")

    keys = {
        window: w.extract_key(
            render.page_hashes(synthetic_pdf, window.page_numbers, dpi=DPI_ANSWER,
                               content_hash=probed.content_hash),
            vlm_model=MODEL, prompt_version=PROMPT, dpi=DPI_ANSWER, schema_hash=S2_SCHEMA_HASH)
        for window in (parent, left, right)
    }
    assert len(set(keys.values())) == 3


@pytest.mark.parametrize("reason", w.BISECT_REASONS)
def test_every_documented_trigger_bisects(reason):
    """§6.2 lists four: MAX_TOKENS, a truncated response, a schema-invalid one, and an offset
    failure. Each one splits and re-bills; none of them guesses."""
    left, right = w.bisect_window(w.Window(1, 30, 1), reason)

    assert (left.start, left.end, right.start, right.end) == (1, 15, 16, 30)
    assert left.bisected_from == right.bisected_from == reason


def test_a_trigger_the_spec_does_not_name_is_refused():
    with pytest.raises(ValueError):
        w.bisect_window(w.Window(1, 30, 1), "felt_like_it")


def test_window_unsplittable():
    """F13's floor: one page, still over budget. There is nothing left to split, and saying so is
    the only honest answer — padding it would publish a page the model never described."""
    with pytest.raises(w.WindowUnsplittable) as refusal:
        w.bisect_window(w.Window(7, 7, 1), "max_tokens")

    assert refusal.value.code == "window_unsplittable"
    assert refusal.value.details == {"page_no": 7, "reason": "max_tokens"}


def test_an_odd_window_bisects_without_losing_or_duplicating_a_page():
    left, right = w.bisect_window(w.Window(1, 25, 1), "offset")

    assert left.page_numbers + right.page_numbers == tuple(range(1, 26))


def test_bisecting_a_window_that_is_not_in_the_plan_is_a_programming_error():
    plan = w.plan(20, size_bytes=1024)

    with pytest.raises(ValueError):
        plan.bisect(w.Window(1, 5, 0), "max_tokens")


# ── the offset (§6.4) ───────────────────────────────────────────────────────────────────────────

def test_the_absolute_page_is_computed_in_exactly_one_place():
    """`abs_page = window.start + page_index - 1`, once, so no caller writes it again differently."""
    window = w.Window(15, 28, 1)

    assert window.absolute(1) == 15
    assert window.absolute(14) == 28
    assert [window.absolute(i) for i in range(1, window.pages + 1)] == list(window.page_numbers)


@pytest.mark.parametrize("page_index", [0, -1, 15])
def test_an_index_outside_the_window_raises_rather_than_clamping(page_index):
    """A clamp here shifts a citation onto a page the model never saw, and nothing else errors."""
    with pytest.raises(ValueError):
        w.Window(15, 28, 1).absolute(page_index)


def test_a_window_is_a_page_range_and_refuses_not_to_be():
    with pytest.raises(ValueError):
        w.Window(10, 9, 0)
    with pytest.raises(ValueError):
        w.Window(0, 5, 0)


# ── the keys (§6.3) ─────────────────────────────────────────────────────────────────────────────

def test_facts_key_is_stable_across_runs():
    """AC: the same document, the same configuration, the same key — so S1 is billed once."""
    first = w.facts_key("abc", vlm_model=MODEL, prompt_version=PROMPT)

    assert first == w.facts_key("abc", vlm_model=MODEL, prompt_version=PROMPT)
    assert len(first) == 64


@pytest.mark.parametrize(("field", "value"), [
    ("content_hash", "def"), ("vlm_model", "gemini-3.8-pro-001"), ("prompt_version", "s2-v2"),
])
def test_facts_key_changes_with_every_input(field, value):
    """Register B2 — caching S1 is what makes the ladder reproducible, and a key that missed one
    of these would make it reproducibly *wrong*."""
    inputs = {"content_hash": "abc", "vlm_model": MODEL, "prompt_version": PROMPT}
    baseline = w.facts_key(inputs.pop("content_hash"), **inputs)
    changed = dict(content_hash="abc", vlm_model=MODEL, prompt_version=PROMPT)
    changed[field] = value

    assert w.facts_key(changed.pop("content_hash"), **changed) != baseline


def test_extract_key_is_stable_for_identical_inputs():
    assert _key() == _key()
    assert len(_key()) == 64


@pytest.mark.parametrize(("label", "changed"), [
    ("a page image hash", {"hashes": ("a" * 64, "b" * 64, "z" * 64)}),
    ("the page order", {"hashes": ("b" * 64, "a" * 64, "c" * 64)}),
    ("the page count", {"hashes": HASHES[:2]}),
    ("the model id", {"model": "gemini-3.8-pro-001"}),
    ("the prompt version", {"prompt": "s2-v2"}),
    ("the dpi", {"dpi": DPI_INDEX}),
    ("the schema", {"schema": "0" * 64}),
])
def test_extract_key_changes_with_every_input(label, changed):
    assert _key(**changed) != _key(), label


def test_extract_key_needs_at_least_one_page():
    with pytest.raises(ValueError):
        _key(())


def test_the_schema_hash_follows_the_schema():
    """`impl` put a hand-maintained integer in the key, which is only correct while somebody
    remembers to bump it. Add a field and every window re-bills, which is the honest answer."""
    assert S2_SCHEMA_HASH == schema_hash(WindowOut)
    assert schema_hash({"type": "object"}) != S2_SCHEMA_HASH


def test_the_tier_is_not_an_extract_key_input():
    """§6.3 — batch and standard produce the same output, so the discount must not re-bill."""
    import inspect

    assert "tier" not in inspect.signature(w.extract_key).parameters
