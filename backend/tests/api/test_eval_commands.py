"""L2/L3 — `vsir eval acceptance` and `vsir eval abstention`, the shipped commands (plan U016).

Three suites already assert §12.3's table and §12.4's eval as *library behaviour*:
`test_acceptance_synthetic.py`, `test_parity_lookup.py` / `test_withheld_negative_set.py`, and
`test_near_miss_codes_never_answer.py`. This file asserts the **commands** — the surface §4.4
requires, the one a reviewer actually runs — and only the properties that are the command's own:

* it prints one row per assertion, with the expectation beside the measurement;
* it exits 0 when the corpus is right and non-zero when a row fails;
* a row it cannot run yet is a named `SKIP` that neither fails the command nor hides;
* it reaches no model, and it does not change the index it read.

The commands run **in this process** through :func:`vsir.cli.main`, against the L2 Qdrant and with
the configuration in ``BASE_ENV``. In-process rather than through a subprocess because the exit
code, the printed report and the JSON event line are all part of the contract and all three are
observable here — and because a subprocess would inherit whatever is in the developer's shell,
which is the one thing a test about configuration must not do.
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import os
import socket
from pathlib import Path
from typing import Iterator

import pytest
from qdrant_client import QdrantClient

from vsir import cli
from vsir.core.nearmiss import NearMiss
from vsir.eval import abstention, acceptance, legacy, synthetic

REPO = Path(__file__).resolve().parents[3]
EMBED_DIM = 1536

#: The command's own namespace. `VSIR_COLLECTION` is deliberately not `vsir_pages`: these suites
#: run beside `test_acceptance_synthetic.py`, which seeds `vsir_pages_acceptance_synthetic_1536`,
#: and two suites sharing an ephemeral collection would drop it out from under each other.
COLLECTION = "vsir_pages_evalcmd"
RUNS = "vsir_runs_evalcmd"

BASE_ENV = {
    "VSIR_PORT": "8000", "VSIR_COLLECTION": COLLECTION, "VSIR_RUNS_COLLECTION": RUNS,
    "VSIR_VLM": "stub", "VSIR_VLM_MODEL": "gemini-3.8-flash-001",
    "VSIR_EMBED_MODEL": "gemini-embedding-2", "VSIR_PROMPT_VERSION": "s2-v1",
    "VSIR_API_TOKENS": "test-only-not-a-credential", "VSIR_READ_QUOTA": "10",
    "VSIR_ALLOW_PAID": "0", "VSIR_LOG_LEVEL": "INFO", "VSIR_RELEASE_ID": "test-0",
}

#: Every collection either command may create, so the fixtures can prove they were all dropped.
EPHEMERAL = (
    synthetic.synthetic_collection(f"{COLLECTION}_{acceptance.EPHEMERAL}", EMBED_DIM),
    legacy.legacy_collection(f"{COLLECTION}_{acceptance.EPHEMERAL}", EMBED_DIM),
    synthetic.synthetic_collection(f"{COLLECTION}_{abstention.EPHEMERAL}", EMBED_DIM),
)


def qdrant_url() -> str:
    return os.environ.get("VSIR_TEST_QDRANT_URL", "http://localhost:6335")


@pytest.fixture
def clean(qdrant: QdrantClient) -> Iterator[QdrantClient]:
    """No leftover ephemeral collection on the way in, and none on the way out."""
    def drop() -> None:
        for name in EPHEMERAL:
            if qdrant.collection_exists(name):
                qdrant.delete_collection(name)

    drop()
    try:
        yield qdrant
    finally:
        drop()


@pytest.fixture
def run(monkeypatch, clean):
    """`vsir eval …` in this process, configured for the L2 stack. Returns the exit code."""
    for name, value in {**BASE_ENV, "VSIR_QDRANT_URL": qdrant_url()}.items():
        monkeypatch.setenv(name, value)
    # OQ-2's credential and the provider's own variable, both removed: an eval that could reach a
    # model must not be able to find a key even by accident (§12.2, D10).
    for name in ("VSIR_VLM_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    def _run(*arguments: str) -> int:
        return cli.main(["eval", *arguments])

    return _run


def rows_of(output: str, verdict: str) -> list[str]:
    """The report's rows carrying ``verdict``, as printed."""
    return [line for line in output.splitlines() if line.rstrip().endswith(verdict)]


def columns(line: str) -> tuple[str, str, str]:
    """One printed row split back into `(assertion, expected, observed)`.

    Slicing at the module's own widths rather than on whitespace: the point of the assertion these
    feed is that the *expectation* and the *measurement* are in two separate columns, and a
    whitespace split cannot tell one padded column from two.
    """
    body = line[2:]
    assertion = body[:acceptance.ASSERTION_WIDTH]
    rest = body[acceptance.ASSERTION_WIDTH + 1:]
    return (assertion.strip(), rest[:acceptance.VALUE_WIDTH].strip(),
            rest[acceptance.VALUE_WIDTH + 1:acceptance.VALUE_WIDTH * 2 + 1].strip())


@pytest.fixture(scope="module")
def parity_output(qdrant: QdrantClient) -> str:
    """`vsir eval acceptance --only parity`, run once for the whole module.

    The section is 660 index reads over 405 identifiers, 96 withheld codes and 63 gains — a few
    seconds, and four assertions below are about one report rather than four. Module-scoped for
    that reason alone; nothing here is mutated by a test.
    """
    patch = pytest.MonkeyPatch()
    for name, value in {**BASE_ENV, "VSIR_QDRANT_URL": qdrant_url()}.items():
        patch.setenv(name, value)
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            code = cli.main(["eval", "acceptance", "--only", "parity"])
    finally:
        patch.undo()
    assert code == cli.EXIT_OK, buffer.getvalue()
    return buffer.getvalue()


# ── `vsir eval acceptance` ──────────────────────────────────────────────────────────────────────

def test_the_synthetic_section_passes_and_exits_zero(run, capsys):
    """AC: one row per §12.3 assertion, expected beside actual, exit 0 (§13 M3, "always")."""
    code = run("acceptance", "--only", "synthetic")

    output = capsys.readouterr().out
    assert code == cli.EXIT_OK, output
    assert "acceptance: " in output and ", 0 failed, " in output
    # Every §12.3 label the M1 corpus states is named in the report, so a row that silently
    # stopped being run would change the output rather than only the count.
    corpus = synthetic.load()
    for row in corpus.expected["compact_labels"]:
        assert f'lookup("{row["label"]}")' in output
    assert 'verify("SF 1.1A", [p008])' in output
    assert rows_of(output, "PASS")
    assert not rows_of(output, "FAIL")


def test_every_printed_row_shows_the_expectation_beside_the_measurement(run, capsys):
    """AC: *"an explicit expected-vs-actual"* — the whole reason this is a command and not a dot.

    A row that printed only its verdict would satisfy every other assertion in this file, so the
    two columns are read apart and both must carry text.
    """
    run("acceptance", "--only", "synthetic")

    output = capsys.readouterr().out
    body = [line for line in output.splitlines()
            if line.startswith("  ") and line.rstrip()[-4:] in ("PASS", "FAIL", "SKIP")]
    assert len(body) >= 40
    for line in body:
        assertion, expected, observed = columns(line)
        assert assertion, line
        assert expected, line
        assert observed, line


def test_the_parity_and_negative_rows_appear_in_the_same_output(parity_output):
    """AC: §12.3's PARITY block and the `withheld.jsonl` negative rows, in one report."""
    output = parity_output

    assert "every identifier the old gate accepted is findable by phrase" in output
    assert "every raw in withheld.jsonl is unfindable in `text`" in output
    baseline = legacy.load()
    assert f"{len(baseline.accepted_raws())} of {len(baseline.accepted_raws())}" in output
    assert f"0 of {len(baseline.withheld())} findable" in output
    assert not rows_of(output, "FAIL")


def test_the_gains_section_lists_the_codes_the_old_grammar_dropped(parity_output):
    """AC: *"a **GAINS** section lists codes the old grammar dropped"* — recorded, never failed."""
    output = parity_output

    assert "GAINS —" in output
    # The two §12.3's own acceptance table names, and which the old surface could not return.
    assert "EAO 84-5140.0020" in output
    assert "B&R X20SI4100" in output
    # A gain is a report: it appears in its own section and never as a row with a verdict.
    gains = output.split("GAINS —", 1)[1].split("NO LEGACY COVERAGE", 1)[0]
    assert not rows_of(gains, "FAIL") and not rows_of(gains, "PASS")


def test_the_parity_run_drops_every_collection_it_created(parity_output, qdrant):
    """Create, seed, query, drop — in one process, leaving nothing behind (§15 Factor VI).

    The parity section seeds 142 projected pages. A run that left them would leave a collection
    named after a *superseded* run beside the serving one, which is precisely what
    `legacy_collection`'s own reasoning is about.
    """
    for name in EPHEMERAL:
        assert not qdrant.collection_exists(name), f"{name} was left behind"


def test_the_paths_parity_cannot_cover_are_printed_beside_the_result(parity_output):
    """R7 — a green parity run is not sign-off for the ~70% of §7/§8 `impl` never exercised."""
    output = parity_output

    assert "NO LEGACY COVERAGE" in output
    for line in legacy.NO_LEGACY_COVERAGE:
        assert line in output


def test_the_real_section_skips_by_name_rather_than_failing(run, capsys):
    """Edge case: before M2b the real-text rows must **skip with a named reason**, not fail.

    The plan's risk register names the failure mode this asserts against: *"the 'skip before M2b'
    path becomes a permanent skip nobody notices."* So three things are required and all three are
    checked — the skip names the artefacts, it names the open questions, and the count is in the
    summary line.
    """
    code = run("acceptance", "--only", "real")

    output = capsys.readouterr().out
    assert code == cli.EXIT_OK, output
    missing = [name for name in acceptance.BOUGHT
               if not (REPO / "data" / "fixtures" / "TC1E-SF" / name).is_file()]
    if not missing:                                    # the re-bill has landed; U013 owns the rest
        pytest.skip("the M2b artefacts are present — U013's corpus rows are no longer skipped")
    skipped = rows_of(output, "SKIP")
    assert skipped, "the corpus rows must be listed, not omitted"
    assert "OQ-1" in output and "OQ-2" in output
    for name in missing:
        assert name in output
    assert f", {len(skipped)} skipped" in output
    # The rows that assert the table's own faithfulness to §12.3 run today and must pass.
    assert rows_of(output, "PASS")
    assert not rows_of(output, "FAIL")


def test_a_skipped_row_is_never_counted_as_a_pass(run, capsys):
    """A skip that inflated the pass count would make the summary line a lie."""
    run("acceptance", "--only", "real")

    output = capsys.readouterr().out
    summary = [line for line in output.splitlines() if line.startswith("acceptance: ")][-1]
    passed, failed, skipped = (int(part.split()[0]) for part in summary
                               .removeprefix("acceptance: ").split(", "))
    assert passed == len(rows_of(output, "PASS"))
    assert skipped == len(rows_of(output, "SKIP"))
    assert failed == 0


def test_a_failing_row_makes_the_command_exit_non_zero(run, capsys, monkeypatch):
    """A deliberately broken assertion, and the command must be red. The negative control.

    Without it every green row above could be a report that cannot fail. The break is made where
    a real regression would appear — in what the index answers — by pointing `lookup` at a label
    the corpus does not print, so the row that must find exactly one page finds none.
    """
    real = acceptance.lookup

    def wrong(client, collection, label, **kwargs):
        # One character, which is the whole point: `K159` is not printed anywhere in the corpus.
        return real(client, collection, "K 159" if label == "K 158" else label, **kwargs)

    monkeypatch.setattr(acceptance, "lookup", wrong)

    code = run("acceptance", "--only", "synthetic")

    output = capsys.readouterr().out
    assert code == cli.EXIT_REFUSED
    failures = rows_of(output, "FAIL")
    assert failures, output
    assert any('lookup("K 158")' in line for line in failures)
    assert ", 0 failed, " not in output


def test_a_missing_acceptance_table_says_so_rather_than_asserting_nothing(run, capsys, tmp_path):
    """`--tc1e-fixture` at an empty directory: one skip, naming the file that is not there."""
    code = run("acceptance", "--only", "real", "--tc1e-fixture", str(tmp_path))

    output = capsys.readouterr().out
    assert code == cli.EXIT_OK
    assert rows_of(output, "SKIP") == rows_of(output, "SKIP")[:1]
    assert "expected.json" in output
    assert not rows_of(output, "PASS")


def test_a_missing_corpus_is_a_refusal_and_not_a_green_run(tmp_path):
    """A section that produced no evidence at all is not a pass — C10, one level up.

    Called as a function rather than through the CLI because the state being asserted is
    `Report.ok` being false *with no failing row*: a command whose report is empty must still be
    red, and the distinction between "0 failed" and "nothing ran" only exists on the object.
    """
    report = acceptance.run(None, base=COLLECTION, dim=EMBED_DIM, release_id="test-0",
                            only="synthetic", synthetic_dir=tmp_path / "nowhere")

    assert report.rows == ()
    assert report.failed == 0
    assert not report.ok
    assert report.refusals and "SYNTHETIC" in report.refusals[0]


# ── `vsir eval abstention` ──────────────────────────────────────────────────────────────────────

def test_abstention_correctness_is_one_and_the_command_exits_zero(run, capsys):
    """AC: `abstention_correctness == 1.00` over `near_misses(n=100)`, exit 0 (§12.4, D11)."""
    code = run("abstention")

    output = capsys.readouterr().out
    assert code == cli.EXIT_OK, output
    assert "abstention_correctness: 1.00" in output
    assert "100 fabricated code(s)" in output
    assert "none: 100 of 100 abstained on every surface" in output


def test_the_control_row_is_reported_beside_the_metric(run, capsys):
    """An eval of absences over an empty index would pass every row: the control is what stops it."""
    run("abstention")

    output = capsys.readouterr().out
    assert "CONTROL — the real codes the fakes were mutated from are still findable" in output
    assert "no longer findable" not in output


def test_a_leaking_near_miss_exits_non_zero_and_names_the_case(run, capsys, monkeypatch):
    """AC: *"mutating one near-miss assertion to fail … names the failing case"*.

    The mutation is made at the generator, which is the honest place: it hands the eval a
    "fabricated" code that is really printed (`k158` is on p001), so `lookup` returns a page and
    the eval must call that a leak. Exactly the shape of the injury §12.4 exists to catch — and
    proof that a green run above is a measurement rather than a report that cannot fail.
    """
    real = abstention.near_misses

    def with_a_real_code(inventory, n=100, **kwargs):
        sample = real(inventory, n=n, **kwargs)
        return (NearMiss(source="k158", fake="k158", position=1),) + sample[1:]

    monkeypatch.setattr(abstention, "near_misses", with_a_real_code)

    code = run("abstention")

    output = capsys.readouterr().out
    assert code == cli.EXIT_REFUSED
    assert "k158 → k158" in output
    assert "SYN-M1@1.0#p001" in output
    assert "abstention_correctness: 0.99" in output
    assert "— FAIL" in output


def test_the_metric_is_never_1_00_when_nothing_was_measured(run, capsys):
    """A refusal reports *not measured*, never a perfect score: 0/0 is not abstention."""
    code = run("abstention", "--corpus", "indexed")

    output = capsys.readouterr().out
    assert code == cli.EXIT_REFUSED
    assert "abstention_correctness: not measured" in output
    assert "does not exist" in output


def test_a_multi_document_collection_refuses_rather_than_picking_one(run, capsys, clean):
    """A safety metric measured over an unnamed corpus is not a measurement (§12.4)."""
    baseline = legacy.load()
    collection = legacy.legacy_collection(f"{COLLECTION}_{acceptance.EPHEMERAL}", EMBED_DIM)
    legacy.seed(clean, collection, baseline.records(), dim=EMBED_DIM)

    refused = run("abstention", "--corpus", "indexed", "--collection", collection)
    output = capsys.readouterr().out
    assert refused == cli.EXIT_REFUSED
    assert "--doc-id" in output

    named = run("abstention", "--corpus", "indexed", "--collection", collection,
                "--doc-id", "TC1E-SF")
    output = capsys.readouterr().out
    assert named == cli.EXIT_OK, output
    assert "abstention_correctness: 1.00" in output


# ── the properties both commands must have ──────────────────────────────────────────────────────

def payload_digest(client: QdrantClient, collection: str) -> tuple[int, str]:
    """`(point count, digest of every payload)` — the fingerprint an eval must not move.

    Sorted by point id and dumped with sorted keys, so the digest is a function of the *content*
    and not of the order Qdrant happened to scroll in.
    """
    points, _next = client.scroll(collection_name=collection, limit=4096, with_payload=True,
                                  with_vectors=False)
    ordered = sorted((str(point.id), json.dumps(point.payload, sort_keys=True, default=str))
                     for point in points)
    digest = hashlib.sha256(json.dumps(ordered).encode("utf-8")).hexdigest()
    return client.count(collection, exact=True).count, digest


@pytest.mark.parametrize("arguments", [
    pytest.param(("acceptance", "--only", "synthetic"), id="acceptance"),
    pytest.param(("abstention",), id="abstention"),
    pytest.param(("abstention", "--corpus", "indexed", "--doc-id", "SYN-M1"), id="indexed"),
])
def test_neither_command_mutates_the_index(run, capsys, clean, arguments):
    """AC: *"asserted by a point-count and payload-hash comparison before and after"*.

    The collection compared is the **serving** one — `{VSIR_COLLECTION}_{dim}`, the name a
    deployment answers from — seeded here so there is something real to disturb. `--corpus
    indexed` reads exactly that collection, which is the case worth asserting: it is the one path
    that touches published data at all.
    """
    served = f"{COLLECTION}_{EMBED_DIM}"
    corpus = synthetic.load()
    synthetic.seed(clean, served, corpus.records(release_id="test-0"), dim=EMBED_DIM)
    try:
        before = payload_digest(clean, served)

        run(*arguments)
        capsys.readouterr()

        assert payload_digest(clean, served) == before
        for name in EPHEMERAL:
            assert not clean.collection_exists(name), f"{name} was left behind"
    finally:
        clean.delete_collection(served)


@pytest.mark.parametrize("arguments", [
    pytest.param(("acceptance", "--only", "synthetic"), id="acceptance"),
    pytest.param(("abstention",), id="abstention"),
])
def test_neither_command_makes_an_outbound_call_to_anything_but_the_store(run, capsys, arguments,
                                                                          monkeypatch):
    """AC: *"run with `GEMINI_API_KEY` unset and a network spy records zero outbound calls"*.

    Zero outbound calls *to a model*: both commands read Qdrant, which is a socket, so the spy
    records every address the process connects to and the assertion is that the only host reached
    is the configured store. The credential variables are removed by the `run` fixture, so a
    command that tried would also have nothing to try with.
    """
    seen: list[tuple[str, int]] = []
    real_connect = socket.socket.connect

    def spy(self, address, *rest):
        if isinstance(address, tuple) and len(address) >= 2:
            seen.append((str(address[0]), int(address[1])))
        return real_connect(self, address, *rest)

    monkeypatch.setattr(socket.socket, "connect", spy)

    run(*arguments)
    capsys.readouterr()

    port = int(qdrant_url().rsplit(":", 1)[-1])
    ports = {address[1] for address in seen}
    assert seen, "the spy recorded nothing at all, so it is not watching the right call"
    assert port in ports, seen
    # 443 is where a model lives. Asserted as an exclusion rather than as `ports == {port}`
    # because name resolution can open a socket of its own on some hosts, and a safety assertion
    # that goes red on a resolver change teaches people to ignore it. The import-graph test below
    # is the total version of the same claim.
    assert not ports & {80, 443}, seen


@pytest.mark.parametrize("module", [acceptance, abstention])
def test_no_eval_module_can_reach_a_model_at_all(module):
    """The structural half of the same guarantee: `vsir.vlm` is not in the import graph.

    A runtime spy proves *this* run spent nothing. The import graph proves no run can — which is
    the property §12.2 actually asks for, and the same argument
    `test_the_inventory_is_unreachable_from_lookup` makes about §6.8.
    """
    imports = set()
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    assert not any(name.startswith("vsir.vlm") for name in imports), imports
    assert not any("genai" in name or "google" in name for name in imports), imports


def test_both_commands_are_the_names_4_4_publishes(run, capsys):
    """§4.4's row is `vsir eval acceptance | abstention | corpus`; `corpus` is U026's, at M8.

    A name that is not served yet is a refusal listing what is — argparse's own, which is the CLI
    analogue of the typed 404 `POST /tools/{name}` returns for a tool this release does not have.
    """
    with pytest.raises(SystemExit) as refusal:
        cli.build_parser().parse_args(["eval", "corpus"])

    assert refusal.value.code == 2
    error = capsys.readouterr().err
    assert "acceptance" in error and "abstention" in error


def test_the_abstention_eval_is_registered_in_ci():
    """AC: *"the abstention eval is registered in CI and runs on every commit"* (§12.4).

    Asserted against the workflow rather than trusted: §12.4's *"runs in CI on every commit"* is
    the difference between a guard and a test somebody remembers to run. The triggers are checked
    too — a step is not registered on every commit if the workflow only runs on a tag.
    """
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert workflow.strip(), "the workflow file is empty — CI runs nothing"
    assert "\non:\n  push:\n  pull_request:\n" in workflow
    assert "near_miss or eval_commands" in workflow
    assert "§12.4" in workflow
    # And no credential is offered to any of it: L0-L3 are replay-mode only (D10).
    assert "secrets." not in workflow
