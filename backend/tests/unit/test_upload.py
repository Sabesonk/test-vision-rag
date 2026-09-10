"""L0/L1 — the upload boundary of ``POST /documents`` (§6.1, §15 Factor XII).

What is asserted here is everything that can be decided **without spawning anything**: the typed
refusals, the spend switch, and the shape of the argv the route would run. The argv matters more
than it looks — it is the whole claim that this route is a transport rather than a second
implementation of ingestion (register **E1**, where `impl`'s UI ingest silently did less than its
CLI one), so a test that pins it is a test that the two cannot drift.

The round trip — upload, poll §6.9's control plane, query the published document — needs a real
Qdrant and a real child process and lives in `tests/api/test_upload_route.py`.
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from vsir import config as config_module
from vsir.config import Config
from vsir.serve import ingest as upload

PDF = b"%PDF-1.7\n%\xc7\xec\x8f\xa2\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


class _Child:
    """A `Popen` stand-in: enough surface for `accept` to log it and for the reaper to finish."""

    pid = 4242
    returncode = 0

    def communicate(self):
        return ("", None)

    def wait(self):
        return 0


def _config() -> Config:
    """A replay-mode release: free by construction, so the spend switch is not in the way."""
    return Config(
        port=8000, qdrant_url="http://localhost:6333", collection="vsir_pages", vlm="stub",
        vlm_model="gemini-3.8-flash-001", embed_model="gemini-embedding-2",
        prompt_version="s2-v1", read_quota=50, allow_paid=False, log_level="INFO",
        release_id="dev-0", embed_dim=1536, runs_collection="vsir_runs", reads_per_question=3,
        fixture_dir="data/fixtures/synthetic_3window", vlm_tier="standard", vlm_rpm=60,
        embed_text_chars=2000, api_tokens=("test-token",),
    )


@pytest.fixture
def cfg() -> Config:
    return _config()


# ── what can be refused before anything is spawned (§7.3, §11.3) ─────────────────────────────────

def test_an_empty_body_is_refused_rather_than_spawning_a_run():
    with pytest.raises(upload.UploadRefused) as refusal:
        upload.check_upload("empty.pdf", b"", 0)

    assert refusal.value.code == "empty_upload"
    assert refusal.value.http_status == 400


def test_a_file_that_is_not_a_pdf_is_refused_on_its_own_bytes_not_its_header():
    """The Content-Type is the uploader's claim; ``%PDF-`` is the file's own.

    A JPEG that reaches PyMuPDF fails from inside the child, minutes later, with the caller
    already holding a 202 — so this is 415 at the boundary instead.
    """
    with pytest.raises(upload.UploadRefused) as refusal:
        upload.check_upload("actually.jpg", b"\xff\xd8\xff\xe0JFIF", 1024)

    assert refusal.value.code == "not_a_pdf"
    assert refusal.value.http_status == 415
    assert refusal.value.details["magic"].startswith("ffd8")


def test_an_upload_over_the_spool_bound_is_refused_with_the_bound_named():
    with pytest.raises(upload.UploadRefused) as refusal:
        upload.check_upload("huge.pdf", PDF, upload.MAX_UPLOAD_BYTES + 1)

    assert refusal.value.code == "upload_too_large"
    assert refusal.value.http_status == 413
    assert refusal.value.details["limit"] == upload.MAX_UPLOAD_BYTES


def test_a_pdf_at_the_bound_is_accepted():
    """The bound is on the spool, not a statement about the document: `inline_cap` handles size."""
    upload.check_upload("big.pdf", PDF, upload.MAX_UPLOAD_BYTES)


def test_every_refusal_carries_the_typed_envelope_the_rest_of_the_surface_uses():
    refusal = upload.UploadRefused("not_a_pdf", "nope", status=415, magic="ffd8")

    assert refusal.to_payload() == {"error": "not_a_pdf", "detail": "nope", "magic": "ffd8"}


# ── the spend switch: where VSIR_ALLOW_PAID finally decides something ────────────────────────────

def test_replay_mode_needs_no_spend_switch_at_all(cfg):
    """`stub` replays a fixture and a miss is a typed `fixture_miss`, never a live call (D10)."""
    upload.check_spend_allowed(cfg)


def test_a_live_model_is_refused_unless_the_release_permits_spending(cfg):
    """The defect this closes: ``VSIR_ALLOW_PAID`` was parsed into `Config` and read by nothing.

    Three lines in `config.py` were its only appearances in the backend, so the only real brake was
    a shell check in `scripts/test-paid.sh` and `--vlm gemini` billed regardless. An upload
    endpoint is the worst possible place for that to stay true, because it moves the spend decision
    to anyone who can reach the port.
    """
    with pytest.raises(upload.UploadRefused) as refusal:
        upload.check_spend_allowed(dataclasses.replace(cfg, vlm="gemini"))

    assert refusal.value.code == "spend_not_permitted"
    assert refusal.value.http_status == 403
    assert refusal.value.details["vlm"] == "gemini"


def test_a_live_model_is_allowed_once_the_release_says_so(cfg):
    upload.check_spend_allowed(dataclasses.replace(cfg, vlm="gemini", allow_paid=True))


def test_the_spend_switch_reads_the_effective_backend_not_the_configured_one(cfg):
    """A request may override `VSIR_VLM`, so the check has to run against what the child resolves.

    Reading `cfg.vlm` alone would let ``vlm=gemini`` on the form bypass a replay-mode release.
    """
    with pytest.raises(upload.UploadRefused) as refusal:
        upload.accept(cfg, filename="d.pdf", body=PDF, vlm="gemini")

    assert refusal.value.code == "spend_not_permitted"


# ── the argv: the claim that this route is a transport (§15 Factor XII) ──────────────────────────

def test_the_route_runs_the_operators_own_subcommand():
    """One implementation of ingestion, reached two ways — never two implementations.

    §15 Factor XII: *"a corrective action that cannot be expressed as a `vsir` subcommand is not a
    supported operation."* The argv is asserted rather than the behaviour, because the behaviour is
    `vsir ingest`'s and is already covered by every other ingest test.
    """
    argv = upload.command(Path("/spool/r.pdf"), run_id="RUN1", until="publish",
                          declared={"doc_id": "TC1E-SF", "revision": "1.3", "subjects": "C24"})

    assert argv[1:5] == ["-m", "vsir", "ingest", "/spool/r.pdf"]
    assert argv[5:9] == ["--until", "publish", "--run-id", "RUN1"]
    assert "--doc-id" in argv and argv[argv.index("--doc-id") + 1] == "TC1E-SF"
    assert "--revision" in argv and argv[argv.index("--revision") + 1] == "1.3"
    assert "--subjects" in argv and argv[argv.index("--subjects") + 1] == "C24"


def test_the_run_id_is_passed_as_run_id_and_never_as_resume():
    """`--resume` continues a run that exists and refuses `run_not_found` if it does not.

    Using it to *start* one answered 202 with a run_id that was never written to `vsir_runs`, so
    the caller polled a 404 forever. The distinction is the reason `--run-id` exists.
    """
    argv = upload.command(Path("/spool/r.pdf"), run_id="RUN1", until="probe", declared={})

    assert "--run-id" in argv
    assert "--resume" not in argv


def test_a_declared_facet_that_was_not_supplied_is_not_passed_as_an_empty_flag():
    """An empty `--doc-id ''` is not the same as no `--doc-id`: §6.1 step 01 derives it instead."""
    argv = upload.command(Path("/spool/r.pdf"), run_id="R", until="publish",
                          declared={"doc_id": "", "revision": None, "tags": "x"})

    assert "--doc-id" not in argv and "--revision" not in argv
    assert argv[argv.index("--tags") + 1] == "x"


def test_a_filename_is_never_interpolated_into_a_shell_string():
    """The argv is a list, so a hostile filename is an argument and not a command."""
    argv = upload.command(Path("/spool/a b; rm -rf /.pdf"), run_id="R", until="publish",
                          declared={})

    assert argv[4] == "/spool/a b; rm -rf /.pdf"
    assert all(";" not in part for part in argv if part != "/spool/a b; rm -rf /.pdf")


def test_an_unknown_step_is_refused_with_the_real_list(cfg):
    with pytest.raises(upload.UploadRefused) as refusal:
        upload.accept(cfg, filename="d.pdf", body=PDF, until="nonsense")

    assert refusal.value.code == "unknown_step"
    assert refusal.value.details["until"] == "nonsense"


def test_an_unknown_vlm_backend_is_refused(cfg):
    with pytest.raises(upload.UploadRefused) as refusal:
        upload.accept(cfg, filename="d.pdf", body=PDF, vlm="gpt")

    assert refusal.value.code == "unknown_vlm"


def test_the_steps_this_route_accepts_are_the_pipelines_own():
    """Two lists that must not drift: the route's and §6.1's."""
    from vsir.cli import INGEST_STEPS

    assert upload.INGEST_UNTIL == INGEST_STEPS


# ── the replay directory: a request-time property, refused at request time ──────────────────────

def test_a_relative_replay_directory_is_resolved_rather_than_passed_through(tmp_path, monkeypatch):
    """The child's working directory is the server's, not the caller's, so relative is a trap."""
    (tmp_path / "fx").mkdir()
    monkeypatch.chdir(tmp_path)

    assert upload.check_fixture("fx", vlm="stub") == str(tmp_path.resolve() / "fx")


def test_a_missing_replay_directory_is_refused_at_the_boundary_not_at_step_four():
    """§6.9's control plane starts at step 09, so a step-04 death leaves nothing to poll.

    That made a bad fixture path a ``202`` followed by a permanent ``404`` — the caller holding a
    run_id that would never exist, with the reason only in the server's log.
    """
    with pytest.raises(upload.UploadRefused) as refusal:
        upload.check_fixture("/tmp/not-a-fixture-directory-at-all", vlm="stub")

    assert refusal.value.code == "fixture_not_found"
    assert refusal.value.http_status == 400
    # The absolute path it actually tried, which is the point of reporting it — and not necessarily
    # the string given: `resolve()` follows symlinks, so on macOS `/tmp` reads back `/private/tmp`.
    resolved = refusal.value.details["resolved"]
    assert resolved.startswith("/") and resolved.endswith("not-a-fixture-directory-at-all")


def test_replay_mode_with_no_fixture_at_all_is_refused_with_the_reason():
    with pytest.raises(upload.UploadRefused) as refusal:
        upload.check_fixture("", vlm="stub")

    assert refusal.value.code == "fixture_required"


def test_a_live_release_may_have_no_fixture(tmp_path):
    """`gemini` calls the model; a fixture is where ``--record`` would write, and is optional."""
    assert upload.check_fixture("", vlm="gemini") == ""
    assert upload.check_fixture(str(tmp_path), vlm="gemini") == str(tmp_path.resolve())


def test_a_live_run_inherits_no_fixture_from_the_release(cfg, monkeypatch, tmp_path):
    """`VSIR_FIXTURE` is also where `cli.py` reads the run's acceptance table from.

    For a replay that is one directory describing one corpus and both meanings agree. For a live
    ingest of an arbitrary uploaded PDF neither applies — and inheriting it meant every upload was
    checked against **another document's** expectations: a 4-page datasheet failed the synthetic
    corpus's label offset and its crop trap on page 20, surfacing as
    `page_out_of_range: page 20 is outside 1..4`. The document was fine; the table was not about it.
    """
    spawned: dict = {}
    monkeypatch.setattr(upload, "_spawn", lambda *a, **k: spawned.update(k) or _Child())

    live = dataclasses.replace(cfg, vlm="gemini", allow_paid=True,
                               fixture_dir="/srv/data/fixtures/synthetic_3window")
    upload.accept(live, filename="d.pdf", body=PDF, spool=tmp_path)

    assert "VSIR_FIXTURE" not in spawned["env"], (
        "a live run must not be handed the release's replay directory, because cli.py would then "
        "check an uploaded document against that corpus's acceptance table")


def test_not_passing_a_fixture_removes_an_inherited_one(cfg):
    """"Do not pass it" cannot be expressed by not writing the key.

    `child_env` starts as a copy of this process's environment, and the API container sets
    `VSIR_FIXTURE` for its own replay default — so skipping the write left the inherited value in
    place and the live run went on being checked against the synthetic corpus. It has to be popped.
    """
    inherited = {"VSIR_FIXTURE": "/srv/data/fixtures/synthetic_3window", "PATH": "/usr/bin"}

    child = upload.child_env(dataclasses.replace(cfg, vlm="gemini"), vlm="gemini", fixture="",
                             base=inherited)

    assert "VSIR_FIXTURE" not in child
    assert child["PATH"] == "/usr/bin", "only that one key is removed"


def test_a_replay_run_still_inherits_the_releases_fixture(cfg, monkeypatch, tmp_path):
    """The other half: replay has nowhere else to get its frozen responses from."""
    spawned: dict = {}
    monkeypatch.setattr(upload, "_spawn", lambda *a, **k: spawned.update(k) or _Child())
    monkeypatch.setattr(upload, "check_fixture", lambda fixture, *, vlm: fixture)

    upload.accept(cfg, filename="d.pdf", body=PDF, spool=tmp_path)

    assert spawned["env"]["VSIR_FIXTURE"] == cfg.fixture_dir


def test_the_resolved_fixture_is_what_reaches_the_child_not_the_configured_one(cfg):
    """`check_fixture` already folded in `cfg.fixture_dir`; re-reading it would undo the resolve."""
    child = upload.child_env(cfg, vlm="stub", fixture="/abs/fx", base={})

    assert child["VSIR_FIXTURE"] == "/abs/fx"


# ── the child's environment: this instance's configuration, not the process's ───────────────────

def test_the_child_ingests_into_the_collection_this_instance_serves(cfg):
    """`create_app` takes its environment as an argument, so the child must not read `os.environ`.

    An instance can be pointed at a different Qdrant or collection than the process was launched
    with — that is how the API suite runs — and a child inheriting the process environment would
    ingest into the collection the process was started against while its parent answered about
    another one. The run would report success and land nowhere anyone was looking.
    """
    instance = dataclasses.replace(cfg, qdrant_url="http://localhost:6335",
                                   collection="vsir_pages_test", release_id="test-7")
    stale = {"VSIR_QDRANT_URL": "http://localhost:6333", "VSIR_COLLECTION": "vsir_pages",
             "VSIR_RELEASE_ID": "dev-0", "PATH": "/usr/bin"}

    child = upload.child_env(instance, vlm="", fixture="", base=stale)

    assert child["VSIR_QDRANT_URL"] == "http://localhost:6335"
    assert child["VSIR_COLLECTION"] == "vsir_pages_test"
    assert child["VSIR_RELEASE_ID"] == "test-7"
    assert child["PATH"] == "/usr/bin", "what Config does not carry is still inherited"


def test_the_child_gets_every_variable_the_pipeline_requires(cfg):
    """A child missing one of §15 Factor III's twelve refuses at boot, which is a 202 then nothing."""
    from vsir.config import REQUIRED_ENV

    child = upload.child_env(cfg, vlm="", fixture="", base={})

    assert set(REQUIRED_ENV) <= set(child), sorted(set(REQUIRED_ENV) - set(child))


def test_the_child_gets_every_variable_load_config_reads_not_only_the_required_ones():
    """The guard that would have caught the bug: read the names out of `config.py` itself.

    A hand-written list drifts, and this one did. ``VSIR_RUNS_COLLECTION`` was missing, so a child
    wrote its run record to the default `vsir_runs` while its parent polled the collection it was
    configured for — ``GET /runs/{run_id}`` answered 404 for a run that was publishing perfectly
    well. ``VSIR_EMBED_DIM`` and ``VSIR_EMBED_TEXT_CHARS`` were missing too, and those are worse:
    both feed the §6.6 fingerprint and the D4 composition, where a silent default is a refusal to
    upsert or a vector that does not mean what its neighbours mean.

    An **optional** variable is exactly the dangerous kind, because a missing one does not refuse —
    it takes a default, and the run succeeds against the wrong thing.
    """
    source = Path(config_module.__file__).read_text()
    reads = set(re.findall(r'_(?:optional|require)\(env,\s*"(VSIR_[A-Z_]+)"', source))
    reads |= set(re.findall(r'_require\(env,\s*"(VSIR_[A-Z_]+)"\)', source))

    assert reads, "the regex found no configuration reads — has config.py been restructured?"

    # A fixture is passed because `VSIR_FIXTURE` is legitimately conditional — a `gemini` release
    # may have none — and the question here is coverage, not whether an empty value is written.
    covered = set(upload.child_env(_config(), vlm="", fixture="/abs/fx", base={}))
    missing = sorted(reads - covered)

    assert not missing, (
        f"child_env does not pass {missing}, so a child would silently take the default for each "
        f"instead of this instance's value")


def test_only_the_backend_and_the_fixture_may_be_influenced_by_a_request(cfg):
    """Everything else about the child is the release's, so a caller cannot re-point the index."""
    child = upload.child_env(cfg, vlm="gemini", fixture="data/fixtures/other", base={})

    assert child["VSIR_VLM"] == "gemini"
    assert child["VSIR_FIXTURE"] == "data/fixtures/other"
    assert child["VSIR_VLM_MODEL"] == cfg.vlm_model, "the model id is pinned by the release (F11)"


def test_the_spend_switch_is_passed_on_so_the_child_agrees_with_the_boundary(cfg):
    """The child re-reads it, so the two must not disagree about whether spending is permitted."""
    assert upload.child_env(cfg, vlm="", fixture="", base={})["VSIR_ALLOW_PAID"] == "0"
    permitted = dataclasses.replace(cfg, allow_paid=True)
    assert upload.child_env(permitted, vlm="", fixture="", base={})["VSIR_ALLOW_PAID"] == "1"


# ── the spool ───────────────────────────────────────────────────────────────────────────────────

def test_the_spool_directory_is_created_and_is_configurable(tmp_path):
    target = tmp_path / "nested" / "spool"

    assert upload.spool_dir({upload.SPOOL_ENV: str(target)}) == target
    assert target.is_dir()


def test_an_unset_spool_variable_falls_back_rather_than_refusing_to_start():
    """Not one of §15 Factor III's twelve required variables, by design.

    A release that never takes an upload must not be made unstartable by a variable it does not
    use — `doctor`'s contract is that unsetting any *required* one is a named non-zero exit, and
    adding a thirteenth would change what that means.
    """
    assert upload.spool_dir({}).is_dir()


def test_clearing_the_spool_removes_leftovers_and_reports_how_many(tmp_path):
    """For a start-up sweep: an unclean shutdown leaves a PDF whose run will never resume."""
    for name in ("a.pdf", "b.pdf"):
        (tmp_path / name).write_bytes(PDF)
    (tmp_path / "keep.txt").write_text("not an upload")

    assert upload.clear_spool(tmp_path) == 2
    assert (tmp_path / "keep.txt").is_file()
