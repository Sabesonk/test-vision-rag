"""L0/L1 — the Part A export contract (Spec §6.8, D1, C8) and the fact that it touches no disk.

Two claims, and they fail in different directions.

**The shape is a contract with another team.** `labels.jsonl` is consumed by the knowledge-graph
build, so an added field is a change nobody agreed to and a missing one is a `KeyError` in someone
else's service. The field set is therefore asserted as an **equality** against §6.8's list, not as
a subset — a superset would pass a containment check and still break the contract.

**Nothing is written to the instance's filesystem** (§15 Factor VI). `impl` wrote three files into
`data/exports/{run_id}/` from the CLI path and never from the HTTP path (register **E1**), so a UI
ingest produced nothing at all and what was produced lived on one replica's disk. The replacement
is a generator read out of the index — and "no file is written" is checked twice here, once by AST
over the module and once by a spy over `open` while a real export runs.

Run this unit's slice:
    bash scripts/test-unit.sh -k "gates or export_shape or safety_flag"
"""
from __future__ import annotations

import ast
import builtins
import json
import types
from pathlib import Path

import pytest
from fake_store import FakeStore

from vsir.ingest import export
from vsir.ingest.export import LABEL_FIELDS, OBSERVED_TOKEN_FIELDS, SECTION_FIELDS

MODULE = Path(export.__file__)

#: Every way a module writes to disk. Scanned by name over the AST rather than by grep, so a
#: mention in a docstring cannot fail it and a call cannot hide inside one.
WRITE_CALLS = ("open", "write_text", "write_bytes", "mkdir", "makedirs", "touch", "NamedTemporary"
               "File", "TemporaryFile", "unlink", "rename", "replace", "copy", "copyfile")


@pytest.fixture(scope="module")
def payloads(stitched) -> list[dict]:
    """The M2a corpus as it sits in the index: 42 payloads, all of one run."""
    return [record.model_copy(update={"run_id": "R1"}).to_payload() for record in stitched.pages]


@pytest.fixture(scope="module")
def store(payloads) -> FakeStore:
    return FakeStore(payloads)


@pytest.fixture(scope="module")
def lines(store) -> list[dict]:
    return [json.loads(line) for line in
            export.labels(store, "pages", run_id="R1", doc_id="synthetic-3window",
                          revision="1.0", chunk=16)]


# ── the §6.8 field set, exactly ──────────────────────────────────────────────────────────────────

#: §6.8's JSON example, transcribed key by key. **The literal is the point.** Asserting a row
#: against `LABEL_FIELDS` alone only proves the export agrees with its own constant: deleting a key
#: from both leaves that check green and takes the field off Part A's wire in silence. This tuple
#: is the independent copy, so the two have to be edited together and the spec is what the suite
#: compares against.
SPEC_6_8_FIELDS: tuple[str, ...] = (
    "page_id", "doc_id", "revision", "page_no", "printed_page_no", "label_verified", "sections",
    "summaries", "codes_in_text", "grounded_rate", "safety_flag", "vlm_model", "prompt_version",
    "dpi",
)


def test_the_exported_field_set_is_the_one_6_8_declares():
    """AC-013 — the constant `label_row` is built from, against §6.8 rather than against itself."""
    assert LABEL_FIELDS == SPEC_6_8_FIELDS


def test_every_line_carries_exactly_the_fields_of_6_8(lines):
    """AC: `page_id`, `doc_id`, `revision`, `page_no`, `printed_page_no`, `label_verified`,
    `sections[]`, `summaries[]`, `codes_in_text[]`, `grounded_rate`, `safety_flag`, `vlm_model`,
    `prompt_version`, `dpi` — an equality, so an extra field fails too."""
    assert lines
    for row in lines:
        assert sorted(row) == sorted(SPEC_6_8_FIELDS)


def test_a_summary_row_carries_the_two_fields_part_a_renders(lines):
    """`summaries[]` read by the literal key, the way the section test reads `page_range`.

    The other four fields AC-013 names are each pinned by a test that indexes them directly;
    `summaries` was pinned only by the field-set comparison, which was self-referential. A page
    that summarised nothing is fine — `summaries` is `[]` on a page with no S2 summary — so the
    assertion is over the pages that have one.
    """
    summarised = [row for row in lines if row["summaries"]]

    assert summarised, "the M2a corpus must carry at least one summary, or this proves nothing"
    for row in summarised:
        for summary in row["summaries"]:
            assert sorted(summary) == ["lang", "text"]
            assert summary["text"]


def test_a_section_row_carries_the_four_fields_the_graph_build_joins_on(lines):
    """`section_id`, `title`, `page_range`, `series_id`. The last is what makes a scope survive a
    revision boundary (§5.1, F8), so an export without it strands every saved citation at M8."""
    sectioned = [row for row in lines if row["sections"]]

    assert sectioned
    for row in sectioned:
        for section in row["sections"]:
            assert sorted(section) == sorted(SECTION_FIELDS)
            assert section["section_id"] and section["series_id"]
            assert len(section["page_range"]) == 2


def test_one_line_per_page_in_page_order(lines, payloads):
    """The order is total and stable so a consumer diffing two exports sees changes, not a
    re-shuffle. The chunking is a `page_no` range for exactly that reason."""
    assert len(lines) == len(payloads)
    assert [row["page_no"] for row in lines] == list(range(1, len(payloads) + 1))


def test_codes_in_text_is_the_old_verified_identifiers_field(lines):
    """C8 — the same contract item, computed structurally from what the page prints rather than
    decided by the allowlist gate that is struck (§2.4)."""
    with_codes = [row for row in lines if row["codes_in_text"]]

    assert with_codes
    for row in with_codes:
        assert row["codes_in_text"] == sorted(set(row["codes_in_text"]))
        assert all(code == code.lower() for code in row["codes_in_text"])


def test_grounded_rate_stays_none_on_a_page_with_no_text_layer(lines):
    """§5.7 carried into the contract: Part A can tell "nothing was claimed" from "nothing checked
    out". A 0.0 there would say the extraction failed on a page that has nothing to extract."""
    scanned = [row for row in lines if row["page_no"] in (1, 2)]

    assert len(scanned) == 2
    assert all(row["grounded_rate"] is None for row in scanned)
    assert all(row["grounded_rate"] is not None for row in lines if row["page_no"] > 2)


def test_the_export_is_a_generator_and_not_a_materialised_document(store):
    """A 1,440-page manual's export must cost one chunk of memory, not the whole file."""
    stream = export.labels(store, "pages", run_id="R1")

    assert isinstance(stream, types.GeneratorType)
    assert json.loads(next(stream))["page_no"] == 1


def test_every_line_is_one_json_object_terminated_by_a_newline(store):
    """NDJSON, which is what a `.jsonl` is: a consumer streams it line by line."""
    raw = list(export.labels(store, "pages", run_id="R1", chunk=16))

    assert all(line.endswith("\n") and line.count("\n") == 1 for line in raw)
    assert all(isinstance(json.loads(line), dict) for line in raw)


def test_a_run_with_no_pages_exports_no_lines_rather_than_an_empty_object(store):
    """An export of nothing is zero lines. A single empty object would be a page that does not
    exist, handed to a graph build as though it did."""
    assert list(export.labels(store, "pages", run_id="a-run-that-never-wrote-a-point")) == []


# ── observed_tokens.jsonl — one line per document (§6.8, C7) ─────────────────────────────────────

def test_the_observed_token_export_is_one_line_per_document():
    """The inventory that backs `present_instead`, exported so Part A's answer policy can see
    which code-like tokens a document's text layer actually carries."""
    control = FakeStore([
        {"kind": "observed_tokens", "doc_id": "B", "revision": "1.0", "run_id": "R1",
         "tokens": ["k158", "q25"], "token_count": 2, "pages": 40},
        {"kind": "observed_tokens", "doc_id": "A", "revision": "1.3", "run_id": "R0",
         "tokens": ["b221"], "token_count": 1, "pages": 12},
        {"kind": "run", "doc_id": "A", "run_id": "R0"},
    ])

    rows = [json.loads(line) for line in export.observed_tokens(control, "runs")]

    assert [row["doc_id"] for row in rows] == ["A", "B"]
    assert all(sorted(row) == sorted(OBSERVED_TOKEN_FIELDS) for row in rows)
    assert rows[1]["tokens"] == ["k158", "q25"]


# ── withheld.jsonl is gone, and asking for it is a typed refusal (§2.4, §2.5 B) ─────────────────

def test_the_third_file_impl_wrote_is_not_an_export(store):
    """`withheld.jsonl` listed what the allowlist gate refused, and the gate is struck — there is
    no withholding left to report. It survives only as a frozen M2b parity artefact (U012)."""
    from vsir.ingest.run import RunRecord

    record = RunRecord(run_id="R1", doc_id="synthetic-3window", revision="1.0")
    with pytest.raises(export.ExportRefused) as refusal:
        export.stream(store, artefact="withheld", collection="pages", runs_collection="runs",
                      record=record)

    assert refusal.value.details["exports"] == ["labels", "observed_tokens"]
    assert refusal.value.code == "export_refused"


def test_exactly_two_artefacts_are_defined():
    assert export.EXPORTS == ("labels", "observed_tokens")


# ── nothing reaches the filesystem (§15 Factor VI, register E1) ──────────────────────────────────

def test_the_export_module_contains_no_filesystem_write_at_all():
    """AC, half one: an AST scan finds no write call in the module that produces the artefacts."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    called = {node.func.attr if isinstance(node.func, ast.Attribute) else
              getattr(node.func, "id", "")
              for node in ast.walk(tree) if isinstance(node, ast.Call)}

    assert not called & set(WRITE_CALLS), f"export.py calls {sorted(called & set(WRITE_CALLS))}"

    imported = {node.module.split(".")[0] for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module}
    imported |= {alias.name.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.Import) for alias in node.names}
    assert not imported & {"pathlib", "os", "shutil", "tempfile"}, (
        f"export.py imports {sorted(imported & {'pathlib', 'os', 'shutil', 'tempfile'})} — the "
        f"artefacts are generated from the index and streamed, so the module has no reason to "
        f"know what a path is (§15 Factor VI)")


def test_no_file_is_written_while_a_whole_document_is_exported(store, monkeypatch, tmp_path):
    """AC, half two: a spy over `open` during a real export of all 42 pages sees no write.

    The AST scan alone would miss a write reached through a helper; this one runs the code. Reads
    stay allowed — a module that could not import would prove nothing — so the spy fails only on a
    mode that creates or truncates.
    """
    opened: list[str] = []
    real_open = builtins.open

    def spy(file, mode="r", *args, **kwargs):
        if any(flag in str(mode) for flag in ("w", "a", "x", "+")):
            opened.append(f"{file}:{mode}")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.chdir(tmp_path)

    rows = list(export.labels(store, "pages", run_id="R1", chunk=8))
    rows += list(export.observed_tokens(FakeStore([]), "runs"))

    assert len(rows) == 42
    assert opened == []
    assert list(tmp_path.iterdir()) == []
