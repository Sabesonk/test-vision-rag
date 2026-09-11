"""Conformance — Spec §12.5: the mistakes a well-meaning contributor makes.

Every rule here is a defect that reads as reasonable code. Nobody adds `rapidfuzz` to make the
system wrong; they add it to make a near-miss match, which is exactly the injury §1.1 exists to
prevent. Nobody pins `gemini-pro-latest` to break provenance; they pin it to stay current. So each
rule is executable, runs in the fast layer, and names the invariant it protects when it fires.

**Scope (§12.5).** `backend/vsir/**` and `requirements*.txt`, plus `Dockerfile*` and
`docker-compose*.yml` for the cloud-native set. Never markdown — the spec, the plan and the README
quote every banned string, and a suite that scanned them could only be kept green by not writing
things down. Never this file either, for the same reason: it names what it bans.

**What is deliberately *not* grepped.** I2 — that `ingest/probe.py` is the only writer of the
`text` payload field — cannot be a string grep, because `ingest/index.py` legitimately upserts a
payload containing that key. The real check is the `get_text(` rule below (only the probe may
*derive* text) paired with an L1 assertion that `record.text == probe_text[page_no]` for every
page of the fixture, which U009 owns.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

SELF = Path(__file__).resolve()
REPO = SELF.parents[3]
PACKAGE = REPO / "backend" / "vsir"

_SKIP_DIRS = {"__pycache__", ".venv", "node_modules", ".git"}


def _walk(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in suffixes
        and path.resolve() != SELF
        and not _SKIP_DIRS & set(path.parts)
    )


def package_files() -> list[Path]:
    """Every Python source file of the service. Markdown and fixtures are out of scope."""
    return _walk(PACKAGE, (".py",))


def requirement_files() -> list[Path]:
    """`requirements*.txt` — and `requirements.lock`, which is what actually gets installed.

    §12.5 names the `.txt` files; the lock is included because a fuzzy-matching library would
    arrive as somebody's transitive dependency, and the lock is the only file that would show it.
    """
    return sorted(
        path for path in (REPO / "backend").glob("requirements*")
        if path.is_file() and path.suffix in {".txt", ".lock"}
    )


def container_files() -> list[Path]:
    """`Dockerfile*` and `docker-compose*.yml`, wherever they are in the repo."""
    found = [path for path in REPO.rglob("Dockerfile*") if not _SKIP_DIRS & set(path.parts)]
    found += [path for path in REPO.glob("docker-compose*.yml")]
    return sorted(path for path in found if path.is_file())


def scan(files: list[Path], pattern: str, *, flags: int = 0) -> list[str]:
    """Every `path:line: text` a pattern matches, so a failure points at what to change."""
    compiled = re.compile(pattern, flags)
    hits: list[str] = []
    for path in files:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if compiled.search(line):
                hits.append(f"{path.relative_to(REPO)}:{number}: {line.strip()}")
    return hits


def scan_under(subdir: str, pattern: str, *, flags: int = 0) -> list[str]:
    return scan(_walk(PACKAGE / subdir, (".py",)), pattern, flags=flags)


# ── the suite scans something, and it scans the right things ─────────────────────────────────────

def test_the_suite_has_files_to_scan():
    """A conformance suite that silently scans nothing is worse than no suite."""
    assert package_files(), f"no Python sources found under {PACKAGE}"
    assert requirement_files(), "no requirements files found"
    assert container_files(), "no Dockerfile or compose file found"


@pytest.mark.parametrize("subdir", ["serve", "core", "ingest", "eval", "vlm", "mcp"])
def test_every_subdirectory_scan_has_something_to_scan(subdir):
    """`scan_under` is the one helper that can pass vacuously, so its scope is asserted.

    `test_no_match_text_under_serve` narrows to one package directory. If `serve/` were renamed or
    moved, that grep would go green by scanning an empty set — the gate on I3's *one exact-match
    code path* would be gone and nothing would say so. The M3 milestone verification named this
    as the suite's one remaining vacuous-pass risk.
    """
    assert _walk(PACKAGE / subdir, (".py",)), f"nothing to scan under {PACKAGE / subdir}"


def test_the_suite_never_scans_markdown():
    """The spec and the README quote every banned string; scanning prose would ban documenting."""
    assert not [path for path in package_files() + container_files() if path.suffix == ".md"]

    probe = PACKAGE / "_conformance_probe.md"
    probe.write_text("entity_keys SCHEMA_CARD classify( image: python:latest\n")
    try:
        assert probe not in package_files()
        assert not scan(package_files(), r"\bentity_keys\b")
    finally:
        probe.unlink()


def test_the_suite_excludes_its_own_source():
    """This file names every banned string. It must not be in its own scope (§12.5)."""
    assert "entity_keys" in SELF.read_text()
    assert SELF not in package_files()
    assert not scan(package_files(), r"\bentity_keys\b")


def test_an_injected_violation_is_caught_and_its_removal_clears_the_suite():
    """The gate is real: a banned string under serve/ fails, and removing it passes."""
    scratch = PACKAGE / "serve" / "_conformance_scratch.py"
    scratch.write_text('SCRATCH = {"entity_keys": 1}\n')
    try:
        assert scan(package_files(), r"\bentity_keys\b"), "an injected violation went unseen"
    finally:
        scratch.unlink()
    assert not scan(package_files(), r"\bentity_keys\b")


# ── §12.5 core set ──────────────────────────────────────────────────────────────────────────────

def test_no_match_text_under_serve():
    """I3, F1 — one exact-match code path: MatchPhrase over variants(label), nothing else.

    `MatchText` matches tokens in any order, so `"SF 1.1A"` would return every page carrying `sf`
    and `1`. Under `serve/` that is not a slow path, it is a wrong answer.
    """
    assert not scan_under("serve", r"\bMatchTextAny\b|\bMatchText\b")


def test_no_fuzzy_or_similarity_library_is_declared():
    """§7.6 — no edit distance, no similarity library. A near-miss code must not match."""
    banned = (
        r"rapidfuzz|fuzzywuzzy|thefuzz|fuzzysearch|python-levenshtein|\blevenshtein\b|jellyfish"
        r"|editdistance|textdistance|pylev|jarowinkler|scikit-learn|\bsklearn\b|\bdifflib\b"
    )
    assert not scan(requirement_files(), banned, flags=re.IGNORECASE)


def test_no_fuzzy_matching_from_the_standard_library_either():
    """`difflib` needs no requirement, so banning it in the lock file is not enough."""
    assert not scan(package_files(), r"\bdifflib\b|\bSequenceMatcher\b|\bget_close_matches\b")


def test_no_field_named_score_in_any_model():
    """§7.6 — a similarity score is never computed, stored or returned.

    An ordinal `rank` is permitted and required: a position is not a confidence. The patterns are
    declaration-shaped rather than the bare word, so prose may still say why the field is banned.
    """
    declarations = r"^\s*score\s*:|^\s*score\s*=|\bscore\s*=\s*Field\(|['\"]score['\"]"
    assert not scan(package_files(), declarations)


def test_no_floating_model_alias_anywhere():
    """F11 — boot refuses one, and it must not be committed in the first place.

    The pattern is a quoted *model id* ending in the alias suffix, so `doctor.py`'s
    `FLOATING_SUFFIX = "-latest"` — the constant that implements the refusal — is not a violation
    of it. Compose files are in scope: an environment block is exactly where one would appear.
    """
    alias = r"['\"][A-Za-z0-9][A-Za-z0-9._-]*-latest['\"]|[A-Za-z0-9._-]+-latest\s*$"
    assert not scan(package_files(), alias)
    assert not scan(container_files(), r"[A-Za-z0-9._-]{2,}-latest")


def test_no_relational_database_anywhere():
    """§4.2 — Qdrant is the only store. No ORM, no migrations, no raw SQL."""
    banned = r"\balembic\b|\bsqlalchemy\b|\bpsycopg\b|\basyncpg\b"
    assert not scan(package_files(), banned, flags=re.IGNORECASE)
    assert not scan(requirement_files(), banned, flags=re.IGNORECASE)


def test_the_test_stack_is_qdrant_only_and_never_binds_the_dev_grpc_port():
    """The template's Postgres service described nothing in this system; M0 replaced it.

    A *declaration* is what matters, not the word: this file explains in a comment why Postgres is
    gone, and a suite that banned the explanation would ban explaining.
    """
    compose = REPO / "docker-compose.test.yml"
    text = compose.read_text()

    assert not scan([compose], r"^\s*image:\s*\S*postgres|^\s*POSTGRES_\w+:|^\s{2}test-db:",
                    flags=re.IGNORECASE | re.MULTILINE)
    assert "qdrant/qdrant:v1.19.0" in text
    # 6334 is the dev instance's gRPC port: publishing it here would let a test run read — and
    # `down -v` wipe — the dev collection (§4.2).
    assert not scan([compose], r'"6334:')
    assert scan([compose], r'"6335:6333"')


def test_get_text_only_in_the_probe():
    """I2 — `ingest/probe.py` is the only module that may *derive* page text.

    Anything else calling PyMuPDF's `get_text(` is a second extractor, and two extractors mean the
    `text` a claim is verified against is not the `text` that was indexed (F15).
    """
    offenders = [
        hit for hit in scan(package_files(), r"\bget_text\(")
        if "ingest/probe.py" not in hit
    ]
    assert not offenders


@pytest.mark.parametrize("name", ["SCHEMA_CARD", "IdClass", "entity_keys", r"classify\("])
def test_no_struck_legacy_name(name):
    """C1 — the identifier grammar is gone: no regex, no class, no curated exact-match index."""
    assert not scan(package_files(), rf"\b{name}")


# ── §12.5 cloud-native set ──────────────────────────────────────────────────────────────────────

def test_the_app_never_opens_a_log_file():
    """§15 Factor XI — stdout is the stream; the platform collects it. No file, no rotation."""
    assert not scan(package_files(), r"logging\.FileHandler|RotatingFileHandler|TimedRotating")


def test_no_container_image_is_tagged_latest():
    """§15.2 — and an *untagged* image is tagged `latest`, which is the same defect unwritten."""
    offenders: list[str] = []
    for path in container_files():
        text = path.read_text(encoding="utf-8")
        args = dict(re.findall(r"^ARG\s+([A-Za-z_][A-Za-z0-9_]*)=(\S+)", text, re.MULTILINE))
        for number, line in enumerate(text.splitlines(), start=1):
            match = re.match(r"\s*(?:FROM|image:)\s+(\S+)", line)
            if not match:
                continue
            reference = match.group(1)
            for name, value in args.items():
                reference = reference.replace(f"${{{name}}}", value).replace(f"${name}", value)
            if "${" in reference:  # an unresolved variable is supplied by config, not the build
                continue
            pinned = "@sha256:" in reference or re.search(r":[^/]+$", reference)
            if reference.endswith(":latest") or not pinned:
                offenders.append(f"{path.relative_to(REPO)}:{number}: {line.strip()}")
    assert not offenders


def test_one_image_runs_every_process_type():
    """§15 Factor XII, AC-015 — `web`, `ingest-worker` and one-off admin are one image.

    The property is easy to hold by hand and easy to break by hand: a service that grows its own
    `build:` context, or a `console`-style sidecar that quietly starts running `vsir`, is a second
    release answering as the first. Compose is read as text rather than with a YAML parser because
    §15 Factor III took PyYAML out of this project's dependencies, and a test-only dependency is
    still a dependency.
    """
    service = re.compile(r"^  ([a-z][a-z0-9_-]*):\s*$")
    for compose in sorted(REPO.glob("docker-compose*.yml")):
        images: dict[str, str] = {}
        commands: dict[str, str] = {}
        current = ""
        for line in compose.read_text(encoding="utf-8").splitlines():
            header = service.match(line)
            if header:
                current = header.group(1)
                continue
            if not current:
                continue
            image = re.match(r"^    image:\s*(\S+)", line)
            if image:
                images[current] = image.group(1)
            command = re.match(r"""^    command:\s*\[\s*["']([a-z-]+)["']""", line)
            if command:
                commands[current] = command.group(1)

        app = {name: image for name, image in images.items() if image.startswith("vsir:")}
        assert len(set(app.values())) == 1, (
            f"{compose.name}: the vsir services do not share one image: {app}")
        process_types = {commands[name] for name in app if name in commands}
        assert {"serve", "ingest", "doctor"} <= process_types, (
            f"{compose.name}: one image must run all three process types, found {process_types}")


def test_no_credential_literal():
    """§15.1 — a token or a key never appears in code, a log line, a response or an image.

    Constructing a header from a variable is fine: the patterns require a *string literal* after
    the assignment, which is the shape of a committed secret.
    """
    banned = r"api_key\s*=\s*['\"][^'\"]|\btoken\s*=\s*['\"][^'\"]|['\"]Bearer\s+[A-Za-z0-9]"
    assert not scan(package_files(), banned)
    assert not scan(container_files(), banned)


def test_no_secret_baked_into_an_image():
    """§15 Factor III — secrets arrive from the platform secret store as env at runtime."""
    assert not scan(container_files(), r"^\s*ENV\s+\w*(KEY|TOKEN|SECRET|PASSWORD)\w*\s*=?\s*\S",
                    flags=re.IGNORECASE | re.MULTILINE)


def test_no_test_only_branch_in_the_production_path():
    """§15 Factor X — config selects the stub (`VSIR_VLM=stub`), never an `if`.

    A test-only branch means the path under test is not the path that ships, which makes every
    green test a statement about different code.
    """
    banned = (
        r"if\s+TESTING\b|if\s+os\.environ\.get\(\s*['\"]TESTING|if\s+os\.getenv\(\s*['\"]TESTING"
        r"|PYTEST_CURRENT_TEST|if\s+['\"]pytest['\"]\s+in"
    )
    assert not scan(package_files(), banned)


def test_no_module_level_mutable_session_store():
    """C11, §15.2 — the `RetrievalState` singleton plan2 sketched is struck.

    Server-held session state is what makes F8 possible: an agent believes it searched a chapter
    while the server quietly searched a subset. `scope` and `exclude` are parameters, and
    `effective_scope` is echoed back.
    """
    assert not scan(package_files(), r"\bRetrievalState\b")
    module_level_container = r"^[A-Za-z_][A-Za-z0-9_]*(\s*:[^=]+)?\s*=\s*(\{\}|\[\]|set\(\)|dict\(\)|list\(\))\s*(#.*)?$"
    assert not scan(package_files(), module_level_container)


# ── the same rule, as an AST scan rather than a regex (U014 AC, §15 Factor VI) ───────────────────

#: Constructors whose result is a mutable container. A module-level binding to one of these is a
#: *candidate* store; what condemns it is being written to (see :func:`_module_state_offenders`).
_CONTAINER_CALLS = frozenset({
    "dict", "list", "set", "defaultdict", "OrderedDict", "Counter", "deque", "ChainMap",
    "LRUCache", "TTLCache", "WeakValueDictionary", "WeakKeyDictionary",
})
#: Calls that mutate the object they are called on.
_MUTATORS = frozenset({
    "append", "extend", "insert", "add", "update", "setdefault", "pop", "popitem", "clear",
    "remove", "discard", "sort", "__setitem__",
})


def _module_level_containers(tree: "ast.Module") -> set[str]:
    """Every module-level name bound to a mutable container, literal or constructed."""
    names: set[str] = set()
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        value = node.value
        mutable = isinstance(value, (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp,
                                     ast.SetComp))
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            mutable = mutable or value.func.id in _CONTAINER_CALLS
        if mutable:
            names.update(target.id for target in targets if isinstance(target, ast.Name))
    return names


def _shown(path: Path) -> str:
    """A repo-relative path when it is in the repo, the full one otherwise (the planted case)."""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def _module_state_offenders(path: Path) -> list[str]:
    """Module-level containers this file **writes to** — the shape of a server-held store.

    A module-level ``dict`` that is only ever read is a lookup table (`_GAUGE_HELP`, `INDEXED`),
    and banning those would ban every constant in the package. What makes one a *store* is a
    write: ``CACHE[key] = value``, ``SESSIONS.setdefault(...)``, ``SEEN.add(...)``. One of those
    at module scope means two replicas disagree and a restart forgets — which is how an agent
    comes to believe it searched a chapter the server quietly searched a subset of (F8, C11).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = _module_level_containers(tree)
    if not names:
        return []
    offenders: list[str] = []
    for node in ast.walk(tree):
        written: str | None = None
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            written_targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in written_targets:
                if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) \
                        and target.value.id in names:
                    written = target.value.id
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) \
                        and target.value.id in names:
                    written = target.value.id
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in _MUTATORS and isinstance(node.func.value, ast.Name) \
                and node.func.value.id in names:
            written = node.func.value.id
        if written:
            offenders.append(f"{_shown(path)}:{node.lineno}: writes to {written}")
    return offenders


def test_no_module_level_state_is_mutated_anywhere_in_serve():
    """§15 Factor VI, C11 — an AST scan, because the regex only sees an *empty* literal.

    `web` scales horizontally by construction, so anything correctness-bearing in process memory
    is N different values, one per replica, each of which forgets on deploy. The serve package is
    scanned first and hardest because it is the one that handles a caller's request; the whole
    package follows, because an ingest module that cached a run in a dict would be the same bug
    one process type over.
    """
    serve_offenders = [problem for path in _walk(PACKAGE / "serve", (".py",))
                       for problem in _module_state_offenders(path)]
    assert not serve_offenders

    package_offenders = [problem for path in package_files()
                         for problem in _module_state_offenders(path)]
    assert not package_offenders


def test_the_ast_scan_catches_a_planted_session_store(tmp_path: Path):
    """The scanner is asserted to fire, so a green run is evidence and not a silent no-op."""
    planted = tmp_path / "planted.py"
    planted.write_text("SESSIONS = {}\n\n\ndef remember(key, value):\n    SESSIONS[key] = value\n")

    assert _module_state_offenders(planted), "the AST scan must catch a module-level store"

    planted.write_text("SESSIONS = ()\n\n\ndef remember(key, value):\n    return {key: value}\n")
    assert not _module_state_offenders(planted)


def test_no_async_handler_does_sync_io():
    """§4.2 / NFR — a blocking call in an async handler stalls the whole event loop."""
    assert not scan(package_files(), r"^\s*import\s+requests\b|^\s*from\s+requests\b")
    assert not scan(package_files(), r"\brequests\.(get|post|put|delete)\(")
