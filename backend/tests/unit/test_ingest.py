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
from vsir.eval import synthetic_pdf as generator
from vsir.ingest import probe

BASE_ENV = {
    "VSIR_PORT": "8000",
    "VSIR_QDRANT_URL": "http://localhost:6333",
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


def test_ingest_reports_each_step_on_the_event_stream(env, capsys, synthetic_pdf):
    """§15 Factor XI — one JSON object per line, every one carrying the run id."""
    _run(synthetic_pdf, "--until", "window")
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()
              if line.startswith("{")]

    steps = [event["step"] for event in events if event["event"] == "ingest_step"]
    assert steps == ["manifest", "probe", "render", "facts", "window"]
    assert {event["release_id"] for event in events} == {"test-0"}
    assert all(event["run_id"] for event in events)


@pytest.mark.parametrize("until", cli.INGEST_STEPS)
def test_ingest_stops_where_it_is_told(env, capsys, synthetic_pdf, until):
    code = _run(synthetic_pdf, "--until", until)
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()
              if line.startswith("{")]
    steps = [event["step"] for event in events if event["event"] == "ingest_step"]

    assert code == cli.EXIT_OK
    assert steps == list(cli.INGEST_STEPS[:cli.INGEST_STEPS.index(until) + 1])


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


def test_a_backend_with_no_client_refuses_by_name(env, capsys, synthetic_pdf):
    """At M2a the fixture is the only thing that can fill the S1 cache; the Gemini client is U008's.
    A run that cannot make the call says so and exits non-zero — it never proceeds without facts."""
    code = _run(synthetic_pdf, "--vlm", "gemini", "--until", "facts")
    out = capsys.readouterr().out

    assert code == cli.EXIT_REFUSED
    assert "vlm_backend_unavailable" in out


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

    def key_now() -> str:
        return window.facts_key(probe.content_hash(synthetic_pdf),
                                vlm_model=BASE_ENV["VSIR_VLM_MODEL"],
                                prompt_version=BASE_ENV["VSIR_PROMPT_VERSION"])

    key = key_now()
    assert key == key_now(), "two runs over the same PDF must re-bill S1 zero times"
    path = synthetic_fixture / "facts" / f"{key}.json"

    assert path.is_file(), f"no frozen S1 response at {path}"
    facts = window.DocumentFacts.model_validate_json(path.read_text())
    assert [entry.page_no for entry in facts.toc] == [start for start, _ in generator.CHAPTERS]


def test_two_sections_straddle_a_window_fold(expected):
    """F8 — the corpus is only useful for stitching if a section actually crosses a fold."""
    folds = {end for _, end in expected["windows"][:-1]}
    straddling = [section["title"] for section in expected["sections"]
                  if any(section["first"] <= fold < section["last"] for fold in folds)]

    assert straddling == expected["straddling_sections"]
