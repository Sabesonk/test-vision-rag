"""L2 — §6.4's repair, in the **production** path: bisect and re-bill, never pad and never guess.

Spec §6.2, §6.4, §11.1 · invariant **I4** · failure rows **F7**, **F13**.

`tests/unit/test_derive_offset.py` proves that `derive()` bisects when it is handed something to
re-bill with. This suite proves the other half, which is the half that actually ships: that
`vsir ingest` **hands it one**. Without that argument the repair is a capability rather than a
behaviour — a real document whose second window came back shifted by a page would fail the run
instead of being repaired, and I4 as §9 words it ("a failure bisects and re-bills") would not hold
end to end.

The corpus is the checked-in 3-window fixture, copied to a temporary directory and doctored:
window 2's frozen response gets its printed labels rotated by one, which is exactly the off-by-one
signature §6.4's second check exists to catch, and the two halves' correct responses are frozen
under **their own** `extract_key`s — which is what a re-billed call would produce, because the key
is computed from the pages the call actually covers (§6.3).

Nothing here is a live call: the doctored fixture is replay all the way down (D10).
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from qdrant_client import QdrantClient

from vsir import cli
from vsir.config import DPI_ANSWER, load_config
from vsir.ingest import derive as derive_module
from vsir.ingest import extract as extract_module
from vsir.ingest import index as index_module
from vsir.ingest import manifest, probe, render
from vsir.ingest import run as run_module
from vsir.ingest import window as window_module
from vsir.ingest.extract import S2_SCHEMA_HASH
from vsir.vlm import backend as vlm_backend
from vsir.vlm import cache as vlm_cache

REPO = Path(__file__).resolve().parents[3]
PDF = REPO / "data" / "source" / "synthetic_3window.pdf"
FIXTURE = REPO / "data" / "fixtures" / "synthetic_3window"
DOC = "synthetic-3window"

COLLECTION = "vsir_pages_offset"
PAGES_COLLECTION = f"{COLLECTION}_1536"
RUNS = "vsir_runs_offset"
PAGES = 42
#: The middle window of the ladder, and the halves §6.2 splits it into.
SHIFTED = (15, 28)
HALVES = ((15, 21), (22, 28))

BASE_ENV = {
    "VSIR_PORT": "8000", "VSIR_COLLECTION": COLLECTION, "VSIR_RUNS_COLLECTION": RUNS,
    "VSIR_VLM": "stub", "VSIR_VLM_MODEL": "gemini-3.8-flash-001",
    "VSIR_EMBED_MODEL": "gemini-embedding-2", "VSIR_PROMPT_VERSION": "s2-v1",
    "VSIR_API_TOKENS": "test-only-not-a-credential", "VSIR_READ_QUOTA": "10",
    "VSIR_ALLOW_PAID": "0", "VSIR_LOG_LEVEL": "INFO", "VSIR_RELEASE_ID": "test-0",
}


def key_for(start: int, end: int, cfg: Any, content_hash: str) -> str:
    """The `extract_key` for a window — over the ordered page image hashes S2 would see (§6.3)."""
    hashes = render.page_hashes(PDF, range(start, end + 1), dpi=DPI_ANSWER,
                                content_hash=content_hash)
    return vlm_cache.extract_key(hashes, vlm_model=cfg.vlm_model,
                                 prompt_version=cfg.prompt_version, dpi=DPI_ANSWER,
                                 schema_hash=S2_SCHEMA_HASH)


def rotate_labels(body: dict) -> dict:
    """The off-by-one signature: every form keeps its `page_index` and takes its neighbour's label.

    The window is right and the *response* describes the sheets one along — which is how the
    failure actually arises, because the plan is authoritative and `window.start` is not what goes
    wrong. Coverage still holds, so §6.4's second check is the only thing that can notice.
    """
    forms = body["pages"]
    labels = [form["printed_page_no"] for form in forms]
    for index, form in enumerate(forms):
        form["printed_page_no"] = labels[(index + 1) % len(labels)]
    return body


def half_of(body: dict, window: tuple[int, int], parent: tuple[int, int]) -> dict:
    """The parent window's **correct** forms for one half, renumbered into its `page_index` space.

    This is what a re-billed call returns: the same pages, described correctly, under a key that
    belongs to the half. The renumbering is the whole reason each half gets its own key —
    `impl` merged the halves and filed them under the parent's key, so the repair was invisible on
    the next run (§6.3).
    """
    start, end = window
    forms = [dict(form, page_index=parent[0] + form["page_index"] - 1 - start + 1)
             for form in body["pages"]
             if start <= parent[0] + form["page_index"] - 1 <= end]
    return {"pages": forms}


@pytest.fixture(scope="module")
def doctored(tmp_path_factory) -> Path:
    """The checked-in fixture, with window 2 shifted and both halves frozen beside it."""
    root = tmp_path_factory.mktemp("fixture")
    shutil.copytree(FIXTURE, root, dirs_exist_ok=True)
    cfg = load_config({**BASE_ENV, "VSIR_QDRANT_URL": "http://127.0.0.1:6399",
                       "VSIR_FIXTURE": str(root)})
    probed = probe.run(PDF)

    parent_key = key_for(*SHIFTED, cfg, probed.content_hash)
    correct = json.loads((root / "extract" / f"{parent_key}.json").read_text())
    for half in HALVES:
        vlm_cache.write(root, "extract", key_for(*half, cfg, probed.content_hash),
                        json.dumps(half_of(correct, half, SHIFTED)))
    vlm_cache.write(root, "extract", parent_key,
                    json.dumps(rotate_labels(json.loads(json.dumps(correct)))))
    # The acceptance table describes the **pristine** corpus, and two of its rows are legitimately
    # different here: the CLI's own armed-trap row shifts window 2 again (which un-shifts it), and
    # F6's reattribution moves a code across page 21|22 — the very boundary the bisection splits
    # on, and §6.5 never moves a code between windows. Keeping the table would make this suite
    # assert the pristine corpus's numbers about a corpus it deliberately changed;
    # `test_the_undoctored_corpus_needs_no_repair_at_all` is where the table still runs.
    (root / "expected.json").unlink()
    return root


@pytest.fixture
def store(qdrant):
    def drop() -> None:
        for name in (PAGES_COLLECTION, RUNS):
            if qdrant.collection_exists(name):
                qdrant.delete_collection(name)

    drop()
    try:
        yield qdrant
    finally:
        drop()


def qdrant_url() -> str:
    return os.environ.get("VSIR_TEST_QDRANT_URL", "http://localhost:6335")


@pytest.fixture
def ingest(monkeypatch, doctored, store):
    """`vsir ingest` in this process, against the L2 Qdrant and the doctored replay directory."""
    for name, value in {**BASE_ENV, "VSIR_QDRANT_URL": qdrant_url(),
                        "VSIR_FIXTURE": str(doctored)}.items():
        monkeypatch.setenv(name, value)

    def run(*arguments: str) -> int:
        return cli.main(["ingest", str(PDF), "--vlm", "stub", *arguments])

    return run


# ── the ladder is armed: the doctored fixture really is shifted ──────────────────────────────────

def test_the_doctored_window_carries_its_neighbours_labels(doctored):
    """The trap is real before anything is asserted about the repair. A fixture that was not
    actually shifted would make every row below pass for the wrong reason."""
    cfg = load_config({**BASE_ENV, "VSIR_QDRANT_URL": "http://127.0.0.1:6399",
                       "VSIR_FIXTURE": str(doctored)})
    probed = probe.run(PDF)
    shifted = json.loads((doctored / "extract" /
                          f"{key_for(*SHIFTED, cfg, probed.content_hash)}.json").read_text())
    original = json.loads((FIXTURE / "extract" /
                           f"{key_for(*SHIFTED, cfg, probed.content_hash)}.json").read_text())

    labels = [form["printed_page_no"] for form in shifted["pages"]]
    was = [form["printed_page_no"] for form in original["pages"]]

    assert labels != was
    assert labels == was[1:] + was[:1]
    assert [form["page_index"] for form in shifted["pages"]] == list(range(1, 15))


def test_both_halves_are_frozen_under_their_own_keys(doctored):
    """§6.3 — each half's key is a fact about the pages it covers, so a re-billed call finds it."""
    cfg = load_config({**BASE_ENV, "VSIR_QDRANT_URL": "http://127.0.0.1:6399",
                       "VSIR_FIXTURE": str(doctored)})
    probed = probe.run(PDF)
    keys = {half: key_for(*half, cfg, probed.content_hash) for half in HALVES}

    assert len(set(keys.values())) == 2
    for half, key in keys.items():
        body = json.loads((doctored / "extract" / f"{key}.json").read_text())
        assert [form["page_index"] for form in body["pages"]] == \
            list(range(1, half[1] - half[0] + 2))


# ── the production repair (I4, F7, F13) ──────────────────────────────────────────────────────────

def test_a_shifted_window_is_bisected_re_billed_and_the_document_still_publishes(store, ingest,
                                                                                 capsys):
    """AC + I4: a real `vsir ingest` over a shifted window **bisects and re-bills**, and the
    document publishes complete. Before the `reextract` argument was wired into the CLI this run
    failed with `offset_check_failed` — the repair existed and nothing invoked it."""
    code = ingest()
    out = capsys.readouterr().out

    assert code == cli.EXIT_OK, out[-4000:]
    assert index_module.count(store, PAGES_COLLECTION,
                              {"doc_id": DOC, "is_current": True}) == PAGES

    events = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    bisects = [event for event in events if event["event"] == "derive_bisect"]
    assert len(bisects) == 1
    assert bisects[0]["window"] == list(SHIFTED)
    assert bisects[0]["halves"] == [list(half) for half in HALVES]
    assert bisects[0]["check"] == "independent_observation"


def test_no_page_is_derived_from_the_response_that_failed_the_check(store, ingest):
    """§6.2, §6.3 — the halves **replace** the parent entirely. A page carrying the failed call's
    receipt would be a page derived from a response the pipeline decided not to believe."""
    cfg = load_config({**BASE_ENV, "VSIR_QDRANT_URL": qdrant_url(),
                       "VSIR_FIXTURE": str(FIXTURE)})
    parent = key_for(*SHIFTED, cfg, probe.run(PDF).content_hash)

    assert ingest() == cli.EXIT_OK

    pages = run_module.run_records(store, PAGES_COLLECTION, doc_id=DOC, revision="1.0",
                                   run_id=run_module.runs(store, RUNS)[0].run_id)
    keys = {page.provenance.extract_key for page in pages}
    assert parent not in keys
    assert len({page.page_no for page in pages}) == PAGES


def test_the_repaired_window_is_recorded_as_bisected_on_its_control_point(store, ingest):
    """§6.7 — the window point says the repair happened. F13's ladder is not a defect to hide:
    a bisected window is a **pass** that re-billed, and the run record has to show which."""
    assert ingest() == cli.EXIT_OK

    record = run_module.runs(store, RUNS)[0]
    windows = run_module.windows(store, RUNS, record.run_id)

    assert [window.window for window in windows] == [[1, 14], [15, 28], [29, 42]]
    assert [window.bisected for window in windows] == [False, True, False]
    assert all(window.offset_ok for window in windows)
    assert record.state == run_module.PUBLISHED
    assert record.gate_results["offset_check"]["pass"] is True
    assert "bisected and re-billed" in record.gate_results["offset_check"]["detail"]


def test_the_undoctored_corpus_needs_no_repair_at_all(store, monkeypatch, request):
    """The control: the checked-in fixture publishes with **no** bisection. Without this row the
    rows above would pass on a pipeline that bisected every window it saw."""
    for name, value in {**BASE_ENV, "VSIR_QDRANT_URL": qdrant_url(),
                        "VSIR_FIXTURE": str(FIXTURE)}.items():
        monkeypatch.setenv(name, value)

    assert cli.main(["ingest", str(PDF), "--vlm", "stub"]) == cli.EXIT_OK

    record = run_module.runs(store, RUNS)[0]
    assert record.state == run_module.PUBLISHED
    assert not any(window.bisected for window in run_module.windows(store, RUNS, record.run_id))
    assert record.gate_results["offset_check"]["detail"].endswith("passed both §6.4 checks")


# ── the terminal case: a failure the ladder cannot repair gates the run (§11.1) ──────────────────

def test_an_unrepairable_offset_failure_gates_the_run_and_names_the_window(store, monkeypatch,
                                                                          capsys):
    """AC: any window failing either §6.4 check **blocks** publish, and the run record names the
    failing window — with zero pages queryable (I7).

    Driven through `cli._offset_blocked` directly rather than through a doctored corpus, because
    the reachable end-to-end failures downstream of the repair are §6.2's own terminus
    (`window_unsplittable`) and a replay miss, both of which fail the run before derivation can
    reach a verdict. What is asserted is the path an unrepairable §6.4 failure takes: the failing
    window is written with `offset_ok=False`, the gate reads it the way it reads every other
    window, and the run is `gated` rather than published.
    """
    for name, value in {**BASE_ENV, "VSIR_QDRANT_URL": qdrant_url(),
                        "VSIR_FIXTURE": str(FIXTURE)}.items():
        monkeypatch.setenv(name, value)
    cfg = load_config()
    client = QdrantClient(url=qdrant_url(), check_compatibility=False)
    doc = manifest.build(PDF)
    probed = probe.run(PDF)
    facts, _ = extract_module.document_facts(vlm_backend(cfg), source=PDF, probed=probed,
                                             vlm_model=cfg.vlm_model,
                                             prompt_version=cfg.prompt_version)
    plan = window_module.plan(probed.page_count, toc=facts.toc, size_bytes=probed.size_bytes,
                              document=doc.doc_id)
    handle = cli._RunHandle(client=client, runs_collection=RUNS)
    handle.record = run_module.start(client, RUNS, run_id="01J0OFFSETBLOCKED00000000",
                                     doc_id=doc.doc_id, revision=doc.revision,
                                     release_id="test-0", collection=PAGES_COLLECTION,
                                     page_count=probed.page_count,
                                     windows_total=len(plan.windows), owner="suite")
    failure = derive_module.OffsetError(
        "the model read a neighbour's label", window=[plan.windows[0].start, plan.windows[0].end],
        check="independent_observation")

    passed = cli._offset_blocked(
        None, cfg, handle, doc=doc, probed=probed, plan=plan,
        keys=tuple(f"key-{index}" for index, _ in enumerate(plan.windows)),
        extraction=None, failure=failure)
    out = capsys.readouterr().out

    assert passed is False
    record = run_module.require(client, RUNS, handle.record.run_id)
    assert record.state == run_module.GATED and record.published_at is None
    assert record.gate_results["offset_check"]["pass"] is False
    assert record.gate_results["offset_check"]["evidence"][0]["window"] == \
        [plan.windows[0].start, plan.windows[0].end]
    assert record.gate_results["offset_check"]["evidence"][0]["check"] == \
        "independent_observation"
    assert index_module.count(client, PAGES_COLLECTION,
                              {"doc_id": doc.doc_id, "is_current": True}) == 0
    assert "0 page(s)" in out and "queryable" in out
    client.close()
