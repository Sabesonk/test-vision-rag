"""The boot self-check of Spec §4.3, shared by ``vsir doctor`` and by server start (U014).

**Never degrade to a partial service.** Every check either passes or names its reason and makes the
process exit non-zero. Nothing here is advisory and nothing is skipped to get a green line.

Two of the five refusals are local to the process and live here:

1. a configured model id ending in ``-latest`` (F11 — a floating alias silently changes what the
   cache keys and the collection fingerprint describe, so an answer stops being traceable to the
   model that produced it);
2. a missing required environment variable (§15 Factor III).

The other three read the **live collection** — the payload schema against ``INDEXED``, the
embedding fingerprint, and ``phrase_matching`` on ``text``/``vlm_codes``. They arrive with
``core/indexed.py`` in U003, which extends this module and ``vsir doctor`` with
``--create-collection``. They are appended to :data:`BOOT_CHECKS`, which is the whole extension
point: one check list, run identically by the CLI and by server start, so the two can never drift.
"""
from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass, field
from importlib import metadata
from typing import Callable, Mapping

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
)

OK = "ok"
FAIL = "fail"

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
    """One boot check. ``status`` is :data:`OK` or :data:`FAIL` — there is no third outcome."""

    name: str
    status: str
    detail: str
    facts: dict[str, object] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return self.status == FAIL


def check_required_env(env: Mapping[str, str]) -> CheckResult:
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


def check_model_ids_pinned(env: Mapping[str, str]) -> CheckResult:
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


def check_config_valid(env: Mapping[str, str]) -> CheckResult:
    """Every configured value parses and is in range — a typed refusal, never a coerced default."""
    try:
        cfg = load_config(env)
    except ConfigError as exc:
        return CheckResult("config_valid", FAIL, str(exc), {"var": getattr(exc, "var", None)})
    return CheckResult("config_valid", OK, "configuration parses", cfg.redacted())


def check_python_runtime(_env: Mapping[str, str]) -> CheckResult:
    """The runtime is at or above the pinned floor (Factor II)."""
    version = platform.python_version()
    if sys.version_info[:2] < PYTHON_FLOOR:
        floor = ".".join(str(part) for part in PYTHON_FLOOR)
        return CheckResult(
            "python_runtime", FAIL, f"python {version} is below the pinned {floor}",
            {"python": version},
        )
    return CheckResult("python_runtime", OK, f"python {version}", {"python": version})


def check_dependencies(_env: Mapping[str, str]) -> CheckResult:
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


#: The one check list. `vsir doctor` and server start run exactly this, in this order.
BOOT_CHECKS: tuple[Callable[[Mapping[str, str]], CheckResult], ...] = (
    check_required_env,
    check_model_ids_pinned,
    check_config_valid,
    check_python_runtime,
    check_dependencies,
)


def run_boot_checks(env: Mapping[str, str] | None = None) -> list[CheckResult]:
    """Run every boot check and return all results.

    All of them run: the exit code is what refuses the boot, so there is no value in stopping at
    the first failure and hiding the rest from whoever has to fix them.
    """
    env = os.environ if env is None else env
    return [check(env) for check in BOOT_CHECKS]


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


def doctor(env: Mapping[str, str] | None = None) -> int:
    """Run the boot self-check, log one JSON event per check, and return the exit code."""
    env = os.environ if env is None else env
    results = run_boot_checks(env)
    for result in results:
        emit = _log.error if result.failed else _log.info
        emit(
            "boot_check_failed" if result.failed else "boot_check_ok",
            check=result.name,
            detail=result.detail,
            **result.facts,
        )
    failures = [result.name for result in results if result.failed]
    facts = report(env)
    if failures:
        _log.error("doctor_refused", failed_checks=failures, **facts)
        return 1
    _log.info("doctor_ok", failed_checks=[], **facts)
    return 0
