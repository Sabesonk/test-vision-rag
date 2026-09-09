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
