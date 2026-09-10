"""L0/L1 — step 03, page rasters (Spec §6.1, §4.2, register E3/A5).

The assertion this file exists for is that **nothing is written down**. `impl` wrote 110 PNGs and
20.7 MB for one 55-page document, before anything was validated and with nothing to collect them
if the document was later quarantined (E3) — and the stale path it then stored on the record made
`read()` return 503 for every page (A5). §4.2 replaces both with an in-process cache, so a cold
instance returns identical results and only more slowly.
"""
from __future__ import annotations

import builtins
import os
import pathlib
from contextlib import contextmanager

import pytest

from vsir.config import DPI_ANSWER, DPI_INDEX
from vsir.ingest import render
from vsir.serve.caps import ALLOWED_DPI, MAX_FETCH_MEGAPIXELS

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


@contextmanager
def _write_spy(monkeypatch):
    """Record every filesystem write this process attempts, by any Python route.

    Covers the four doors a raster could leave by — `open`, `os.open`, `Path.open` and the
    `Path.write_*` shortcuts — and reports the path, so a failure names the file rather than the
    fact that one exists. A snapshot of the directory tree runs beside it, which is what would
    catch a write made below Python by the C extension.
    """
    written: list[str] = []
    real_open, real_os_open, real_path_open = builtins.open, os.open, pathlib.Path.open

    def spy_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wxa+"):
            written.append(f"open({file!s}, {mode!r})")
        return real_open(file, mode, *args, **kwargs)

    def spy_os_open(path, flags, *args, **kwargs):
        if flags & _WRITE_FLAGS:
            written.append(f"os.open({path!s}, {flags})")
        return real_os_open(path, flags, *args, **kwargs)

    def spy_path_open(self, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wxa+"):
            written.append(f"Path.open({self!s}, {mode!r})")
        return real_path_open(self, mode, *args, **kwargs)

    def refuse_write_bytes(self, data):
        written.append(f"Path.write_bytes({self!s})")
        raise AssertionError(f"a raster was written to {self}")

    def refuse_write_text(self, data, *args, **kwargs):
        written.append(f"Path.write_text({self!s})")
        raise AssertionError(f"a raster was written to {self}")

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(os, "open", spy_os_open)
    monkeypatch.setattr(pathlib.Path, "open", spy_path_open)
    monkeypatch.setattr(pathlib.Path, "write_bytes", refuse_write_bytes)
    monkeypatch.setattr(pathlib.Path, "write_text", refuse_write_text)
    yield written


def _tree(root: pathlib.Path) -> dict[str, int]:
    return {str(path): path.stat().st_size for path in root.rglob("*") if path.is_file()}


def test_no_raster_is_written_to_the_filesystem(monkeypatch, synthetic_pdf, expected, tmp_path):
    """§4.2, §15 Factor VI — rasters are never persisted. Register E3, closed by construction."""
    render.cache_clear()
    data_dir = synthetic_pdf.parent.parent
    before = _tree(data_dir) | _tree(tmp_path)

    monkeypatch.chdir(tmp_path)
    with _write_spy(monkeypatch) as written:
        rasters = render.render_pages(synthetic_pdf, range(1, expected["page_count"] + 1),
                                      dpi=DPI_ANSWER)
        render.render_page(synthetic_pdf, 1, dpi=DPI_INDEX)
        render.render_page(synthetic_pdf, 1, dpi=DPI_ANSWER,
                           region=expected["crop_trap"]["region"])

    assert len(rasters) == expected["page_count"]
    assert all(raster.png.startswith(b"\x89PNG") for raster in rasters)
    assert written == [], f"the renderer wrote to the filesystem: {written}"
    assert _tree(data_dir) | _tree(tmp_path) == before


def test_the_write_spy_would_catch_a_write(monkeypatch, tmp_path):
    """The gate is real: the same spy over a function that does persist a raster fails."""
    monkeypatch.chdir(tmp_path)
    with _write_spy(monkeypatch) as written:
        with open(tmp_path / "p1_220.png", "wb") as handle:
            handle.write(b"\x89PNG")

    assert written and "p1_220.png" in written[0]


def test_the_page_hashes_are_stable_and_ordered(synthetic_pdf, expected):
    """§6.3 — the ordered page image hashes are what `extract_key` is built from."""
    pages = range(1, expected["page_count"] + 1)

    assert list(render.page_hashes(synthetic_pdf, pages, dpi=DPI_ANSWER)) == \
        expected["render"]["page_sha256"]
    assert render.page_hashes(synthetic_pdf, (1, 2)) != render.page_hashes(synthetic_pdf, (2, 1))


def test_a_raster_is_identical_on_every_render(synthetic_pdf):
    render.cache_clear()
    first = render.render_page(synthetic_pdf, 9, dpi=DPI_ANSWER)
    render.cache_clear()
    second = render.render_page(synthetic_pdf, 9, dpi=DPI_ANSWER)

    assert first.sha256 == second.sha256
    assert (first.width, first.height) == (second.width, second.height)


def test_the_cache_serves_the_second_call(synthetic_pdf):
    render.cache_clear()
    render.render_page(synthetic_pdf, 3, dpi=DPI_ANSWER)
    cold = render.cache_info()
    render.render_page(synthetic_pdf, 3, dpi=DPI_ANSWER)
    warm = render.cache_info()

    assert (cold["hits"], cold["misses"]) == (0, 1)
    assert (warm["hits"], warm["misses"]) == (1, 1)
    assert warm["maxsize"] == render.RASTER_CACHE_PAGES


def test_the_cache_is_keyed_on_the_files_content(tmp_path):
    """A cache keyed on a path alone would serve an old page for an edited PDF, forever."""
    import pymupdf

    def write(path: pathlib.Path, marker: str) -> None:
        with pymupdf.open() as doc:
            for _ in range(10):
                doc.new_page(width=200, height=200).insert_text((20, 60), marker, fontsize=12)
            path.write_bytes(doc.tobytes(deflate=True, no_new_id=True))

    document = tmp_path / "revised.pdf"
    write(document, "revision A")
    original = render.render_page(document, 9, dpi=DPI_ANSWER)
    write(document, "revision B is a different document entirely")

    assert render.render_page(document, 9, dpi=DPI_ANSWER).sha256 != original.sha256


def test_the_two_pinned_dpis_are_different_rasters(synthetic_pdf):
    """§4.2 — `dpi_index=150` is what gets embedded; `dpi_answer=220` is what `read` sees."""
    index = render.index_raster(synthetic_pdf, 9)
    answer = render.render_page(synthetic_pdf, 9, dpi=DPI_ANSWER)

    assert index.dpi == DPI_INDEX and answer.dpi == DPI_ANSWER
    assert index.width < answer.width
    assert index.sha256 != answer.sha256


def test_a_region_renders_a_strict_part_of_the_page(synthetic_pdf):
    full = render.render_page(synthetic_pdf, 20, dpi=DPI_ANSWER)
    top = render.render_page(synthetic_pdf, 20, dpi=DPI_ANSWER, region=(0.0, 0.0, 1.0, 0.5))

    assert full.is_full_page and not top.is_full_page
    assert top.height == pytest.approx(full.height / 2, abs=2)
    assert top.width == full.width
    assert top.megapixels < full.megapixels


@pytest.mark.parametrize("region", [
    (0.0, 0.0, 1.0),                 # three values
    (0.0, 0.0, 1.0, 1.5),            # outside 0..1
    (0.5, 0.0, 0.5, 1.0),            # zero width
    (1.0, 0.0, 0.0, 1.0),            # inverted
])
def test_a_malformed_region_is_a_typed_refusal_never_a_clamp(region):
    """§7.3's rule, enforced at the renderer: a clamped region returns the wrong pixels quietly."""
    with pytest.raises(render.RenderError) as refusal:
        render.normalise_region(region)

    assert refusal.value.code == "region_invalid"


def test_a_page_outside_the_document_is_a_typed_refusal(synthetic_pdf, expected):
    with pytest.raises(render.RenderError) as refusal:
        render.render_page(synthetic_pdf, expected["page_count"] + 1, dpi=DPI_ANSWER)

    assert refusal.value.code == "page_out_of_range"
    assert refusal.value.details["page_count"] == expected["page_count"]


# ── the size of a raster, before it exists (§7.3's megapixel bound, U018) ───────────────────────

@pytest.mark.parametrize("dpi", ALLOWED_DPI)
def test_the_predicted_size_is_the_rendered_size_at_every_allowed_dpi(synthetic_pdf, dpi):
    """§7.3 — `fetch`'s 12 MP bound is enforced from the prediction, so it must be exact.

    Rendering is the memory spike, so the bound has to be decided *before* the pixmap exists — a
    12 MP ceiling checked by measuring the pixmap has already allocated what it refuses. That only
    works if the prediction and the renderer agree exactly: a prediction that drifted would admit
    calls that do not fit and refuse calls that do.
    """
    rendered = render.render_page(synthetic_pdf, 20, dpi=dpi,
                                 region=None if dpi <= 220 else (0.0, 0.0, 1.0, 0.55))

    assert render.predicted_pixels(synthetic_pdf, 20, dpi=dpi,
                                   region=None if dpi <= 220 else (0.0, 0.0, 1.0, 0.55)) == \
        (rendered.width, rendered.height)
    assert render.predicted_megapixels(synthetic_pdf, 20, dpi=dpi,
                                       region=None if dpi <= 220 else (0.0, 0.0, 1.0, 0.55)) == \
        pytest.approx(rendered.megapixels)


@pytest.mark.parametrize("region", [(0.0, 0.0, 1.0, 0.55), (0.25, 0.25, 0.75, 0.75),
                                    (0.9, 0.9, 1.0, 1.0)])
def test_the_predicted_size_is_the_rendered_size_for_a_crop(synthetic_pdf, region):
    rendered = render.render_page(synthetic_pdf, 20, dpi=300, region=region)

    assert render.predicted_pixels(synthetic_pdf, 20, dpi=300, region=region) == \
        (rendered.width, rendered.height)


def test_predicting_a_size_renders_nothing(monkeypatch, synthetic_pdf, tmp_path):
    """The whole point: asking how big a raster would be must not make one (§15.1).

    Asserted two ways — no pixels are produced (the render seam is not called) and nothing is
    written — because the second is what E3 was and the first is what makes the bound cheap.
    """
    render.cache_clear()
    monkeypatch.chdir(tmp_path)
    rendered: list[int] = []
    monkeypatch.setattr(render, "_render",
                        lambda *args, **kwargs: rendered.append(1) or pytest.fail("rendered"))

    with _write_spy(monkeypatch) as written:
        pixels = render.predicted_pixels(synthetic_pdf, 20, dpi=400, region=(0, 0, 1, 0.55))

    assert pixels[0] > 0 and pixels[1] > 0
    assert rendered == []
    assert written == [], f"predicting a size wrote to the filesystem: {written}"
    assert render.cache_info()["misses"] == 0


def test_predicting_a_page_outside_the_document_is_the_same_typed_refusal(synthetic_pdf,
                                                                         expected):
    """The prediction refuses what the renderer would refuse, so the bound cannot be evaded."""
    with pytest.raises(render.RenderError) as refusal:
        render.predicted_pixels(synthetic_pdf, expected["page_count"] + 1, dpi=150)

    assert refusal.value.code == "page_out_of_range"


def test_a_full_page_at_400_dpi_is_over_the_fetch_megapixel_bound(synthetic_pdf):
    """Why §7.3 requires a `region` above 220 dpi, as a number rather than as an assertion.

    An A4 page at 400 dpi is 15 MP — over the 12 MP a whole `fetch` is allowed — so the rule that
    detail that fine must be about *part* of a page is not a policy preference, it is the only
    shape in which that dpi fits at all.
    """
    assert render.predicted_megapixels(synthetic_pdf, 20, dpi=400) > MAX_FETCH_MEGAPIXELS
    assert render.predicted_megapixels(synthetic_pdf, 20, dpi=400,
                                       region=(0.0, 0.0, 1.0, 0.55)) < MAX_FETCH_MEGAPIXELS


def test_the_render_seam_is_what_the_cache_wraps(monkeypatch, synthetic_pdf):
    """The cache is provably a cache: one render for two identical requests, then eviction.

    U018's acceptance criterion, at the level where it is cheap to assert. `test_page_image.py`
    re-asserts it over the HTTP route, where the same eviction must produce a byte-identical image.
    """
    render.cache_clear()
    calls: list[tuple] = []
    real = render._render

    def counted(source, page_no, dpi, region):
        calls.append((page_no, dpi, region))
        return real(source, page_no, dpi, region)

    monkeypatch.setattr(render, "_render", counted)

    first = render.render_page(synthetic_pdf, 5, dpi=DPI_INDEX)
    render.render_page(synthetic_pdf, 5, dpi=DPI_INDEX)

    assert len(calls) == 1, "the second identical request must not render"

    render.cache_clear()
    again = render.render_page(synthetic_pdf, 5, dpi=DPI_INDEX)

    assert len(calls) == 2
    assert again.png == first.png, "an evicted entry re-renders byte-identically"


def test_there_is_no_image_path_anywhere_in_the_renderer():
    """Register A5 — the stale `image_path` that made `read()` 503 for every page (§5.3)."""
    source = pathlib.Path(render.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))

    assert "image_path" not in code.split('"""')[-1]
    assert not hasattr(render.Raster, "path")
