"""Shared L0/L1 fixtures — the generated M2a corpus and the numbers checked in beside it.

The corpus is `data/source/synthetic_3window.pdf` and `data/fixtures/synthetic_3window/`, both
built by `vsir.eval.synthetic_pdf` and both committed. Tests read the expectations from
`expected.json` rather than computing them, for the same reason §12.3's acceptance table is
absolute rather than comparative (C10): a number a test derives from the code under test cannot
fail, it can only be re-baselined.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SYNTHETIC_PDF = REPO / "data" / "source" / "synthetic_3window.pdf"
SYNTHETIC_FIXTURE = REPO / "data" / "fixtures" / "synthetic_3window"


@pytest.fixture(scope="session")
def synthetic_pdf() -> Path:
    """The generated 3-window corpus. A missing file is a failure, never a skip.

    A skipped fixture-consuming suite is a green run of tests that asserted nothing, which is
    exactly the failure mode `vsir demo exact --synthetic` refuses for the M1 corpus.
    """
    assert SYNTHETIC_PDF.is_file(), (
        f"{SYNTHETIC_PDF} is missing — rebuild it with "
        f"`python -m vsir.eval.synthetic_pdf` (it is checked in)"
    )
    return SYNTHETIC_PDF


@pytest.fixture(scope="session")
def synthetic_fixture() -> Path:
    """The replay directory: the frozen S1 response and the acceptance table (D10, §12.1)."""
    assert SYNTHETIC_FIXTURE.is_dir(), (
        f"{SYNTHETIC_FIXTURE} is missing — rebuild it with `python -m vsir.eval.synthetic_pdf`"
    )
    return SYNTHETIC_FIXTURE


@pytest.fixture(scope="session")
def expected(synthetic_pdf: Path) -> dict:
    """`expected.json`: the acceptance numbers, recorded by the producer, read by the consumer."""
    path = SYNTHETIC_FIXTURE / "expected.json"
    assert path.is_file(), f"{path} is missing — rebuild it with `python -m vsir.eval.synthetic_pdf`"
    return json.loads(path.read_text())


# ── the derived corpus (U009) ───────────────────────────────────────────────────────────────────
#
# Steps 01-08 over the generated PDF, replayed from the frozen fixture, once per session. The
# extraction is free (D10) but rendering 42 pages at dpi 220 is not free of *time*, and five L1
# suites ask the same question of the same document — so the pipeline runs once and the suites
# read it. Nothing here is mutated by a test: every object below is frozen or a Pydantic model,
# and a suite that needs a variation builds it with `dataclasses.replace` / `model_copy`.

SYNTHETIC_ENV = {
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


@pytest.fixture(scope="session")
def synthetic_config(synthetic_fixture: Path):
    """The corpus's configuration, built from a mapping rather than the process environment.

    `load_config(env=...)` is the same function the process boots with — no test-only path, and
    no `monkeypatch` leaking one suite's environment into another's (§15 Factor III).
    """
    from vsir.config import load_config

    return load_config({**SYNTHETIC_ENV, "VSIR_FIXTURE": str(synthetic_fixture)})


@pytest.fixture(scope="session")
def extracted(synthetic_pdf: Path, synthetic_config):
    """Steps 01-06: `(manifest, probe, facts, plan, extraction)` over the generated corpus."""
    from vsir.ingest import extract as extract_module
    from vsir.ingest import manifest, probe
    from vsir.ingest import window as window_module
    from vsir.vlm import backend as vlm_backend

    cfg = synthetic_config
    doc = manifest.build(synthetic_pdf)
    probed = probe.run(synthetic_pdf)
    client = vlm_backend(cfg)
    facts, _ = extract_module.document_facts(
        client, source=synthetic_pdf, probed=probed, vlm_model=cfg.vlm_model,
        prompt_version=cfg.prompt_version)
    plan = window_module.plan(probed.page_count, toc=facts.toc, size_bytes=probed.size_bytes,
                              document=doc.doc_id)
    extraction = extract_module.extract(
        client, source=synthetic_pdf, plan=plan, probed=probed, vlm_model=cfg.vlm_model,
        prompt_version=cfg.prompt_version)
    return doc, probed, facts, plan, extraction


@pytest.fixture(scope="session")
def derived(extracted, synthetic_config):
    """Step 07 over the whole corpus — the `Derivation` the L1 suites assert against."""
    from vsir.ingest import derive as derive_module

    doc, probed, facts, _plan, extraction = extracted
    cfg = synthetic_config
    return derive_module.derive(
        extraction, probed=probed, doc=doc, run_id="01J000000000000000000000",
        release_id=cfg.release_id, vlm_model=cfg.vlm_model, prompt_version=cfg.prompt_version,
        doc_lang=facts.lang)


@pytest.fixture(scope="session")
def stitched(derived, extracted):
    """Step 08 over the whole corpus — the finished records and their sections."""
    from vsir.ingest import stitch as stitch_module

    doc = extracted[0]
    return stitch_module.stitch(derived.pages, doc_id=doc.doc_id, revision=doc.revision)
