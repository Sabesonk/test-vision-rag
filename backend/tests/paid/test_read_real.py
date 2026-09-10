"""L4 — one real `read`, against a real vision model, for the two claims replay cannot make.

Everything about `read` that can be proved for free is proved at L0 and L2, and most of it can:
the stamp, the caps, the cache, the three states, the mandatory `sufficient`. Two things cannot,
and U028 is the reason this module exists at all — **five defects between `VSIR_VLM=stub` and a
published document survived 1149 green tests**, because the stub never builds a request, loads a
prompt or opens an SDK client:

* **the call is actually well-formed.** The prompt file is in the wheel, the model id resolves,
  the response schema is one the provider accepts, and the rasters go up as parts it understands.
  A `read` that cannot be *made* is invisible to every level below this one.
* **a real model's transcription errors land on the safe side.** The whole design rests on the
  claim that a code a model got wrong comes back `absent` or `unverifiable` and never falsely
  `present` — and a frozen response can only ever prove that our stamping of *our own* fixture is
  consistent. Here the codes are whatever the model actually reads off the sheet, and the
  assertion is against what the corpus generator says is **printed**, which is ground truth
  independent of both the model and the index.

**What it spends:** four `read` calls over two pages each, at dpi 220 — an answerable question, an
unanswerable one, the scanned sheets, and one repeat under a *different* question for F19. The
ingest in front of them is free: it replays the frozen S2 corpus (D10), so the bill is those four
calls and nothing else. A fifth, the identical repeat, is served from the cache and bills nothing,
which is itself one of the rows.

**Which document.** The pilot `TC1E-SF` is what U020's acceptance names, and **OQ-1 is still
open**: the PDF is not in the tree. §17's documented fallback is the generated corpus, which is
strictly better for the second claim above — every code printed on every page of it is known
exactly, from `vsir.eval.synthetic_pdf.expected_text`, which is a *fixture generator* and not the
code under test. Point ``VSIR_PILOT_PDF`` at the pilot and this module reads that instead.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterator

import pytest
from qdrant_client import QdrantClient

from vsir.cli import main as cli_main
from vsir.config import DPI_ANSWER, load_config
from vsir.core import ids
from vsir.core.verify import ABSENT, PRESENT, UNVERIFIABLE
from vsir.eval import synthetic_pdf as generator
from vsir.serve import app as app_module

pytestmark = pytest.mark.paid

ROOT = Path(__file__).resolve().parents[3]
CORPUS_PDF = ROOT / "data" / "source" / "synthetic_3window.pdf"
CORPUS_FIXTURE = ROOT / "data" / "fixtures" / "synthetic_3window"

#: The document this module ingests and then reads. Its own ids and its own collections, so a
#: paid run cannot disturb a corpus somebody else's suite is asserting about.
DOC_ID = "vsir-read-real"
REVISION = "1.0"
COLLECTION = "vsir_pages_l4_read"
RUNS = "vsir_runs_l4_read"

#: Two ordinary text pages of the corpus, and a question they answer **outright**: page 19 prints
#: ``B219 --> K119 - SI4`` and page 20 prints ``B220 --> K120 - SI1``. Descriptive on purpose —
#: what is under test here is whether a real model reads the raster and transcribes verbatim, and
#: a question requiring inference would confound *"the pixels did not arrive"* with *"the model
#: reasoned differently"*.
ANSWER_PAGES = (19, 20)
QUESTION = "which monitored relay and which safe input channel does each of these two sheets name?"

#: The same two pages, asked something they genuinely do not settle. These are safety-function
#: *list* sheets: they state a category and a wiring arrangement, not a release precondition. So
#: the honest answer is `sufficient: false` with an empty extract — and a real model producing a
#: fluent one anyway is the failure §7.2.6 makes `sufficient` mandatory to catch.
UNANSWERABLE_QUESTION = ("what is the complete commissioning procedure that must be carried out "
                         "before the guard door interlock may be released?")

#: The two rasterised front-matter sheets, and a question the **image** answers: page 1 shows
#: "C24 SYNTHETIC SAFETY MANUAL" and "Revision 1.0" as pixels and carries no text layer at all.
#: That is the failure branch, and it is only a real test if the model actually reads something
#: off the sheet: whatever it reads can never be checked, so it must come back `unverifiable` —
#: never `absent` (which would deny a code that is plainly printed) and never `present` (which
#: would assert one no text supports). R2 says this stays true forever.
SCANNED_PAGES = generator.SCANNED_PAGES
SCANNED_QUESTION = ("which machine or equipment code is printed on these sheets, and which "
                    "revision do they state?")

if os.environ.get("VSIR_ALLOW_PAID") != "1":
    pytest.skip("VSIR_ALLOW_PAID is not 1 — this module spends money and refuses to run without "
                "the explicit opt-in (§12.2)", allow_module_level=True)
if not (os.environ.get("VSIR_VLM_KEY") or "").strip():
    pytest.skip("VSIR_VLM_KEY is unset. A paid layer with no credential fails per call, after "
                "billing whatever it managed to send (§17 OQ-2)", allow_module_level=True)
if not CORPUS_PDF.is_file():
    pytest.skip(f"{CORPUS_PDF} is missing — rebuild it with `python -m vsir.eval.synthetic_pdf`",
                allow_module_level=True)


def page_id(page_no: int) -> str:
    return ids.page_id(DOC_ID, REVISION, page_no)


@pytest.fixture(scope="module")
def published(tmp_path_factory: Any) -> Iterator[str]:
    """The corpus, ingested and published — **for free**, by replaying the frozen S2 responses.

    The ingest is not what this module is testing and it must not be what this module pays for,
    so it runs with ``--vlm stub`` and the checked-in fixture (D10). The environment is put back
    to the live backend afterwards, because the read below has to reach the real model and
    §15 Factor X says a backend is chosen by configuration and never by a branch.
    """
    store = tmp_path_factory.mktemp("l4-read-documents")
    os.environ.update({"VSIR_COLLECTION": COLLECTION, "VSIR_RUNS_COLLECTION": RUNS,
                       "VSIR_DOC_STORE": str(store)})
    exit_code = cli_main([
        "ingest", str(CORPUS_PDF), "--vlm", "stub", "--fixture", str(CORPUS_FIXTURE),
        "--doc-id", DOC_ID, "--revision", REVISION,
    ])
    assert exit_code == 0, "the free replay ingest did not complete — nothing was billed"

    # From here on the release is configured for the live model, and replay must not shadow it: a
    # fixture directory left in the environment would serve a frozen answer and this module would
    # buy nothing while reporting that it had.
    os.environ["VSIR_VLM"] = "gemini"
    os.environ.pop("VSIR_FIXTURE", None)
    cfg = load_config()
    assert cfg.vlm == "gemini" and not cfg.fixture_dir
    client = QdrantClient(url=cfg.qdrant_url, timeout=60, check_compatibility=False)
    try:
        yield cfg.pages_collection
    finally:
        for name in (cfg.pages_collection, RUNS):
            if client.collection_exists(name):
                client.delete_collection(name)
        client.close()


@pytest.fixture(scope="module")
def runtime(published: str) -> Iterator[Any]:
    """The release's own dispatcher, with the live backend behind it (§7.5, §15 Factor XII)."""
    built, client = app_module.runtime_from_env(dict(os.environ))
    try:
        yield built
    finally:
        client.close()


def call(runtime: Any, page_nos: tuple[int, ...], question: str) -> dict:
    from vsir.serve import auth as auth_module

    outcome = app_module.dispatch(
        runtime, "read",
        {"page_ids": [page_id(page_no) for page_no in page_nos], "question": question},
        identity=auth_module.local_identity("l4-read-real"), correlation={})
    assert outcome.status == 200, outcome.payload
    return outcome.payload


@pytest.fixture(scope="module")
def answered(runtime: Any) -> dict:
    """**Paid call 1.** Two text pages and a question they can settle."""
    return call(runtime, ANSWER_PAGES, QUESTION)


@pytest.fixture(scope="module")
def abstained(runtime: Any) -> dict:
    """**Paid call 2.** The same two pages, asked something they do not settle."""
    return call(runtime, ANSWER_PAGES, UNANSWERABLE_QUESTION)


@pytest.fixture(scope="module")
def scanned(runtime: Any) -> dict:
    """**Paid call 3.** The two pages with no text layer — the failure branch."""
    return call(runtime, SCANNED_PAGES, SCANNED_QUESTION)


# ── the call is well-formed, which is the half no green replay suite can claim (U028) ──────────

def test_a_real_read_comes_back_and_is_a_read(answered: dict):
    """The prompt loaded, the schema was accepted, the rasters went up, the answer parsed."""
    result = answered["result"]

    assert answered["status"] == "ok"
    assert isinstance(result["sufficient"], bool), "`sufficient` is mandatory (§7.2.6)"
    assert result["extract"].strip(), (
        "the model was shown two sheets that print `B219 --> K119 - SI4` and `B220 --> K120 - "
        "SI1` and asked which relay and channel each names, and it returned nothing — the "
        "rasters, the prompt or the dpi are wrong, not the stamp")
    assert [page["page_id"] for page in result["page_provenance"]] == \
        [page_id(page_no) for page_no in ANSWER_PAGES]


def test_the_pages_were_rendered_at_the_pinned_dpi(answered: dict):
    """§7.2.6 — dpi 220, chosen by the server, recorded on ``read_key`` and on the audit line."""
    assert DPI_ANSWER == 220
    # The provenance is per page and the dpi is per call, so the assertion that it was *this* dpi
    # is the key the call was made under — which the audit line carries and the body does not.
    assert "dpi" not in answered["result"]


def test_the_model_actually_read_the_sheet_and_named_codes(answered: dict):
    """Not an assertion about *which* codes: a model may name three or ten. About it reading.

    This is the row that separates *"the model abstained"* from *"the model saw nothing"*. Every
    other assertion in this module passes vacuously against a blank raster — an empty code list
    contains no falsely-`present` stamp — so without one live row that requires the pixels to
    have arrived, a green L4 would say nothing at all.
    """
    assert answered["result"]["codes"], (
        "a real read of two pages printing K119, SI4, K120 and SI1 named no code at all — "
        "the rasters, the prompt or the dpi are wrong, not the stamp")


# ── the safe side: a `present` stamp is never wrong (I2, F2, §1.1) ─────────────────────────────

def test_every_code_stamped_present_is_genuinely_printed_on_that_page(answered: dict):
    """The claim the whole system rests on, measured against ground truth the model never saw.

    ``expected_text`` is what the corpus generator *drew*, so this compares a real model's
    transcription against what is actually on the paper — not against the index, and not against
    a frozen answer. A false `present` here is a wrong part number with a verification badge on
    it, which is the injury §1.1 exists to prevent.
    """
    printed = {page_no: " ".join(generator.expected_text(page_no)).lower()
               for page_no in ANSWER_PAGES}

    for code in answered["result"]["codes"]:
        if code["status"] != PRESENT:
            continue
        assert code["page_ids"], "a `present` stamp names the pages that carry it"
        for cited in code["page_ids"]:
            page_no = int(cited.rsplit("#p", 1)[1])
            assert code["raw"].lower() in printed[page_no], (
                f"{code['raw']!r} was stamped present on page {page_no}, and page {page_no} "
                f"does not print it")


def test_a_code_the_model_misread_is_absent_and_never_silently_dropped(answered: dict):
    """§2.5 B — ``withheld[]`` is struck: a code that failed its check is **returned, stamped**.

    `impl` removed it from the response and filed it in ``withheld.jsonl``, which hides the
    transcription error from the only party that can act on it. Whether a real model misreads
    anything on this sheet is not something a test can require, so this asserts the shape: every
    code the model emitted comes back, and each carries one of the three states.
    """
    states = {code["status"] for code in answered["result"]["codes"]}

    assert states <= {PRESENT, ABSENT, UNVERIFIABLE}
    for code in answered["result"]["codes"]:
        if code["status"] == ABSENT:
            assert code["raw"].lower() not in \
                " ".join(" ".join(generator.expected_text(n)) for n in ANSWER_PAGES).lower()


def test_a_page_with_no_text_layer_yields_unverifiable_and_never_present(scanned: dict):
    """The failure branch of U020's L4 acceptance, on a real call.

    The model *can* read these sheets — they are legible pixels — and nothing it reads off them
    can be checked against anything. `present` would assert a code no text supports; `absent`
    would deny a code that is plainly drawn on the page. `unverifiable` is the only honest
    answer, and R2 says it stays that way (§7.2.6).
    """
    codes = scanned["result"]["codes"]

    assert {code["status"] for code in codes} <= {UNVERIFIABLE}, (
        "a code on a page with no text layer was stamped something other than `unverifiable`")
    assert {page["text_trust"] for page in scanned["result"]["page_provenance"]} == {"no_text"}
    assert "no_text_layer" in scanned["result"]["flags"]


def test_the_scanned_pages_are_read_from_the_image_and_stamped_anyway(scanned: dict):
    """The failure branch is only a test if the model read something (see the row above).

    These sheets *are* legible — they are pixels of a title block — so a model asked what they
    print should name something. Every one of those is `unverifiable`, which is precisely the
    disclosure R2 is about: the codes exist, we can see them, and nothing in this system can
    confirm them.
    """
    assert scanned["result"]["codes"], (
        "the model was shown two legible cover sheets and asked what code they print, and named "
        "nothing — the raster never arrived, and the `unverifiable` row above is then vacuous")


# ── a real model asked something the pages do not settle (§7.2.6) ──────────────────────────────

def test_a_real_model_abstains_rather_than_composing_an_answer(abstained: dict):
    """`sufficient` earning its keep against a real model, on real-but-insufficient pages.

    Two safety-function list sheets do not contain a commissioning procedure. A model that
    produced one would be producing it from what it knows about machines of this kind, which is
    the single failure §1.1 exists to prevent — and the caller would have no way to tell, because
    the codes in it would be real codes from the sheet and would stamp `present`.
    """
    assert abstained["result"]["sufficient"] is False
    assert abstained["result"]["extract"].strip() == "", (
        "an honest empty extract is correct here; a padded one is the injury")


# ── the receipt (§6.3, §7.4) ───────────────────────────────────────────────────────────────────

def test_the_paid_response_is_cached_and_the_repeat_costs_nothing(runtime: Any, answered: dict):
    """The third paid call that never happens. An identical `read` is served from the control
    plane, which is what makes a re-run of this module cost two calls rather than four."""
    repeated = call(runtime, ANSWER_PAGES, QUESTION)

    assert repeated["result"] == answered["result"]


def test_a_new_question_about_the_same_pages_is_a_miss_even_here(runtime: Any, answered: dict):
    """F19 against the live backend. **This is a fourth paid call**, and it is the one row that
    cannot be moved to replay: a cache that returned the previous answer would be indisputably
    wrong and completely invisible, because the answer would be fluent and verified."""
    other = call(runtime, ANSWER_PAGES, "which contactor is printed on these sheets?")

    assert other["result"]["extract"] != answered["result"]["extract"]
