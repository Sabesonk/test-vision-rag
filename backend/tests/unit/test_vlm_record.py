"""L0/L1 — the recorder that turns one paid ingest into a permanent fixture (§12.1, D10 · U013).

`vlm/cache.py::write` names two callers: the M2a corpus generator, and *"the one paid ingest at
M2b"*. Only the first existed, so `data/fixtures/TC1E-SF/raw_window_*.json` — the artefact §12.1's
whole economics rest on — had no producer. This suite covers the second.

The property that matters is not that it writes a file. It is that **what it writes replays**: the
same key, the same bytes, the same `finish_reason`, so a level running against the frozen fixture
sees exactly what the billed call returned. The last test in this file proves that end to end by
recording the M2a corpus through the stub and comparing the result to the fixture it came from,
byte for byte — a round trip the recorder cannot pass by writing anything of its own.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vsir.ingest import probe as probe_module
from vsir.vlm import cache as vlm_cache
from vsir.vlm import record as record_module
from vsir.vlm.cache import Entry, FixtureStore
from vsir.vlm.client import Request

BODY = '{"pages": [{"page_index": 1, "codes": ["SF 1.1A"]}]}'


class _Fake:
    """A backend that answers from a script and counts what it was asked."""

    name = "fake"

    def __init__(self, *entries: Entry | Exception) -> None:
        self.scripted = list(entries)
        self.calls: list[Request] = []

    def generate(self, request: Request) -> Entry:
        self.calls.append(request)
        answer = self.scripted.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _entry(key: str, body: str = BODY, **kwargs) -> Entry:
    return Entry(key=key, namespace=vlm_cache.EXTRACT, body=body, origin="model", **kwargs)


def _request(key: str, namespace: str = vlm_cache.EXTRACT) -> Request:
    from vsir.ingest.extract import WindowOut

    return Request(namespace=namespace, key=key, stage="s2", schema=WindowOut,
                   images=(b"raster",), label="S2 1-30")


# ── it never answers, and never edits ───────────────────────────────────────────────────────────

def test_the_recorder_returns_the_wrapped_backend_s_entry_unchanged(tmp_path: Path):
    """A recorder that could substitute a body would make the fixture a statement about itself."""
    answer = _entry("k1")
    recorder = record_module.recording(_Fake(answer), tmp_path)

    returned = recorder.generate(_request("k1"))

    assert returned is answer
    assert [request.key for request in recorder.inner.calls] == ["k1"]


def test_the_body_is_frozen_byte_for_byte_under_the_call_s_own_key(tmp_path: Path):
    """§6.3 — replay selects by key, so a recording under any other name is unreplayable."""
    body = '{"pages": [{"page_index": 1, "codes": ["SF 1.1A", "K 158"]}]}\n'
    recorder = record_module.recording(_Fake(_entry("abc123", body)), tmp_path)

    returned = recorder.generate(_request("abc123"))

    frozen = FixtureStore(tmp_path).path(vlm_cache.EXTRACT, "abc123")
    assert frozen.read_text(encoding="utf-8") == body == returned.body


def test_the_recording_replays_with_the_same_finish_reason_and_usage(tmp_path: Path):
    """The register B1 sidecar: a truncation has to replay as a truncation, not a parse error."""
    usage = {"input_tokens": 4096, "output_tokens": 8192}
    recorder = record_module.recording(
        _Fake(_entry("k2", finish_reason="MAX_TOKENS", usage=usage)), tmp_path)

    recorder.generate(_request("k2"))

    replayed = FixtureStore(tmp_path).get(vlm_cache.EXTRACT, "k2")
    assert replayed.body == BODY
    assert replayed.finish_reason == "MAX_TOKENS"
    assert replayed.truncated is True
    assert replayed.usage == usage
    assert replayed.origin == "replay"


def test_the_sidecar_names_the_stage_the_label_and_the_image_count(tmp_path: Path):
    """A bare `{"pages": [...]}` file is unattributable — which is the orphan register B1 names."""
    recorder = record_module.recording(_Fake(_entry("k3")), tmp_path)

    recorder.generate(_request("k3"))

    meta = json.loads(
        FixtureStore(tmp_path).meta_path(vlm_cache.EXTRACT, "k3").read_text(encoding="utf-8"))
    assert meta["stage"] == "s2"
    assert meta["label"] == "S2 1-30"
    assert meta["images"] == 1
    assert meta["origin"] == "model"
    assert meta["bytes"] == len(BODY)


# ── it records what the pipeline accepted, and only that ────────────────────────────────────────

def test_a_call_that_raised_freezes_nothing(tmp_path: Path):
    """A truncation is bisected and re-billed into a key of its own (§6.2); the partial window
    must not be sitting in the fixture under the key the repaired one will not use."""
    failure = vlm_cache.VlmTruncated("cut off", cache_key="k4",
                                     namespace=vlm_cache.EXTRACT, finish_reason="MAX_TOKENS")
    recorder = record_module.recording(_Fake(failure), tmp_path)

    with pytest.raises(vlm_cache.VlmTruncated):
        recorder.generate(_request("k4"))

    assert recorder.recorded == []
    assert list(tmp_path.rglob("*.json")) == []


def test_each_half_of_a_bisected_window_is_its_own_receipt(tmp_path: Path):
    """Wrapping the boundary catches every call, which is why it is not wired per step."""
    recorder = record_module.recording(_Fake(_entry("left"), _entry("right")), tmp_path)

    recorder.generate(_request("left"))
    recorder.generate(_request("right"))

    assert [path.stem for path in recorder.recorded] == ["left", "right"]


def test_the_s1_and_s2_namespaces_are_kept_apart(tmp_path: Path):
    """One key space per namespace: `facts/` and `extract/` are different questions."""
    recorder = record_module.recording(
        _Fake(Entry(key="k5", namespace=vlm_cache.FACTS, body="{}", origin="model")), tmp_path)

    recorder.generate(_request("k5", namespace=vlm_cache.FACTS))

    assert (tmp_path / vlm_cache.FACTS / "k5.json").is_file()
    assert not (tmp_path / vlm_cache.EXTRACT / "k5.json").exists()


def test_the_recorder_reports_the_wrapped_backend_s_name(tmp_path: Path):
    """It is not a backend anybody selects — `VSIR_VLM` still names what answered (§15 Factor X)."""
    recorder = record_module.recording(_Fake(_entry("k6")), tmp_path)

    assert recorder.name == "fake"


# ── §12.1's text.json ───────────────────────────────────────────────────────────────────────────

def test_freeze_text_writes_every_page_with_the_extractor_that_produced_it(tmp_path: Path,
                                                                          synthetic_pdf: Path):
    probed = probe_module.run(synthetic_pdf)

    written = record_module.freeze_text(tmp_path, probed)

    frozen = json.loads(written.read_text(encoding="utf-8"))
    assert frozen["probe_version"] == probed.probe_version
    assert frozen["content_hash"] == probed.content_hash
    assert frozen["page_count"] == probed.page_count == len(frozen["pages"])
    assert [page["page_no"] for page in frozen["pages"]] == list(range(1, probed.page_count + 1))
    assert [page["text"] for page in frozen["pages"]] == list(probed.texts)


def test_freeze_text_creates_the_directory_it_is_pointed_at(tmp_path: Path, synthetic_pdf: Path):
    written = record_module.freeze_text(tmp_path / "new" / "fixture", probe_module.run(synthetic_pdf))

    assert written.is_file()


# ── the round trip: what it records is what replay reads ────────────────────────────────────────

def test_recording_the_m2a_corpus_reproduces_its_fixture_byte_for_byte(tmp_path: Path,
                                                                       synthetic_pdf: Path,
                                                                       synthetic_fixture: Path,
                                                                       synthetic_config):
    """The whole claim, end to end: replay the frozen corpus through the recorder and the bytes
    that come out are the bytes that went in, under the same keys.

    A recorder that wrote its own rendering of a response would pass every test above this one and
    fail this one — which is why it is here and why it compares files rather than parsed objects.
    """
    from vsir.ingest import extract as extract_module
    from vsir.ingest import window as window_module
    from vsir.vlm import backend as vlm_backend

    cfg = synthetic_config
    probed = probe_module.run(synthetic_pdf)
    recorder = record_module.recording(vlm_backend(cfg), tmp_path)
    facts, _ = extract_module.document_facts(
        recorder, source=synthetic_pdf, probed=probed, vlm_model=cfg.vlm_model,
        prompt_version=cfg.prompt_version, dpi=220)
    plan = window_module.plan(probed.page_count, toc=facts.toc, size_bytes=probed.size_bytes,
                              document="synthetic-3window")
    extract_module.extract(recorder, source=synthetic_pdf, plan=plan, probed=probed,
                           vlm_model=cfg.vlm_model, prompt_version=cfg.prompt_version, dpi=220)
    record_module.freeze_text(tmp_path, probed)

    recorded = sorted(path.relative_to(tmp_path).as_posix()
                      for path in tmp_path.rglob("*.json") if not path.name.endswith(".meta.json"))
    assert recorded == ["extract/" + key + ".json" for key in sorted(
        path.stem for path in (synthetic_fixture / "extract").glob("*.json")
        if not path.name.endswith(".meta.json"))] + ["facts/" + key + ".json" for key in sorted(
        path.stem for path in (synthetic_fixture / "facts").glob("*.json")
        if not path.name.endswith(".meta.json"))] + ["text.json"]
    for relative in recorded:
        if relative == "text.json":
            continue
        assert (tmp_path / relative).read_bytes() == (synthetic_fixture / relative).read_bytes(), \
            relative
