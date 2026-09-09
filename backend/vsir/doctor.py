"""The boot self-check of Spec §4.3, shared by ``vsir doctor`` and by server start (U014).

**Never degrade to a partial service.** Every check either passes or names its reason and makes the
process exit non-zero. Nothing here is advisory and nothing is skipped to get a green line.

Two of the five refusals are local to the process and live here:

1. a configured model id ending in ``-latest`` (F11 — a floating alias silently changes what the
   cache keys and the collection fingerprint describe, so an answer stops being traceable to the
   model that produced it);
2. a missing required environment variable (§15 Factor III).

The other three read the **live collection**: the payload schema against ``INDEXED``,
``phrase_matching`` on ``text``/``vlm_codes``, and the embedding fingerprint. The first two are
here, in :func:`check_collection_schema`; the model-identity half of the fingerprint needs a record
written beside the collection and arrives with U010.

**Three statuses, two policies.** A check that could not reach Qdrant did not *conclude* — it did
not find the schema wrong. Refusing to boot on unreachability would turn a backing-service outage
into a fleet-wide restart loop, which is the exact failure §15.1 exists to prevent. So:

* **boot** — ``vsir doctor`` and server start — refuses on :data:`FAIL` only;
* **readiness** — ``GET /ready`` — is red on :data:`FAIL` **or** :data:`UNAVAILABLE`, which is
  §15.1's "boot self-check passed **and** Qdrant reachable **and** the pinned index schema
  present" read literally: schema *presence* is readiness, schema *drift* is a refusal.
"""
from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass, field
from importlib import metadata
from typing import Callable, Mapping

from qdrant_client import QdrantClient

from vsir import logging as vsir_logging
from vsir.config import (
    COMPOSITION_VERSION,
    DISTANCE,
    DPI_ANSWER,
    DPI_INDEX,
    MODEL_ENV,
    REQUIRED_ENV,
    Config,
    ConfigError,
    load_config,
    scrub_url,
)
from vsir.core import indexed

OK = "ok"
FAIL = "fail"
#: The check did not conclude, because the backing service could not be reached or the collection
#: is not there yet. Boot tolerates it; readiness does not.
UNAVAILABLE = "unavailable"

#: The readiness reasons a check can carry, named so an orchestrator can act on them (§11.3).
QDRANT_UNAVAILABLE = "qdrant_unavailable"
INDEX_NOT_READY = "index_not_ready"

#: How long a boot check waits on Qdrant. A boot check is not the place to hang.
QDRANT_TIMEOUT_S = 2

# A model id may not end in this: pin the version, never a floating alias (§4.2, F11, register B6).
FLOATING_SUFFIX = "-latest"

# Spec §4.2's pinned set. `vsir doctor` prints the resolved versions (Factor II); the versions
# themselves are pinned by requirements.lock and by the image digest, not asserted here.
PINNED_DISTRIBUTIONS = (
    "fastapi",
    "uvicorn",
    "python-multipart",
    "pydantic",
    "google-genai",
    "qdrant-client",
    "pymupdf",
    "pillow",
)

PYTHON_FLOOR = (3, 11)  # the image pins the exact minor by digest; this is the floor (§4.2)

_log = vsir_logging.get_logger(__name__)


@dataclass(frozen=True)
class CheckResult:
    """One boot check: :data:`OK`, :data:`FAIL`, or :data:`UNAVAILABLE` (did not conclude).

    ``reason`` is the readiness reason an :data:`UNAVAILABLE` carries — ``qdrant_unavailable`` or
    ``index_not_ready`` — so ``GET /ready`` reports a name rather than a bare boolean.
    """

    name: str
    status: str
    detail: str
    facts: dict[str, object] = field(default_factory=dict)
    reason: str | None = None

    @property
    def failed(self) -> bool:
        """Only this refuses a boot. An unreachable backing service is not a wrong schema."""
        return self.status == FAIL

    @property
    def inconclusive(self) -> bool:
        return self.status == UNAVAILABLE


def check_required_env(env: Mapping[str, str], _client: QdrantClient | None) -> CheckResult:
    """Refusal 5 — a missing required env var, named (§4.3, §15 Factor III)."""
    required = list(REQUIRED_ENV)
    # The VLM key is required exactly when the Gemini backend is selected: with `VSIR_VLM=stub`
    # there is nothing to authenticate to, and demanding a key would make replay mode (D10)
    # impossible to run in CI.
    if (env.get("VSIR_VLM") or "").strip() == "gemini":
        required.append("VSIR_VLM_KEY")
    missing = [var for var in required if not (env.get(var) or "").strip()]
    if missing:
        return CheckResult(
            "required_env",
            FAIL,
            f"not set: {', '.join(missing)} — see .env.example (§15 Factor III)",
            {"missing": missing},
        )
    return CheckResult("required_env", OK, f"all {len(required)} required variables set")


def check_model_ids_pinned(env: Mapping[str, str],
                           _client: QdrantClient | None) -> CheckResult:
    """Refusal 1 — a floating model alias (F11).

    Runs off the raw environment rather than a parsed :class:`Config` so that it still reports on a
    configuration that is incomplete for some other reason: a builder debugging one refusal should
    see all of them.
    """
    floating = {
        var: value
        for var in MODEL_ENV
        if (value := (env.get(var) or "").strip()) and value.endswith(FLOATING_SUFFIX)
    }
    if floating:
        named = ", ".join(f"{var}={value}" for var, value in sorted(floating.items()))
        return CheckResult(
            "model_ids_pinned",
            FAIL,
            f"model id ends in {FLOATING_SUFFIX}: {named} — pin the version (§4.3, F11)",
            {"floating": floating, "suffix": FLOATING_SUFFIX},
        )
        # impl/config.yaml ships `gemini-pro-latest` and warns in its own comment that "Model IDs
        # move." That is F11, so this refusal is a correction *of* the previous implementation.
    resolved = {var: (env.get(var) or "").strip() for var in MODEL_ENV}
    return CheckResult("model_ids_pinned", OK, "every model id is a pinned version", resolved)


def check_config_valid(env: Mapping[str, str], _client: QdrantClient | None) -> CheckResult:
    """Every configured value parses and is in range — a typed refusal, never a coerced default."""
    try:
        cfg = load_config(env)
    except ConfigError as exc:
        return CheckResult("config_valid", FAIL, str(exc), {"var": getattr(exc, "var", None)})
    return CheckResult("config_valid", OK, "configuration parses", cfg.redacted())


def check_python_runtime(_env: Mapping[str, str], _client: QdrantClient | None) -> CheckResult:
    """The runtime is at or above the pinned floor (Factor II)."""
    version = platform.python_version()
    if sys.version_info[:2] < PYTHON_FLOOR:
        floor = ".".join(str(part) for part in PYTHON_FLOOR)
        return CheckResult(
            "python_runtime", FAIL, f"python {version} is below the pinned {floor}",
            {"python": version},
        )
    return CheckResult("python_runtime", OK, f"python {version}", {"python": version})


def check_dependencies(_env: Mapping[str, str], _client: QdrantClient | None) -> CheckResult:
    """Report the resolved versions of the §4.2 set; a missing distribution is a broken install."""
    resolved: dict[str, object] = {}
    missing: list[str] = []
    for dist in PINNED_DISTRIBUTIONS:
        try:
            resolved[dist] = metadata.version(dist)
        except metadata.PackageNotFoundError:
            resolved[dist] = None
            missing.append(dist)
    if missing:
        return CheckResult(
            "dependencies",
            FAIL,
            f"not installed: {', '.join(missing)} — install requirements.lock (§15 Factor II)",
            resolved,
        )
    return CheckResult("dependencies", OK, f"{len(resolved)} pinned distributions resolved", resolved)


def check_collection_schema(env: Mapping[str, str],
                           client: QdrantClient | None) -> CheckResult:
    """Refusals 2 and 4 — the live payload schema against ``INDEXED``, and phrase matching.

    This is the assertion job of the one ``INDEXED`` dict (I6). A field that stopped being indexed
    — a dropped index, a hand-edited collection, a half-finished migration — becomes a named
    refusal here instead of a quietly narrower answer (F10).

    Reachability and presence are **not** failures. An unreachable Qdrant or a collection that does
    not exist yet leaves this check :data:`UNAVAILABLE`: the instance is not ready, and readiness is
    what removes it from the load balancer. Only a collection that exists and *disagrees* refuses
    the boot.
    """
    try:
        cfg = load_config(env)
    except ConfigError as exc:
        # `config_valid` already reports this; there is no schema to check against a refused config.
        return CheckResult("collection_schema", UNAVAILABLE,
                           f"configuration refused: {exc}", reason=INDEX_NOT_READY)

    owned = client is None
    connection = client or QdrantClient(url=cfg.qdrant_url, timeout=QDRANT_TIMEOUT_S,
                                        check_compatibility=False)
    facts = {"collection": cfg.pages_collection, "dim": cfg.embed_dim}
    try:
        if not connection.collection_exists(cfg.pages_collection):
            return CheckResult(
                "collection_schema", UNAVAILABLE,
                f"collection {cfg.pages_collection!r} does not exist yet — "
                f"create it with `vsir doctor --create-collection`",
                facts, reason=INDEX_NOT_READY,
            )
        problems = indexed.schema_problems(connection, cfg.pages_collection, cfg.embed_dim)
    except Exception as exc:  # noqa: BLE001 - any failure here is "could not reach Qdrant"
        return CheckResult(
            "collection_schema", UNAVAILABLE,
            f"qdrant unreachable at {scrub_url(cfg.qdrant_url)}: {type(exc).__name__}: {exc}",
            facts, reason=QDRANT_UNAVAILABLE,
        )
    finally:
        if owned:
            connection.close()

    if problems:
        return CheckResult("collection_schema", FAIL,
                           "live schema disagrees with INDEXED: " + "; ".join(problems),
                           {**facts, "problems": problems})
    return CheckResult("collection_schema", OK,
                       f"{cfg.pages_collection} matches INDEXED ({len(indexed.INDEXED)} keys)",
                       facts)


#: The one check list. `vsir doctor` and server start run exactly this, in this order.
BOOT_CHECKS: tuple[Callable[[Mapping[str, str], QdrantClient | None], CheckResult], ...] = (
    check_required_env,
    check_model_ids_pinned,
    check_config_valid,
    check_python_runtime,
    check_dependencies,
    check_collection_schema,
)


def run_boot_checks(env: Mapping[str, str] | None = None,
                    client: QdrantClient | None = None) -> list[CheckResult]:
    """Run every boot check and return all results.

    All of them run: the exit code is what refuses the boot, so there is no value in stopping at
    the first failure and hiding the rest from whoever has to fix them.

    ``client`` lets a long-lived process hand in the connection it already holds, so a readiness
    probe every few seconds does not build and tear down an HTTP client each time. It is a **sync**
    client on purpose: `GET /ready` runs this whole list in a worker thread rather than doing
    blocking I/O on the event loop.
    """
    env = os.environ if env is None else env
    return [check(env, client) for check in BOOT_CHECKS]


def create_pages_collection(env: Mapping[str, str] | None = None) -> int:
    """`vsir doctor --create-collection` — build the collection from ``INDEXED`` (§5.5).

    A one-off admin process, from the same image and release as everything else (§15 Factor XII):
    there is no live surgery on a collection and no laptop-only script.
    """
    env = os.environ if env is None else env
    cfg = load_config(env)
    client = QdrantClient(url=cfg.qdrant_url, timeout=60, check_compatibility=False)
    try:
        created = indexed.create_collection(client, cfg.pages_collection, cfg.embed_dim)
        info = client.get_collection(cfg.pages_collection)
        vectors = info.config.params.vectors
        sparse = info.config.params.sparse_vectors or {}
        _log.info(
            "collection_created" if created else "collection_exists",
            collection=cfg.pages_collection,
            dim=cfg.embed_dim,
            fingerprint_id=cfg.fingerprint_id,
            vectors={name: {"size": params.size,
                            "distance": getattr(params.distance, "value", str(params.distance))}
                     for name, params in (vectors or {}).items()},
            sparse_vectors={name: {"modifier": getattr(params.modifier, "value",
                                                       str(params.modifier))}
                            for name, params in sparse.items()},
            payload_indexes={
                field: {"type": getattr(info_.data_type, "value", str(info_.data_type)),
                        **({"phrase_matching": getattr(info_.params, "phrase_matching", None),
                            "tokenizer": getattr(getattr(info_.params, "tokenizer", None),
                                                 "value", None),
                            "lowercase": getattr(info_.params, "lowercase", None),
                            "min_token_len": getattr(info_.params, "min_token_len", None)}
                           if field in indexed.TEXT_FIELDS else {})}
                for field, info_ in (info.payload_schema or {}).items()
            },
        )
        return 0
    finally:
        client.close()


class BootRefused(RuntimeError):
    """Raised instead of serving. Spec §4.3: never degrade to a partial service.

    ``vsir doctor`` turns the same failures into an exit code; a server start turns them into this,
    which unwinds before the port is bound. The two run the identical :data:`BOOT_CHECKS`, so a
    configuration the CLI refuses can never be one the server accepts.
    """

    def __init__(self, results: list[CheckResult]) -> None:
        reasons = "; ".join(f"{result.name}: {result.detail}" for result in results)
        super().__init__(f"boot refused — {reasons}")
        self.results = results

    @property
    def failed_checks(self) -> list[str]:
        return [result.name for result in self.results]


def assert_boot_ok(env: Mapping[str, str] | None = None,
                   client: QdrantClient | None = None) -> list[CheckResult]:
    """Run the boot self-check, report it on the event stream, and raise on any failure."""
    results = run_boot_checks(env, client)
    for result in results:
        if result.failed:
            emit, event = _log.error, "boot_check_failed"
        elif result.inconclusive:
            emit, event = _log.warning, "boot_check_unavailable"
        else:
            emit, event = _log.info, "boot_check_ok"
        emit(event, check=result.name, detail=result.detail, reason=result.reason,
             **result.facts)
    failures = [result for result in results if result.failed]
    if failures:
        raise BootRefused(failures)
    return results


def report(env: Mapping[str, str] | None = None) -> dict[str, object]:
    """The facts §13 M0 requires ``vsir doctor`` to print: release, models, index fingerprint."""
    env = os.environ if env is None else env
    facts: dict[str, object] = {
        "release_id": (env.get("VSIR_RELEASE_ID") or "").strip() or None,
        "python": platform.python_version(),
        "dpi_index": DPI_INDEX,
        "dpi_answer": DPI_ANSWER,
        "distance": DISTANCE,
        "composition_version": COMPOSITION_VERSION,
    }
    try:
        cfg: Config | None = load_config(env)
    except ConfigError:
        cfg = None
    if cfg is None:
        # The configuration is what the fingerprint is computed *from*, so with a refused
        # configuration there is no fingerprint to print — and saying so is the honest report.
        facts.update({"models": None, "fingerprint": None, "fingerprint_id": None,
                      "pages_collection": None, "runs_collection": None})
    else:
        facts.update({
            "models": cfg.models,
            "fingerprint": cfg.fingerprint,
            "fingerprint_id": cfg.fingerprint_id,
            "pages_collection": cfg.pages_collection,
            "runs_collection": cfg.runs_collection,
            "vlm": cfg.vlm,
            "replay": cfg.replay,
        })
    return facts


def doctor(env: Mapping[str, str] | None = None, *, create_collection: bool = False) -> int:
    """Run the boot self-check, log one JSON event per check, and return the exit code.

    ``create_collection`` builds the collection from ``INDEXED`` first, so
    ``vsir doctor --create-collection`` is create-then-assert in one command.
    """
    env = os.environ if env is None else env
    if create_collection:
        try:
            create_pages_collection(env)
        except ConfigError as exc:
            _log.error("doctor_refused", failed_checks=["config_valid"], detail=str(exc))
            return 1
    facts = report(env)
    try:
        results = assert_boot_ok(env)
    except BootRefused as refusal:
        _log.error("doctor_refused", failed_checks=refusal.failed_checks, **facts)
        return 1
    # An inconclusive check does not refuse the boot, but it is not a pass either. The event name
    # changes, because an operator greps `event=doctor_ok` to mean "this release was checked" and
    # a run that never reached the collection did not check it.
    unavailable = [result.name for result in results if result.inconclusive]
    if unavailable:
        _log.warning("doctor_inconclusive", failed_checks=[], unavailable_checks=unavailable,
                     **facts)
    else:
        _log.info("doctor_ok", failed_checks=[], unavailable_checks=[], **facts)
    return 0
