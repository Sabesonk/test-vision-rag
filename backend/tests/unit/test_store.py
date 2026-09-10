"""L0/L1 — the document store: ``page_id`` → bytes, and every way it refuses (U029, §4.2).

The unit's whole claim is a resolution chain — ``page_id`` → ``doc_id@revision`` → a file — and
three refusals that must never become something friendlier: a document that is not there, bytes
that are not the ones a run indexed, and an identifier that cannot safely be a file name. Each of
those has a way of degrading into a nicer-looking failure (a blank image, the wrong page, a
traversal), so each is asserted here rather than left to the route that will consume them (U018).

Everything is a `tmp_path`. Nothing in this file touches the configured store, and nothing here
needs Qdrant, a model or a PDF that is really a PDF: the store moves bytes and checks digests, and
whether they render is the renderer's business.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from vsir.config import Config
from vsir.ingest import store as store_module
from vsir.ingest.store import DocumentStore

BODY = b"%PDF-1.7\nnot really a pdf, and nothing in this module cares\n%%EOF\n"
OTHER = b"%PDF-1.7\ndifferent bytes entirely\n%%EOF\n"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def store(tmp_path: Path) -> DocumentStore:
    return DocumentStore(tmp_path / "documents")


# ── the resolution chain: page_id -> doc_id@revision -> bytes ───────────────────────────────────

def test_a_deposited_document_resolves_from_any_page_id_of_it(store):
    """The one job. Three pages of one document, one file, no path in anything (§5.3, A5)."""
    store.put("TC1E-SF", "1.3", body=BODY)

    for page_no in (1, 2, 42):
        source = store.for_page(f"TC1E-SF@1.3#p{page_no:03d}")

        assert source.page_no == page_no
        assert source.path.read_bytes() == BODY
        assert source.document.name == "TC1E-SF@1.3"


def test_the_file_is_named_for_the_document_so_no_payload_needs_a_path(store):
    stored = store.put("TC1E-SF", "1.3", body=BODY)

    assert stored.path.name == "TC1E-SF@1.3.pdf"
    assert stored.path.parent == store.root
    # And the name round-trips, which is what `entries()` relies on to list the store.
    assert store_module.split_file_name(stored.path.name) == ("TC1E-SF", "1.3")


def test_a_page_id_that_is_not_canonical_never_reaches_the_filesystem(store):
    """``#p0001`` is a different string and therefore a different point (`core.ids`). It is
    refused by the parser, so the store never has to decide what it meant."""
    store.put("TC1E-SF", "1.3", body=BODY)

    with pytest.raises(ValueError):
        store.for_page("TC1E-SF@1.3#p0001")


def test_the_page_number_is_carried_through_untouched(store):
    store.put("SYN-M1", "1.0", body=BODY)

    assert store.for_page("SYN-M1@1.0#p007").page_no == 7
    assert store.for_page("SYN-M1@1.0#p1000").page_no == 1000


# ── the three refusals (§11.3) ──────────────────────────────────────────────────────────────────

def test_a_document_that_is_not_stored_is_a_typed_refusal_naming_it(store):
    """Never a placeholder image, never a 500, never an empty result.

    A page that is indexed and cannot be shown is a different fact from a page that does not
    exist, and the refusal has to carry which document is missing or nobody can fix it.
    """
    with pytest.raises(store_module.DocumentNotStored) as refusal:
        store.for_page("TC1E-SF@1.3#p001")

    assert refusal.value.code == "document_not_stored"
    assert refusal.value.details["document"] == "TC1E-SF@1.3"
    assert refusal.value.details["doc_id"] == "TC1E-SF"
    assert refusal.value.details["revision"] == "1.3"
    assert "TC1E-SF@1.3" in str(refusal.value)


def test_bytes_that_disagree_with_the_run_are_refused_rather_than_served(store):
    """The case that otherwise fails silently: the same (doc_id, revision), corrected bytes.

    Until publish retires the previous run's pages (§6.7) the index still points at them, and
    rendering the new file for one of those pages answers with a page nobody indexed. The run
    record's ``content_hash`` is what makes the disagreement visible.
    """
    store.put("TC1E-SF", "1.3", body=BODY)
    indexed_under = sha256(BODY)
    store.put("TC1E-SF", "1.3", body=OTHER)          # a corrected re-ingest, allowed

    with pytest.raises(store_module.DocumentHashMismatch) as refusal:
        store.for_page("TC1E-SF@1.3#p001", expect_hash=indexed_under)

    assert refusal.value.code == "document_hash_mismatch"
    assert refusal.value.details["expected_hash"] == indexed_under
    assert refusal.value.details["stored_hash"] == sha256(OTHER)
    # And the same page with the *new* run's hash is served, because that run's pages are the
    # ones the new bytes belong to.
    assert store.for_page("TC1E-SF@1.3#p001", expect_hash=sha256(OTHER)).path.is_file()


@pytest.mark.parametrize("doc_id", ["../etc", "a/b", "a\\b", "..", ".hidden", "", "a b"])
def test_an_identifier_that_cannot_be_a_file_name_is_refused_not_mangled(store, doc_id):
    """A `page_id` can arrive from a saved citation (`resolve`, §7.2.3), so this is a traversal
    guard as much as a naming rule — and mangling would let two revisions share one file."""
    with pytest.raises(store_module.DocumentIdUnsafe) as refusal:
        store.path_for(doc_id, "1.0")

    assert refusal.value.code == "document_id_unsafe"
    assert refusal.value.http_status == 400


def test_the_traversal_guard_holds_for_the_revision_half_too(store):
    with pytest.raises(store_module.DocumentIdUnsafe):
        store.path_for("TC1E-SF", "../../../etc/passwd")


def test_a_traversal_carried_in_a_page_id_never_resolves(store):
    """The whole attack in one line: a citation is caller-supplied and `parse_page_id` accepts
    any revision but ``@`` and ``#``."""
    with pytest.raises(store_module.DocumentIdUnsafe):
        store.for_page("TC1E-SF@../../../../etc/passwd#p001")


def test_a_revision_that_looks_like_a_revision_is_fine(store):
    """The guard must not be so tight that a real corpus cannot be stored."""
    for revision in ("1.0", "1.3", "A", "2024-06-01", "rev_2", "1.0+draft", "undeclared"):
        assert store.path_for("TC1E-SF", revision).name == f"TC1E-SF@{revision}.pdf"


# ── depositing ──────────────────────────────────────────────────────────────────────────────────

def test_a_deposit_is_idempotent_and_leaves_one_file(store):
    first = store.put("TC1E-SF", "1.3", body=BODY)
    second = store.put("TC1E-SF", "1.3", body=BODY)

    assert first.path == second.path
    assert len(list(store.root.glob("*.pdf"))) == 1


def test_depositing_from_a_path_copies_the_bytes(store, tmp_path):
    source = tmp_path / "TC1E-SF.pdf"
    source.write_bytes(BODY)

    stored = store.put("TC1E-SF", "1.3", source=source)

    assert stored.path != source
    assert stored.path.read_bytes() == BODY
    assert stored.content_hash == sha256(BODY)


def test_depositing_a_file_that_is_already_the_stored_one_does_not_empty_it(store):
    """A resumed run re-ingests straight out of the store, so `source` *is* `destination`. A
    rename of a file onto itself through a staging copy would truncate the document."""
    stored = store.put("TC1E-SF", "1.3", body=BODY)

    again = store.put("TC1E-SF", "1.3", source=stored.path, content_hash=sha256(BODY))

    assert again.path.read_bytes() == BODY


def test_a_deposit_whose_hash_does_not_match_what_the_run_computed_is_refused(store, tmp_path):
    """The run hashed the file at step 02; if what lands in the store hashes differently, the
    bytes changed underneath the run and nothing downstream may assume otherwise."""
    with pytest.raises(store_module.DocumentHashMismatch):
        store.put("TC1E-SF", "1.3", body=BODY, content_hash=sha256(OTHER))


def test_a_deposit_takes_exactly_one_source(store):
    with pytest.raises(ValueError):
        store.put("TC1E-SF", "1.3")
    with pytest.raises(ValueError):
        store.put("TC1E-SF", "1.3", body=BODY, source=Path("x.pdf"))


def test_nothing_half_written_is_ever_visible_as_a_document(store):
    """Staged then renamed, and the staging directory is dot-prefixed so a listing skips it."""
    store.put("TC1E-SF", "1.3", body=BODY)

    assert (store.root / store_module.STAGING).is_dir()
    assert [entry.name for entry in store.entries()] == ["TC1E-SF@1.3"]


def test_an_unwritable_store_is_named_before_a_run_spends(tmp_path):
    blocked = tmp_path / "read-only"
    blocked.mkdir(mode=0o500)
    try:
        with pytest.raises(store_module.StoreUnwritable) as refusal:
            DocumentStore(blocked / "documents").ensure_writable()
    finally:
        blocked.chmod(0o700)

    assert refusal.value.code == "document_store_unwritable"


# ── listing, for `vsir documents` ───────────────────────────────────────────────────────────────

def test_an_empty_store_lists_nothing_rather_than_failing(store):
    assert store.entries() == ()


def test_the_store_lists_what_it_holds_in_name_order(store):
    store.put("SYN-M1", "1.0", body=BODY)
    store.put("TC1E-SF", "1.3", body=BODY)
    store.put("TC1E-SF", "1.4", body=OTHER)

    assert [entry.name for entry in store.entries()] == [
        "SYN-M1@1.0", "TC1E-SF@1.3", "TC1E-SF@1.4"]


def test_a_stray_pdf_that_is_not_a_document_is_skipped_not_crashed_on(store):
    store.put("TC1E-SF", "1.3", body=BODY)
    store.root.joinpath("something-else.pdf").write_bytes(BODY)

    assert [entry.name for entry in store.entries()] == ["TC1E-SF@1.3"]


def test_the_recorded_hash_is_the_same_digest_the_probe_computes(store):
    """`probe.content_hash` is the delta gate for every cache key (§6.3). If the store's idea of
    a document's identity differed from the probe's, the run record's hash would never match."""
    from vsir.ingest import probe

    stored = store.put("TC1E-SF", "1.3", body=BODY)

    assert stored.content_hash == probe.content_hash(stored.path) == sha256(BODY)


# ── configuration: the environment and only the environment (§15 Factor III) ────────────────────

def test_the_store_is_the_directory_the_configuration_names(tmp_path):
    cfg = _config(doc_store=str(tmp_path / "mounted"))

    assert DocumentStore.from_config(cfg).root == tmp_path / "mounted"


def test_an_unset_store_falls_back_rather_than_refusing_to_start():
    """Not one of the twelve (§4.3): a release that never ingests must still boot."""
    root = DocumentStore.from_config(_config(doc_store="")).root

    assert root.name == store_module.DEFAULT_DIRNAME
    assert root.is_absolute()


def test_the_environment_form_reads_the_same_variable(tmp_path):
    store = DocumentStore.from_env({store_module.STORE_ENV: str(tmp_path / "mounted")})

    assert store.root == tmp_path / "mounted"


def _config(**overrides) -> Config:
    return Config(
        port=8000, qdrant_url="http://localhost:6333", collection="vsir_pages", vlm="stub",
        vlm_model="gemini-3.8-flash", embed_model="gemini-embedding-2", prompt_version="s2-v1",
        read_quota=50, allow_paid=False, log_level="INFO", release_id="dev-0", embed_dim=1536,
        runs_collection="vsir_runs", reads_per_question=3, fixture_dir="", vlm_tier="standard",
        vlm_rpm=60, embed_text_chars=2000, api_tokens=("test-token",), **overrides)
