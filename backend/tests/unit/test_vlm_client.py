"""L0 — the live backend's own guarantees, with no network (Spec §6.3, §4.3, F11, register B6).

The Gemini client is ported from `impl/app/segment.py` and the four things that changed are the
four things asserted here:

* **the pin is re-verified at the point of spend.** `vsir doctor` refuses a floating model id at
  boot (F11), and this backend refuses it again when the call is about to be made — because boot
  runs once per process and a long-lived worker can be handed a configuration that never went
  through one (register B6);
* **the prompt is part of the release, and its digest says so.** `prompt_version` is a *label*;
  edit `s2.md` and leave the label alone and every frozen and cached response under it was produced
  by instructions that no longer exist. The digest makes that edit fail by name;
* **a token bucket bounds the burst.** `impl` rate-limits nothing, so a full-corpus run's opening
  move is to fire every window at once and then serve out its own 429s at exponentially increasing
  delay — a wasted round trip per window in the stage that is 99 % of spend;
* **a truncation is never kept.** It bisects and re-bills (F13), and the retry ladder is for
  transient failures only: retrying a truncation is free money for the provider.

Every test injects the transport or the clock, so nothing here opens a socket and nothing needs a
credential. `test_replay.py` proves the same about the whole ingest run.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from vsir.ingest.extract import WindowOut
from vsir.ingest.window import DocumentFacts
from vsir.vlm import (EXTRACT, MAX_ATTEMPTS, PROMPT_DIGESTS, PROMPT_DIR, PROMPT_STAGES,
                      GeminiBackend, PromptUnavailable, Request, TokenBucket, VlmCallFailed,
                      VlmTierUnsupported, VlmTruncated, VlmUnavailable, hint, prompt)
from vsir.vlm import client

MODEL = "gemini-3.8-flash"
PROMPT = "s2-v1"
BODY = '{"pages": []}'


class _Reason:
    """What the SDK puts on a candidate: an enum-like object with a `.name`."""

    def __init__(self, name: str) -> None:
        self.name = name


class _Usage:
    def __init__(self) -> None:
        self.prompt_token_count = 1200
        self.candidates_token_count = 340
        self.total_token_count = 1540


class _Response:
    def __init__(self, *, text: str = BODY, finish: str = "STOP") -> None:
        self.text = text
        self.candidates = [type("C", (), {"finish_reason": _Reason(finish)})()]
        self.usage_metadata = _Usage()


def _backend(transport, *, model: str = MODEL, tier: str = "standard", rpm: int = 600,
             prompt_dir=None) -> GeminiBackend:
    return GeminiBackend(model=model, prompt_version=PROMPT, tier=tier,
                         bucket=TokenBucket(rpm, clock=lambda: 0.0, sleep=lambda _: None),
                         key="not-a-real-credential", transport=transport, sleep=lambda _: None,
                         prompt_dir=prompt_dir)


def _request(**overrides) -> Request:
    fields = {"namespace": EXTRACT, "key": "a" * 64, "stage": "s2", "schema": WindowOut,
              "images": (b"\x89PNG fake",), "hint": hint(start=1, end=4, page_count=42),
              "label": "S2 1-4", **overrides}
    return Request(**fields)


# ── the pin, re-verified where the money is spent (F11, register B6) ───────────────────────────

def test_a_floating_model_id_is_refused_at_the_point_of_spend():
    """When a provider repoints a floating alias the key string does not change but the model
    behind it does, so the cache serves extractions produced by a *different* model under a name
    that claims otherwise — precisely the failure the key exists to prevent."""
    calls: list[dict] = []
    backend = _backend(lambda **call: calls.append(call) or _Response(),
                       model="gemini-pro-latest")

    with pytest.raises(VlmUnavailable) as refusal:
        backend.generate(_request())

    assert refusal.value.details["suffix"] == "-latest"
    assert calls == [], "the call was made before the pin was checked"


def test_the_pin_is_checked_even_when_the_boot_check_never_ran():
    """`impl/config.yaml` sets `gemini-pro-latest` for both extract and read and warns about it in
    a comment. Two checks for one rule, because a worker's configuration may bypass boot."""
    with pytest.raises(VlmUnavailable):
        _backend(lambda **call: _Response(), model="gemini-flash-latest").generate(_request())


# ── the prompt is part of the release ──────────────────────────────────────────────────────────

def test_the_released_prompts_hash_to_their_published_digests():
    """The guard the cache key cannot provide on its own: `prompt_version` describes the text only
    while the two move together."""
    for stage in PROMPT_STAGES:
        found = prompt(stage, PROMPT)
        assert found.digest == PROMPT_DIGESTS[PROMPT][stage]
        assert found.text == (PROMPT_DIR / f"{stage}.md").read_text()


def test_editing_a_prompt_without_releasing_a_version_fails_by_name(tmp_path):
    """AC-adjacent, and the plan's named risk: a fixture going stale relative to a prompt edit.
    The only way through is a new `VSIR_PROMPT_VERSION`, which re-keys every response by design."""
    (tmp_path / "s2.md").write_text((PROMPT_DIR / "s2.md").read_text() + "\nAlso guess.\n")

    with pytest.raises(PromptUnavailable) as refusal:
        prompt("s2", PROMPT, directory=tmp_path)

    assert refusal.value.code == "prompt_unavailable"
    assert refusal.value.details["prompt_version"] == PROMPT
    assert "F11" in str(refusal.value)


def test_a_prompt_version_with_no_released_text_is_refused():
    with pytest.raises(PromptUnavailable) as refusal:
        prompt("s2", "v2")

    assert refusal.value.details["released"] == sorted(PROMPT_DIGESTS)


def test_a_stage_this_release_does_not_ship_never_borrows_another_stages_prompt():
    """A stage with no released text is a named refusal, never a fallback to another stage's.

    Serving S2's instructions to a call that asked a question would answer a different question
    entirely and report success. `read` shipped at U020 and is a released stage now (below); the
    property is about any stage that is **not**, which is what a future one arrives as.
    """
    with pytest.raises(PromptUnavailable) as refusal:
        prompt("s3", PROMPT)

    assert refusal.value.details["stages"] == list(PROMPT_STAGES)


def test_every_stage_this_release_ships_has_released_text_behind_it():
    """The three of §6.1 steps 04 and 06 and §7.2.6 — and the digest each was published with.

    :func:`prompt` refuses a file that does not hash to its published digest, so this is the one
    assertion that keeps `PROMPT_DIGESTS` honest for **every** stage at once: add a stage without
    releasing its text, or edit a released file, and it fails here rather than at the first live
    call (F11).
    """
    assert set(PROMPT_STAGES) == {"s1", "s2", "read"}
    for stage in PROMPT_STAGES:
        assert prompt(stage, PROMPT).text.strip()


def test_the_read_prompt_binds_the_rules_sufficient_exists_for():
    """§7.2.6 — the two instructions a `read` response is unusable without.

    `sufficient` has to separate *"the answer is no"* from *"wrong pages"*, and the model has to
    be told not to answer from what it knows: those are the two ways a paid read produces a
    confident wrong answer, and both are binding text rather than a hope about the schema.
    """
    flat = " ".join(prompt("read", PROMPT).text.split())

    assert "Only these pages" in flat
    assert "`sufficient` is the answer to a different question than `extract` is" in flat
    assert "verbatim" in flat.lower()
    assert "Nothing about where else to look" in flat


def test_the_s2_prompt_carries_the_binding_rules_of_the_spec():
    """§5.2 — the summary rule is binding text, and "presence, never extent" is what makes
    stitching able to survive a window fold. Both are asserted, because a prompt edit that dropped
    them would still hash to a new digest and be released without anyone noticing what went."""
    text = prompt("s2", PROMPT).text
    # The file is wrapped at 100 columns, so the rule is asserted against the collapsed text:
    # what is binding is the instruction, not where the paragraph happens to break.
    flat = " ".join(text.split())

    assert "2–3 sentences on what is SPECIFIC to this page" in flat
    assert "Do not describe the document generally" in flat
    assert "Presence, never extent" in flat
    assert "verbatim" in flat.lower()
    for kind in ("prose", "table", "schematic", "exploded", "cover", "toc", "index", "blank"):
        assert f"`{kind}`" in flat


def test_the_s1_prompt_asks_for_a_zero_rather_than_a_guessed_page_index():
    """The contents list decides how the rest of the document is read: an entry with a guessed
    index becomes a boundary in the wrong place (§6.2, register B2)."""
    text = prompt("s1", PROMPT).text

    assert "**A 0 is a correct and useful answer.**" in text
    assert "verbatim" in text.lower()


# ── the token bucket (net new) ─────────────────────────────────────────────────────────────────

def test_the_bucket_lets_a_full_burst_through_and_then_paces():
    """Bounds the burst, never the total: a small document is not paced into taking a minute."""
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    bucket = TokenBucket(60, clock=lambda: now[0], sleep=sleep)

    assert [bucket.take() for _ in range(60)] == [0.0] * 60
    assert bucket.take() == pytest.approx(1.0)
    assert slept == [pytest.approx(1.0)]


def test_the_bucket_refills_continuously():
    now = [0.0]
    bucket = TokenBucket(60, clock=lambda: now[0], sleep=lambda _: None)
    for _ in range(60):
        bucket.take()

    now[0] += 30.0

    assert bucket.available == pytest.approx(30.0)


@pytest.mark.parametrize("rate", [0, -1])
def test_a_rate_limit_below_one_call_a_minute_is_refused(rate):
    with pytest.raises(ValueError):
        TokenBucket(rate)


def test_a_call_that_cannot_fit_in_the_bucket_is_refused_rather_than_deadlocking():
    bucket = TokenBucket(2, clock=lambda: 0.0, sleep=lambda _: None)

    with pytest.raises(ValueError):
        bucket.take(3)


# ── the retry ladder, ported from `impl` ───────────────────────────────────────────────────────

def test_a_transient_failure_is_retried_and_then_succeeds():
    attempts: list[int] = []

    def transport(**call):
        attempts.append(len(attempts) + 1)
        if len(attempts) < 3:
            raise RuntimeError("503 Service Unavailable")
        return _Response()

    entry = _backend(transport).generate(_request())

    assert len(attempts) == 3
    assert entry.body == BODY
    assert entry.origin == "model"
    assert entry.usage == {"prompt_tokens": 1200, "output_tokens": 340, "total_tokens": 1540}


def test_a_bad_request_is_not_worth_four_attempts():
    """Ported behaviour: only the substrings that mark a transient failure are retried. Retrying a
    400 spends four round trips to be told the same thing four times."""
    attempts: list[int] = []

    def transport(**call):
        attempts.append(1)
        raise ValueError("400 INVALID_ARGUMENT: schema too deep")

    with pytest.raises(VlmCallFailed) as refusal:
        _backend(transport).generate(_request())

    assert len(attempts) == 1
    assert refusal.value.details["attempts"] == 1
    assert refusal.value.details["cache_key"] == "a" * 64


def test_the_retry_budget_is_finite_and_the_failure_names_the_key():
    attempts: list[int] = []

    def transport(**call):
        attempts.append(1)
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    with pytest.raises(VlmCallFailed) as refusal:
        _backend(transport).generate(_request())

    assert len(attempts) == MAX_ATTEMPTS
    assert refusal.value.details["attempts"] == MAX_ATTEMPTS
    assert refusal.value.code == "vlm_call_failed"


# ── a bad answer is never kept (§6.2, F13) ─────────────────────────────────────────────────────

@pytest.mark.parametrize("finish", ["MAX_TOKENS", "TRUNCATED"])
def test_a_response_that_hit_the_output_ceiling_is_a_bisection_trigger(finish):
    """Never a keep. A truncated 30-page window that is quietly kept loses 30 pages of a manual
    and reports success — and the repair is to halve the window, not to retry the same call."""
    attempts: list[int] = []

    def transport(**call):
        attempts.append(1)
        return _Response(finish=finish)

    with pytest.raises(VlmTruncated) as refusal:
        _backend(transport).generate(_request())

    assert len(attempts) == 1, "a truncation must not be retried: the same call truncates again"
    assert refusal.value.details["finish_reason"] == finish


def test_a_response_with_no_body_is_a_failure_not_an_empty_extraction():
    """A window that came back with nothing must fail, not publish zero pages."""
    with pytest.raises(VlmCallFailed):
        _backend(lambda **call: _Response(text="")).generate(_request())


# ── the call itself ────────────────────────────────────────────────────────────────────────────

def test_the_call_is_structured_output_at_temperature_zero_in_one_content():
    """Determinism is what makes `extract_key` honest: at a temperature above zero the same pages,
    model and prompt return different structure on a re-run the key calls a hit."""
    seen: dict = {}
    _backend(lambda **call: seen.update(call) or _Response()).generate(_request())

    assert seen["model"] == MODEL
    assert len(seen["contents"]) == 1, "a bare list returns one aggregated response (D4's lesson)"
    assert seen["config"].temperature == 0.0
    assert seen["config"].response_mime_type == "application/json"
    assert seen["config"].system_instruction == prompt("s2", PROMPT).text
    # The model class described the shape and `response_schema` has no field for half of what
    # Pydantic renders, so what goes on the wire is the translation of it, not the class. This
    # assertion used to read `is WindowOut`, which is what the first live call returned
    # `400 INVALID_ARGUMENT: Unknown name "additional_properties"` for.
    assert seen["config"].response_schema == client.response_schema(WindowOut)


def test_the_schema_that_is_sent_carries_nothing_the_api_has_no_field_for():
    """The property, not the shape: no unsupported keyword survives anywhere in the tree.

    Recursive because the failure was nested — the 400 named both the root and
    `properties[6].value.items`, which is `DocumentFacts.toc`'s item model.
    """
    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                assert key not in client.UNSUPPORTED_SCHEMA_KEYS, f"{key} would be a 400"
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for model in (WindowOut, DocumentFacts):
        walk(client.response_schema(model))


def test_a_nested_model_is_inlined_rather_than_referenced():
    """`response_schema` is sent as a tree with no document to resolve a `$ref` against."""
    schema = client.response_schema(DocumentFacts)

    assert "$defs" not in schema
    assert "$ref" not in repr(schema)
    entries = schema["properties"]["toc"]["items"]
    assert entries["type"] == "object" and "page_no" in entries["properties"]


def test_the_strict_class_still_parses_the_response():
    """Only the *description* is relaxed. `extra="forbid"` keeps refusing an unexpected field on
    the way back in, which is the half worth keeping: a surprise key in a paid response is
    something to refuse, not to drop."""
    with pytest.raises(ValidationError):
        DocumentFacts.model_validate({"title": "x", "unexpected": 1})


def test_the_rasters_go_last_and_the_hint_is_our_own_arithmetic():
    """§6.4 — the page range is ours, from our own windowing, and is never a fact the model is
    asked to report back. The one line of context says where the excerpt sits, nothing more."""
    seen: dict = {}
    _backend(lambda **call: seen.update(call) or _Response()).generate(_request())
    parts = seen["contents"][0].parts

    assert len(parts) == 2
    assert parts[-1].text == "This excerpt is pages 1-4 of 42."
    assert hint(start=15, end=28, page_count=42) == "This excerpt is pages 15-28 of 42."


def test_a_call_with_neither_a_raster_nor_a_line_of_text_is_a_programming_error():
    with pytest.raises(ValueError):
        _backend(lambda **call: _Response()).generate(_request(images=(), hint=""))


def test_the_batch_tier_is_named_rather_than_silently_downgraded():
    """§6.3 — quietly serving a batch request from the standard endpoint bills a full-corpus run
    at twice the rate the cost basis assumes and reports success. The tier is not a key input, so
    a run started on standard can be finished on batch for free once that path lands."""
    calls: list[dict] = []

    with pytest.raises(VlmTierUnsupported) as refusal:
        _backend(lambda **call: calls.append(call) or _Response(),
                 tier="batch").generate(_request())

    assert refusal.value.code == "vlm_tier_unsupported"
    assert calls == []


def test_the_credential_never_appears_in_a_repr():
    """§15.1 — no traceback, log line or error message may carry it."""
    backend = _backend(lambda **call: _Response())

    assert "not-a-real-credential" not in repr(backend)
    assert backend.key == "not-a-real-credential"
