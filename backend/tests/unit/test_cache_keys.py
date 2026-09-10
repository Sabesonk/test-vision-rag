"""L0 — the four content-addressable cache keys of Spec §6.3 (F11's key half, register B2).

A cache key is a receipt, and it earns its keep only if **every input that can change the model's
answer is on it and nothing else is**. The two ways to get that wrong fail in opposite directions
and only one of them is noisy:

* an input **missing** from the key serves output produced by a different model or a different
  prompt, silently, and reports a cache hit (F11) — the frozen fixture would go on answering after
  the instructions that produced it stopped existing;
* an input **on** the key that cannot change the answer re-bills a full-corpus run for nothing.
  `VSIR_VLM_TIER` is the live example: batch and standard produce the same output, so keying on it
  would charge a corpus for choosing the 50 % discount (§6.3).

So the shape of this file is one test per input asserting the key *moves*, plus tests asserting it
does not move for anything else. `read_key` gets its own section because the question is what makes
it different from `extract_key`, and that difference is the whole mechanism F19 rests on.
"""
from __future__ import annotations

import inspect

import pytest

from vsir.config import COMPOSITION_VERSION, DPI_ANSWER, DPI_INDEX
from vsir.ingest.extract import S2_SCHEMA_HASH, WindowOut, schema_hash
from vsir.vlm import EXTRACT, FACTS, NAMESPACES, READ, FixtureMiss, FixtureStore
from vsir.vlm import cache, embed_key, extract_key, facts_key, read_key, write

MODEL = "gemini-3.8-flash"
OTHER_MODEL = "gemini-3.8-pro-001"
PROMPT = "s2-v1"
EMBED_MODEL = "gemini-embedding-2"
HASHES = ("a" * 64, "b" * 64, "c" * 64)
QUESTION = "Which relay does the stop category depend on?"


def _extract(hashes=HASHES, *, model=MODEL, prompt=PROMPT, dpi=DPI_ANSWER,
             schema=S2_SCHEMA_HASH) -> str:
    return extract_key(hashes, vlm_model=model, prompt_version=prompt, dpi=dpi,
                       schema_hash=schema)


def _read(hashes=HASHES, *, model=MODEL, prompt=PROMPT, dpi=DPI_ANSWER, schema=S2_SCHEMA_HASH,
          question=QUESTION) -> str:
    return read_key(hashes, vlm_model=model, prompt_version=prompt, dpi=dpi, schema_hash=schema,
                    question=question)


# ── facts_key (register B2) ─────────────────────────────────────────────────────────────────────

def test_facts_key_is_stable_across_runs():
    """AC: the same document, the same configuration, the same key — so S1 is billed once."""
    first = facts_key("abc", vlm_model=MODEL, prompt_version=PROMPT)

    assert first == facts_key("abc", vlm_model=MODEL, prompt_version=PROMPT)
    assert len(first) == 64


@pytest.mark.parametrize(("field", "value"), [
    ("content_hash", "def"), ("vlm_model", OTHER_MODEL), ("prompt_version", "s2-v2"),
])
def test_facts_key_changes_with_every_input(field, value):
    """Register B2 — caching S1 is what makes the ladder reproducible, and a key that missed one
    of these would make it reproducibly *wrong*: S1's contents list is the sole input to the
    branch that decides how much S2 costs."""
    baseline = facts_key("abc", vlm_model=MODEL, prompt_version=PROMPT)
    inputs = {"content_hash": "abc", "vlm_model": MODEL, "prompt_version": PROMPT}
    inputs[field] = value

    assert facts_key(inputs.pop("content_hash"), **inputs) != baseline


def test_facts_key_needs_the_content_hash():
    """A key over an empty document hash would answer for every file at once."""
    with pytest.raises(ValueError):
        facts_key("", vlm_model=MODEL, prompt_version=PROMPT)


# ── extract_key (F11's key half) ────────────────────────────────────────────────────────────────

def test_extract_key_is_stable_for_identical_inputs():
    """AC: identical otherwise — which is what makes a re-run over identical pages cost $0."""
    assert _extract() == _extract()
    assert len(_extract()) == 64


@pytest.mark.parametrize(("label", "changed"), [
    ("a page image hash", {"hashes": ("a" * 64, "b" * 64, "z" * 64)}),
    ("the page order", {"hashes": ("b" * 64, "a" * 64, "c" * 64)}),
    ("the page count", {"hashes": HASHES[:2]}),
    ("the model id", {"model": OTHER_MODEL}),
    ("the prompt version", {"prompt": "s2-v2"}),
    ("the dpi", {"dpi": DPI_INDEX}),
    ("the schema", {"schema": "0" * 64}),
])
def test_extract_key_changes_with_every_input(label, changed):
    assert _extract(**changed) != _extract(), label


def test_extract_key_changes_with_prompt_version():
    """F11 (key half), named as the plan names it: a cache cannot serve output from a different
    prompt. This is the one the frozen fixtures depend on — bump `VSIR_PROMPT_VERSION` and every
    frozen response is a typed `fixture_miss` rather than a stale hit under new instructions."""
    assert _extract(prompt="s2-v2") != _extract()
    assert _extract(model=OTHER_MODEL) != _extract()


def test_extract_key_needs_at_least_one_page():
    with pytest.raises(ValueError):
        _extract(())


def test_the_tier_is_not_an_extract_key_input():
    """§6.3 — batch and standard produce the same output, so the discount must not re-bill.

    Asserted on the signature rather than on two values, because the failure this guards is
    somebody *adding* the parameter: a key that cannot be given the tier cannot be keyed on it.
    """
    for key in (extract_key, read_key, facts_key, embed_key):
        assert "tier" not in inspect.signature(key).parameters


def test_the_schema_hash_follows_the_schema():
    """`impl` put a hand-maintained integer in the key, which is only correct while somebody
    remembers to bump it. Add a field and every window re-bills, which is the honest answer —
    the model was asked a different question and its old answer lacks the new field."""
    assert S2_SCHEMA_HASH == schema_hash(WindowOut)
    assert schema_hash({"type": "object"}) != S2_SCHEMA_HASH


# ── read_key (F19's mechanism) ──────────────────────────────────────────────────────────────────

def test_read_key_for_the_same_pages_but_a_different_question_differs():
    """AC, and the mechanism F19 relies on (F19 itself is proved at M5): a new question is a cache
    miss, so `read` cannot answer question B out of question A's paid response."""
    assert _read(question="Which contactor is named?") != _read()
    assert _read() == _read()


def test_read_key_carries_every_extract_key_input_too():
    """§6.3 — `read_key` is *`extract_key` inputs ‖ question*, so a `read` cached under one model,
    prompt, dpi or page set can never answer for another."""
    baseline = _read()

    assert _read(hashes=HASHES[:2]) != baseline
    assert _read(model=OTHER_MODEL) != baseline
    assert _read(prompt="s2-v2") != baseline
    assert _read(dpi=DPI_INDEX) != baseline
    assert _read(schema="0" * 64) != baseline


def test_a_read_key_is_never_an_extract_key():
    """Two calls that ask different questions must not be able to collide even if the inputs of
    one are a prefix of the other's — which is why the namespaces are separate as well (§6.3)."""
    assert _read() != _extract()


@pytest.mark.parametrize("question", ["", "   ", "\n"])
def test_read_key_needs_a_question(question):
    """`read` without a question is `fetch` (§7.2.5) — and it is free, so it must not be billed."""
    with pytest.raises(ValueError):
        _read(question=question)


# ── embed_key (register B5) ─────────────────────────────────────────────────────────────────────

def test_embed_key_changes_with_every_input():
    baseline = embed_key("page 7 text", embed_model=EMBED_MODEL)

    assert baseline == embed_key("page 7 text", embed_model=EMBED_MODEL)
    assert embed_key("page 8 text", embed_model=EMBED_MODEL) != baseline
    assert embed_key("page 7 text", embed_model="gemini-embedding-3") != baseline
    assert embed_key("page 7 text", embed_model=EMBED_MODEL,
                     composition_version="d4-fused-v2") != baseline


def test_embed_key_defaults_to_the_released_composition_version():
    """§6.6 — the composition version is part of the fingerprint, so it is not a caller's choice
    to make casually: the default is the release's."""
    assert embed_key("x", embed_model=EMBED_MODEL) == embed_key(
        "x", embed_model=EMBED_MODEL, composition_version=COMPOSITION_VERSION)


def test_embed_key_has_no_dim_input():
    """§6.6/§5.5 — MRL truncation makes a change of `dim` a change of *collection*, so two dims
    never share a namespace to be confused inside. The fingerprint guards that, not this key."""
    assert "dim" not in inspect.signature(embed_key).parameters


def test_embed_key_needs_the_composed_string():
    with pytest.raises(ValueError):
        embed_key("", embed_model=EMBED_MODEL)


# ── the inputs cannot be made to collide ────────────────────────────────────────────────────────

def test_two_different_input_splits_cannot_share_a_key():
    """The inputs are length-prefixed before they are joined, and that is not decoration.

    With a plain separator, `("a|b", "c")` and `("a", "b|c")` concatenate to the same string and
    therefore share a key — and one of those inputs, `prompt_version`, is operator-supplied. A key
    two configurations can collide on is worse than no key: the collision serves one
    configuration's output as the other's and calls it a hit (F11).
    """
    assert facts_key("abc", vlm_model="m|x", prompt_version="v") != facts_key(
        "abc", vlm_model="m", prompt_version="x|v")
    assert embed_key("a|b", embed_model="m") != embed_key("a", embed_model="b|m")


def test_a_key_is_a_hex_sha256_and_nothing_else():
    """It becomes a filename in the fixture and a payload field in the run record: no separators,
    no case, no operator-supplied text can reach either."""
    for key in (facts_key("abc", vlm_model=MODEL, prompt_version=PROMPT), _extract(), _read(),
                embed_key("x", embed_model=EMBED_MODEL)):
        assert len(key) == 64
        assert set(key) <= set("0123456789abcdef")


# ── the store the keys name (D10) ───────────────────────────────────────────────────────────────

def test_the_namespaces_are_the_three_calls_the_pipeline_makes():
    """One namespace per *call*, not per model, so two calls cannot collide even if their keys
    somehow did. `embed_key` has no namespace: no embedding response is frozen (§6.3)."""
    assert NAMESPACES == (FACTS, EXTRACT, READ)


def test_a_frozen_response_is_addressed_by_its_key_alone(tmp_path):
    """`impl` put the revision in the path, so correcting a metadata field moved the whole store
    and re-billed ~99 % of extraction spend. The key already carries the content hash."""
    key = _extract()
    write(tmp_path, EXTRACT, key, '{"pages": []}')
    store = FixtureStore(tmp_path)

    assert store.path(EXTRACT, key) == tmp_path / EXTRACT / f"{key}.json"
    assert store.has(EXTRACT, key)
    assert store.get(EXTRACT, key).body == '{"pages": []}'


def test_a_key_in_the_wrong_namespace_is_a_miss_not_a_hit(tmp_path):
    key = _extract()
    write(tmp_path, EXTRACT, key, '{"pages": []}')

    with pytest.raises(FixtureMiss):
        FixtureStore(tmp_path).get(READ, key)


def test_a_namespace_the_spec_does_not_name_is_refused(tmp_path):
    with pytest.raises(ValueError):
        FixtureStore(tmp_path).path("embeddings", _extract())


def test_the_store_a_running_process_holds_cannot_write(tmp_path):
    """Replay must never be able to fill its own cache, or one accidental live call would be
    frozen into the repository as though it had been reviewed. `write` is the generator's door."""
    assert not hasattr(FixtureStore(tmp_path), "write")
    assert not hasattr(FixtureStore(tmp_path), "put")
    assert inspect.isfunction(cache.write)
