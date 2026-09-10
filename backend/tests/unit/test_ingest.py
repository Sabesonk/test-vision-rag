"""L1 — `vsir ingest`, steps 01-05 end to end over the generated corpus (Spec §4.4, §6.1).

The demo command is the unit's deliverable, so it is tested like one: it runs, it stops where it
is told, and every refusal it can make is named and non-zero. The refusals matter more than the
happy path. A replay miss that fell back to a live call would spend money in CI; a replay miss that
fabricated a response would make every downstream assertion a statement about fiction (D10).

Run with the rest of the unit's slice:
    bash scripts/test-unit.sh -k "manifest or probe or render or window or ingest"
"""
from __future__ import annotations

import json

import pytest

from vsir import cli
from vsir.config import DPI_ANSWER
from vsir.eval import synthetic_pdf as generator
from vsir.ingest import probe

BASE_ENV = {
    "VSIR_PORT": "8000",
    # Nothing serves this port. L0/L1 are steps 01-08 plus pure functions, so a suite that
    # reached a store would be reaching a *developer's* store — and on this machine there is a
    # live one on 6333. The two store-backed steps are asserted here by their refusal, and
    # exercised against a real Qdrant by tests/api/test_index_upsert.py.
    "VSIR_QDRANT_URL": "http://127.0.0.1:6399",
    "VSIR_COLLECTION": "vsir_pages",
    "VSIR_VLM": "stub",
    "VSIR_VLM_MODEL": "gemini-3.8-flash-001",
    "VSIR_EMBED_MODEL": "gemini-embedding-2",
    "VSIR_PROMPT_VERSION": "s2-v1",
    "VSIR_API_TOKENS": "test-only-not-a-credential",
    "VSIR_READ_QUOTA": "50",
    "VSIR_ALLOW_PAID": "0",
    "VSIR_LOG_LEVEL": "INFO",
    "VSIR_RELEASE_ID": "test-0",
}


@pytest.fixture
def env(monkeypatch, synthetic_fixture):
    for name, value in BASE_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("VSIR_FIXTURE", str(synthetic_fixture))
    return monkeypatch


def _run(pdf, *args) -> int:
    return cli.main(["ingest", str(pdf), *args])


def test_ingest_until_window_runs_green(env, capsys, synthetic_pdf, expected):
    """The unit's Demo Command. Every assertion in it reads from `expected.json` (C10)."""
    code = _run(synthetic_pdf, "--vlm", "stub", "--until", "window")
    out = capsys.readouterr().out

    assert code == cli.EXIT_OK
    assert "ALL ASSERTIONS PASSED" in out
    assert "FAIL" not in out
    assert "0 bytes written to the filesystem" in out
    for start, end in expected["windows"]:
        assert f"{start}-{end}" in out


def test_ingest_until_extract_runs_green(env, capsys, synthetic_pdf, expected):
    """U008's Demo Command: steps 01-06, with S1 and S2 both replayed from the fixture (D10).

    The verbatim response is what the reviewer is shown, so the run prints one page form per
    window — and `page_index` being window-local is visible in it, which is the fact §6.4's offset
    proof exists to defend.
    """
    code = _run(synthetic_pdf, "--vlm", "stub", "--until", "extract")
    out = capsys.readouterr().out

    assert code == cli.EXIT_OK
    assert "ALL ASSERTIONS PASSED" in out
    assert "FAIL" not in out
    assert f"{expected['extraction']['page_forms']} page forms" in out
    assert "the model returned 0 characters of page text" in out


def test_ingest_until_stitch_runs_green(env, capsys, synthetic_pdf, expected):
    """U009's Demo Command: steps 01-08, and every assertion reads from `expected.json` (C10).

    The reviewable claims are the ones the unit exists for — the offset trap firing, the
    reattributed code naming where it came from, and one `section_id` on both sides of a fold.
    """
    code = _run(synthetic_pdf, "--vlm", "stub", "--until", "stitch")
    out = capsys.readouterr().out

    assert code == cli.EXIT_OK
    assert "ALL ASSERTIONS PASSED" in out
    assert "FAIL" not in out
    trap = expected["extraction"]["reattribution"]
    assert f"reattributed {trap['code']}: page {trap['page']} -> {trap['from_page']}" in out
    assert f"ungrounded {expected['extraction']['ungrounded']['code']}" in out
    for title in expected["straddling_sections"]:
        assert f'"{title}" crosses the window fold at' in out
    assert "grounded_rate median 1.0" in out


def test_ingest_until_derive_stops_before_the_section_ids(env, capsys, synthetic_pdf):
    """`--until` is a real stop, not a filter on what gets printed."""
    assert _run(synthetic_pdf, "--vlm", "stub", "--until", "derive") == cli.EXIT_OK
    out = capsys.readouterr().out

    assert "07 derivation" in out
    assert "08 stitching" not in out


def test_ingest_reports_each_step_on_the_event_stream(env, capsys, synthetic_pdf):
    """§15 Factor XI — one JSON object per line, every one carrying the run id."""
    _run(synthetic_pdf, "--until", "stitch")
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()
              if line.startswith("{")]

    steps = [event["step"] for event in events if event["event"] == "ingest_step"]
    assert steps == ["manifest", "probe", "render", "facts", "window", "extract", "derive",
                     "stitch"]
    assert {event["release_id"] for event in events} == {"test-0"}
    assert all(event["run_id"] for event in events)


@pytest.mark.parametrize("until", [step for step in cli.INGEST_STEPS
                                   if step not in cli.STORE_BACKED_STEPS])
def test_ingest_stops_where_it_is_told(env, capsys, synthetic_pdf, until):
    code = _run(synthetic_pdf, "--until", until)
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()
              if line.startswith("{")]
    steps = [event["step"] for event in events if event["event"] == "ingest_step"]

    assert code == cli.EXIT_OK
    assert steps == list(cli.INGEST_STEPS[:cli.INGEST_STEPS.index(until) + 1])


@pytest.mark.parametrize("until", cli.STORE_BACKED_STEPS)
def test_the_store_backed_steps_refuse_by_name_with_no_store(env, capsys, synthetic_pdf, until):
    """§11.3 — each degradation row is a refusal, not a best-effort fallback.

    Step 09 reads the embedding cache off the index, step 10 writes to it and step 11 flips
    `is_current` on it, so none of the three can run without Qdrant. Running anyway would be worse
    than refusing in both directions: it would re-bill every vector the index already holds, and
    then report a published document that was never written.

    **The refusal arrives at step 01, and that is U011's doing.** A store-backed run claims its
    control record before the first window (D9), because a run that dies mid-flight has to be a
    run that exists — so an unreachable store is now named before a single model call rather than
    after the whole of extraction. The typed code is the same one either way (§11.3), and nothing
    downstream of the refusal runs.
    """
    code = _run(synthetic_pdf, "--vlm", "stub", "--until", until)
    out = capsys.readouterr().out

    assert code == cli.EXIT_REFUSED
    assert "REFUSED  qdrant_unavailable" in out
    assert "01 manifest" in out
    for step in ("06 S2 extraction", "09 embedding", "10 indexing", "11 gates and publish"):
        assert step not in out


def test_a_replay_miss_is_typed_and_never_a_live_call(env, capsys, synthetic_pdf):
    """D10 — a key that is not in the fixture is `fixture_miss`, never a call and never a guess.

    Bumping the prompt version is the realistic way to produce one: it is an input to `facts_key`,
    so the frozen S1 response no longer answers the question being asked.
    """
    env.setenv("VSIR_PROMPT_VERSION", "s2-v2")

    code = _run(synthetic_pdf, "--until", "facts")
    out = capsys.readouterr().out

    assert code == cli.EXIT_REFUSED
    assert "REFUSED  fixture_miss" in out
    assert "ALL ASSERTIONS PASSED" not in out


def test_a_backend_with_no_credential_refuses_by_name(env, capsys, synthetic_pdf):
    """§15 Factor III — the credential arrives at runtime, never from the image, so a live backend
    with nothing in `VSIR_VLM_KEY` cannot run. It says so and exits non-zero: it never proceeds
    without facts, and it never falls back to the fixture, which would answer the wrong question
    (the frozen response is not this backend's output)."""
    code = _run(synthetic_pdf, "--vlm", "gemini", "--until", "facts")
    out = capsys.readouterr().out

    assert code == cli.EXIT_REFUSED
    assert "vlm_backend_unavailable" in out
    assert "VSIR_VLM_KEY" in out


def test_steps_before_the_vlm_still_run_without_a_fixture(env, capsys, synthetic_pdf):
    """Steps 01-03 cost nothing and need no model, so they must not be hostage to one."""
    env.setenv("VSIR_FIXTURE", "")

    assert _run(synthetic_pdf, "--until", "render") == cli.EXIT_OK
    assert "REFUSED" not in capsys.readouterr().out


def test_a_missing_document_refuses(env, capsys, tmp_path):
    code = _run(tmp_path / "absent.pdf", "--until", "manifest")

    assert code == cli.EXIT_REFUSED
    assert "source_missing" in capsys.readouterr().out


def test_the_operators_declarations_reach_the_manifest(env, capsys, synthetic_pdf):
    _run(synthetic_pdf, "--until", "manifest", "--doc-id", "TC1E-SF", "--revision", "1.3",
         "--doc-type", "safety_function_list", "--subjects", "C24,C25", "--tags", "pilot")
    out = capsys.readouterr().out

    assert "TC1E-SF" in out and "1.3" in out and "safety_function_list" in out
    assert "C24, C25" in out


# ── the corpus itself ───────────────────────────────────────────────────────────────────────────

def test_the_checked_in_corpus_is_what_the_generator_produces(synthetic_pdf):
    """Reproducible, so the fixture's identity — and every key anchored to it — is stable.

    Without `no_new_id`, PyMuPDF mints a fresh `/ID` on every save: the file hash changes, and with
    it `facts_key` and the name of the frozen S1 response beside it.
    """
    with generator.build_document() as doc:
        rebuilt = doc.tobytes(deflate=True, garbage=4, no_new_id=True)

    assert rebuilt == synthetic_pdf.read_bytes()


def test_the_frozen_s1_response_is_keyed_to_the_checked_in_pdf(synthetic_pdf, synthetic_fixture):
    """§6.3 — the fixture is content-addressable, so it cannot silently answer for another file."""
    from vsir.ingest import window
    from vsir.vlm import FACTS, FixtureStore, facts_key

    def key_now() -> str:
        return facts_key(probe.content_hash(synthetic_pdf),
                         vlm_model=BASE_ENV["VSIR_VLM_MODEL"],
                         prompt_version=BASE_ENV["VSIR_PROMPT_VERSION"])

    key = key_now()
    assert key == key_now(), "two runs over the same PDF must re-bill S1 zero times"
    entry = FixtureStore(synthetic_fixture).get(FACTS, key)

    facts = window.DocumentFacts.model_validate_json(entry.body)
    assert [entry.page_no for entry in facts.toc] == [start for start, _ in generator.CHAPTERS]


def test_the_frozen_s2_responses_are_keyed_to_the_windows_of_that_pdf(synthetic_pdf,
                                                                      synthetic_fixture,
                                                                      expected):
    """§6.3 — one frozen response per window, addressed by the rasters S2 is shown.

    Recomputed here rather than read from a manifest: the point of a content-addressable fixture
    is that the *pipeline's own* keys find it. If the schema, the dpi, the model or the prompt
    version moves, this test fails at the same moment replay starts missing — which is the
    behaviour F11 wants, and the alternative (a manifest of names) would keep passing.
    """
    from vsir.ingest import render, window
    from vsir.ingest.extract import S2_SCHEMA_HASH
    from vsir.vlm import EXTRACT, FixtureStore, extract_key

    probed = probe.run(synthetic_pdf)
    plan = window.plan(probed.page_count, toc=generator.toc_entries(),
                       size_bytes=probed.size_bytes)
    store = FixtureStore(synthetic_fixture)

    forms = 0
    for win in plan.windows:
        key = extract_key(
            render.page_hashes(synthetic_pdf, win.page_numbers, dpi=DPI_ANSWER,
                               content_hash=probed.content_hash),
            vlm_model=BASE_ENV["VSIR_VLM_MODEL"],
            prompt_version=BASE_ENV["VSIR_PROMPT_VERSION"], dpi=DPI_ANSWER,
            schema_hash=S2_SCHEMA_HASH)
        forms += len(json.loads(store.get(EXTRACT, key).body)["pages"])

    assert len(plan.windows) == expected["extraction"]["windows"]
    assert forms == expected["extraction"]["page_forms"]


def test_two_sections_straddle_a_window_fold(expected):
    """F8 — the corpus is only useful for stitching if a section actually crosses a fold."""
    folds = {end for _, end in expected["windows"][:-1]}
    straddling = [section["title"] for section in expected["sections"]
                  if any(section["first"] <= fold < section["last"] for fold in folds)]

    assert straddling == expected["straddling_sections"]
