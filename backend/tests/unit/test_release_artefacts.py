"""L0 — the files a release has to carry are actually in it (§15 Factors I, II, V).

A wheel that is missing a data file is a defect no unit test sees, because the tests import from
the source tree where the file is simply there. The container is where it bites, and the first
paid ingest is where it bit: `POST /documents` answered `202`, the child reached step 04 and died
with `prompt_unavailable` — *"vsir/vlm/prompts/s1.md is missing from the release"*. The stub
backend replays a frozen response and never loads a prompt, so the entire suite was green and
every replayed ingest worked.

So the packaging is asserted here, from the declaration rather than from the built artefact: a
data file the code reads at runtime must be listed in `[tool.setuptools.package-data]`, and the
digests the cache keys are built from must match the files that would ship.
"""
from __future__ import annotations

import hashlib
import tomllib
from fnmatch import fnmatch
from pathlib import Path

import pytest

from vsir.vlm.client import PROMPT_DIGESTS, PROMPT_DIR, PROMPT_STAGES, prompt

BACKEND = Path(__file__).resolve().parents[2]
PYPROJECT = BACKEND / "pyproject.toml"


@pytest.fixture(scope="module")
def declared() -> dict:
    return tomllib.loads(PYPROJECT.read_text())


def test_the_prompts_are_declared_as_package_data(declared):
    """The one-line declaration whose absence cost a paid run.

    `packages.find` ships *modules*; a `.md` beside them is data and is left out unless it is
    named. `pip install .` from the source tree in CI does not reveal this either, because the
    tests never import from the installed copy.
    """
    data = declared["tool"]["setuptools"]["package-data"]

    assert "vsir.vlm" in data, "vsir/vlm/prompts/*.md would be left out of the wheel"
    assert any(pattern.endswith(".md") for pattern in data["vsir.vlm"])


def test_every_prompt_the_code_reads_exists_where_it_looks_for_it():
    """`PROMPT_DIR` is resolved from `__file__`, so this holds in a wheel as well as in a tree."""
    missing = [stage for stage in PROMPT_STAGES
               if not (PROMPT_DIR / f"{stage}.md").is_file()]

    assert not missing, f"no prompt file for {missing} in {PROMPT_DIR}"


def test_every_declared_prompt_version_matches_the_file_that_would_ship():
    """The prompt text is hashed into the §6.3 cache keys, so the file *is* the release artefact.

    Editing a prompt without releasing a new `VSIR_PROMPT_VERSION` has to fail by name rather than
    serve cached output produced by different instructions (F11) — this is that guarantee checked
    against the bytes on disk.
    """
    for version, stages in PROMPT_DIGESTS.items():
        for stage, expected in stages.items():
            body = (PROMPT_DIR / f"{stage}.md").read_bytes()
            actual = hashlib.sha256(body).hexdigest()

            assert actual == expected, (
                f"{stage}.md has changed but {version}'s digest has not: release a new "
                f"VSIR_PROMPT_VERSION, or the cache would serve output from other instructions")


def test_loading_a_prompt_returns_its_text_and_its_digest():
    """The failure mode was a missing file, so the positive path is worth pinning too."""
    loaded = prompt("s1", next(iter(PROMPT_DIGESTS)))

    assert loaded.text.strip(), "an empty prompt is a prompt that was not found"
    assert loaded.digest == PROMPT_DIGESTS[next(iter(PROMPT_DIGESTS))]["s1"]


def test_no_other_runtime_data_file_is_left_undeclared(declared):
    """The general form of the bug: any non-Python file under `vsir/` has to be declared.

    A scan rather than a list, so a data file added later is caught the day it is added instead of
    the first time somebody pays for a run.
    """
    package = BACKEND / "vsir"
    # Declared keys are dotted module paths (`vsir.vlm`) and the files are compared relative to the
    # `vsir` package root, so the leading `vsir.` comes off: `vsir.vlm` + `prompts/*.md` is
    # `vlm/prompts/*.md`.
    patterns = [
        f"{module.removeprefix('vsir.').removeprefix('vsir').replace('.', '/').strip('/')}/{pattern}"
        .lstrip("/")
        for module, globs in declared["tool"]["setuptools"]["package-data"].items()
        for pattern in globs
    ]

    undeclared = sorted(
        str(relative)
        for found in package.rglob("*")
        if found.is_file()
        and found.suffix not in {".py", ".pyc"}
        and "__pycache__" not in found.parts
        for relative in [found.relative_to(package)]
        if not any(fnmatch(str(relative), pattern) for pattern in patterns)
    )

    assert not undeclared, (
        f"these files are read at runtime but would not ship in the wheel: {undeclared}. "
        f"Declare them in [tool.setuptools.package-data].")
