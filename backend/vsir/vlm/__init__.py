"""The VLM boundary — one call surface, two backends, chosen by configuration alone.

Everything the pipeline knows about a model call is in this package, and everything outside it
takes a :class:`~vsir.vlm.client.Backend`. That is what makes the whole system replayable: the
ingest steps do not know whether the answer came from Gemini or from a file frozen months ago,
because the question they asked — *"the response under this cache key"* — has the same shape either
way (§15 Factor IV).

**The backend is a dictionary lookup on one configuration value**, :func:`backend`. Not an ``if``,
not a conditional import, not a test-only path. §15 Factor X and §15.2 both rule those out and
U002's conformance grep enforces it, for a reason that is worth stating plainly: a test-only branch
means the code under test is not the code that ships, so every green test is a statement about
something else.

The four cache keys, the store and the typed refusals live in :mod:`vsir.vlm.cache`; what a call
*is* — the request, the prompt loader, the rate limiter and the live client — lives in
:mod:`vsir.vlm.client`; the replay backend is :mod:`vsir.vlm.stub`.
"""
from __future__ import annotations

from types import MappingProxyType

from vsir.config import Config
from vsir.vlm.cache import (
    EXTRACT,
    FACTS,
    KIND_VLM_CACHE,
    NAMESPACES,
    READ,
    ControlPlaneStore,
    Entry,
    FixtureMiss,
    FixtureStore,
    VlmCallFailed,
    VlmError,
    VlmSchemaInvalid,
    VlmTruncated,
    VlmUnavailable,
    cache_point_id,
    embed_key,
    extract_key,
    facts_key,
    read_key,
    write,
)
from vsir.vlm.client import (
    MAX_ATTEMPTS,
    PROMPT_DIGESTS,
    PROMPT_DIR,
    PROMPT_STAGES,
    Backend,
    GeminiBackend,
    Prompt,
    PromptUnavailable,
    Request,
    TokenBucket,
    VlmTierUnsupported,
    hint,
    prompt,
)
from vsir.vlm.stub import StubBackend

#: ``VSIR_VLM`` → the backend that value selects. Both are imported unconditionally above, so the
#: image contains both and the choice is made at boot from the environment: the same release runs
#: as ``web``, as ``ingest-worker`` and in CI, differing only in configuration (§15 Factor X).
#:
#: The keys are :data:`vsir.config.VLM_BACKENDS`' values, and a mismatch between the two is caught
#: by :func:`backend` rather than by an unhandled ``KeyError`` — configuration validation names
#: the variable, always.
BACKENDS = MappingProxyType({
    StubBackend.name: StubBackend.from_config,
    GeminiBackend.name: GeminiBackend.from_config,
})

__all__ = [
    "BACKENDS", "EXTRACT", "FACTS", "KIND_VLM_CACHE", "MAX_ATTEMPTS", "NAMESPACES",
    "PROMPT_DIGESTS", "PROMPT_DIR", "PROMPT_STAGES", "READ", "Backend", "ControlPlaneStore",
    "Entry", "FixtureMiss", "FixtureStore", "GeminiBackend", "Prompt", "PromptUnavailable",
    "Request", "StubBackend", "TokenBucket", "VlmCallFailed", "VlmError", "VlmSchemaInvalid",
    "VlmTierUnsupported", "VlmTruncated", "VlmUnavailable", "backend", "cache_point_id",
    "embed_key", "extract_key", "facts_key", "hint", "prompt", "read_key", "write",
]


def backend(cfg: Config) -> Backend:
    """The backend ``VSIR_VLM`` names, built from the configuration. One lookup, no branches."""
    try:
        build = BACKENDS[cfg.vlm]
    except KeyError:
        raise VlmUnavailable(
            f"VSIR_VLM={cfg.vlm!r} names no backend in this release "
            f"(available: {sorted(BACKENDS)})",
            vlm=cfg.vlm, available=sorted(BACKENDS),
        ) from None
    return build(cfg)
