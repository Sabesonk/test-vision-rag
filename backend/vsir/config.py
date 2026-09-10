"""Configuration — the environment is the only source (Spec §15 Factor III).

Ported from ``impl/app/config.py``: the frozen dataclass and the derived-name properties survive,
the ``config.yaml`` loader does not (§2.4). Nothing here reads a file, so a process's configuration
is exactly its environment, and changing a model id or a prompt version is a **release** rather than
a hot edit — both feed cache keys and the collection fingerprint (§6.3, §6.6, F11).

Two kinds of value live here and they are not interchangeable:

* **Pins** (§4.2) — module constants below. dpi, the embedding parameters, the fusion weights and
  the page caps are properties of the corpus and the models, identical in every deployment. They
  are code: reviewed, released, and carried into the cache keys.
* **Config** (§15 Factor III) — the twelve required environment variables, plus a small defaulted
  set. Every one of them varies by deployment. The twelve have **no fallback**: a missing one is a
  named refusal at boot (§4.3), never a silent default that differs from the operator's intent.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit

# ── Pins (Spec §4.2) — carried verbatim from impl/config.yaml ────────────────────────────────────
DPI_INDEX = 150                 # the raster that gets embedded
DPI_ANSWER = 220                # the raster `read` sees — pinned, and an input to read_key (F19)
EMBED_DIMS = (768, 1536, 3072)  # output_dimensionality; MRL truncation, recorded in the name (D4)
EMBED_CONCURRENCY = 8           # bounded pool; the SDK client is sync
EMBED_BATCH_SIZE = 8            # items per call, verified against the response count (D4)
EMBED_MAX_EDGE_PX = 1568        # downscale before embedding to bound tokens and cost
EMBED_QUERY_INSTRUCTION = ""    # empty: Google advises no prefix when the corpus side is multimodal
SURFACE_WEIGHTS = MappingProxyType({"page": 1.0, "lexical": 1.0, "captions": 0.4})  # D2
RRF_K = 60                      # ranks only — no similarity value enters the arithmetic (D2, §7.6)
CAP_PAGES_PER_WINDOW = 30       # attention dilution, not the API maximum
LOOKUP_CAP = 20                 # high-cardinality label cap
MAX_READ_PAGES = 3              # tightened from impl's 4, deliberately (§2.4, §7.3)
DISTANCE = "cosine"             # §5.5
COMPOSITION_VERSION = "d4-fused-v1"  # the D4 dense composition; part of the fingerprint (§6.6)

# ── Config (Spec §15 Factor III) ─────────────────────────────────────────────────────────────────
REQUIRED_ENV = (
    "VSIR_PORT",
    "VSIR_QDRANT_URL",
    "VSIR_COLLECTION",
    "VSIR_VLM",
    "VSIR_VLM_MODEL",
    "VSIR_EMBED_MODEL",
    "VSIR_PROMPT_VERSION",
    "VSIR_API_TOKENS",
    "VSIR_READ_QUOTA",
    "VSIR_ALLOW_PAID",
    "VSIR_LOG_LEVEL",
    "VSIR_RELEASE_ID",
)
MODEL_ENV = ("VSIR_VLM_MODEL", "VSIR_EMBED_MODEL")  # every id boot refuses to float (F11)
# A model id may not end in this: pin the version, never a floating alias (§4.2, F11, register B6).
# It lives here rather than beside the boot check because two places enforce it — `vsir doctor` at
# boot and `vlm/client.py` at the point of spend, where a long-lived worker's configuration may
# never have been through a boot check at all.
FLOATING_SUFFIX = "-latest"
VLM_BACKENDS = ("gemini", "stub")                   # dev/prod parity: config selects, never an `if`
VLM_TIERS = ("standard", "batch")                   # §6.3; not an extract_key input
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


class ConfigError(RuntimeError):
    """Base for the configuration refusals Spec §4.3 turns into a non-zero exit."""


class MissingConfig(ConfigError):
    def __init__(self, var: str) -> None:
        super().__init__(f"{var} is not set: every value in .env.example is required (§15 III)")
        self.var = var


class InvalidConfig(ConfigError):
    def __init__(self, var: str, reason: str) -> None:
        super().__init__(f"{var} is invalid: {reason}")
        self.var = var
        self.reason = reason


@dataclass(frozen=True)
class Config:
    """One process's configuration. Frozen: nothing rewrites it after boot (§15 Factor VI)."""

    port: int
    qdrant_url: str
    collection: str
    vlm: str
    vlm_model: str
    embed_model: str
    prompt_version: str
    read_quota: int
    allow_paid: bool
    log_level: str
    release_id: str
    embed_dim: int
    runs_collection: str
    reads_per_question: int
    fixture_dir: str
    vlm_tier: str
    vlm_rpm: int
    embed_text_chars: int
    #: The mounted volume the source PDFs live on (§4.2, `ingest/store.py`). Deployment-varying by
    #: definition — it is a mount — and empty means a directory under the platform's temporary
    #: directory, which is honest about being ephemeral rather than pretending to be a volume.
    #: Rasters are still never persisted: this names where they are re-rendered *from*.
    doc_store: str = ""
    #: §6.8 — the two sources `safety_flag` is computed from. Configuration, not a compiled-in
    #: taxonomy: `impl` hardcoded a keyword list, corpora differ, and a list in the image is one
    #: no deployment could correct. Empty means nothing is flagged, which is the honest default
    #: for a facet whose values are the uploader's vocabulary and the model's own topics.
    safety_doc_types: tuple[str, ...] = ()
    safety_topics: tuple[str, ...] = ()
    # Secrets. repr=False so no traceback, log line or error message can carry them (§15.1).
    api_tokens: tuple[str, ...] = field(repr=False, default=())
    vlm_key: str = field(repr=False, default="")

    @property
    def pages_collection(self) -> str:
        """Dim is in the name: comparing dims is two collections, not two named vectors (§5.5)."""
        return f"{self.collection}_{self.embed_dim}"

    @property
    def fingerprint(self) -> dict[str, object]:
        """What the collection stores about how its vectors were made (§6.6)."""
        return {
            "embed_model": self.embed_model,
            "dim": self.embed_dim,
            "distance": DISTANCE,
            "composition_version": COMPOSITION_VERSION,
        }

    @property
    def fingerprint_id(self) -> str:
        """A short stable digest of the fingerprint — what `vsir doctor` prints.

        Nothing *compares* it yet. `dim` and `distance` are read back from the live collection by
        `core.indexed.schema_problems`, but `embed_model` and `composition_version` are not
        observable from Qdrant, so the model half of §6.6 needs a record written beside the
        collection — U010's, the unit that writes the fingerprint and refuses to upsert on a
        mismatch.
        """
        canonical = json.dumps(self.fingerprint, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    @property
    def models(self) -> dict[str, str]:
        """The resolved model ids, by the variable that set them."""
        return {"VSIR_VLM_MODEL": self.vlm_model, "VSIR_EMBED_MODEL": self.embed_model}

    @property
    def replay(self) -> bool:
        """Replay mode (D10): the stub plus a fixture directory, selected by config alone."""
        return self.vlm == "stub" and bool(self.fixture_dir)

    def redacted(self) -> dict[str, object]:
        """Everything safe to log. The two secret fields are reported as presence, never value."""
        return {
            "port": self.port,
            "qdrant_url": scrub_url(self.qdrant_url),
            "collection": self.collection,
            "pages_collection": self.pages_collection,
            "runs_collection": self.runs_collection,
            "vlm": self.vlm,
            "vlm_model": self.vlm_model,
            "embed_model": self.embed_model,
            "embed_dim": self.embed_dim,
            "prompt_version": self.prompt_version,
            "read_quota": self.read_quota,
            "reads_per_question": self.reads_per_question,
            "allow_paid": self.allow_paid,
            "log_level": self.log_level,
            "release_id": self.release_id,
            "vlm_tier": self.vlm_tier,
            "vlm_rpm": self.vlm_rpm,
            "embed_text_chars": self.embed_text_chars,
            "safety_doc_types": list(self.safety_doc_types),
            "safety_topics": list(self.safety_topics),
            "fixture_dir": self.fixture_dir,
            "doc_store": self.doc_store,
            "replay": self.replay,
            "auth_configured": len(self.api_tokens),  # a count is not a credential; the name
            # avoids the redactor, which matches on token-shaped field names (logging.redact)
            "vlm_key_present": bool(self.vlm_key),
        }


def scrub_url(url: str) -> str:
    """Drop any userinfo before a URL reaches a log line (§15.1: no credential in a log)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<unparseable>"
    if "@" not in parts.netloc:
        return url
    host = parts.hostname or ""
    netloc = f"***@{host}:{parts.port}" if parts.port else f"***@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _require(env: Mapping[str, str], var: str) -> str:
    raw = (env.get(var) or "").strip()
    if not raw:
        raise MissingConfig(var)
    return raw


def _optional(env: Mapping[str, str], var: str, default: str) -> str:
    raw = env.get(var)
    return default if raw is None or raw.strip() == "" else raw.strip()


def _csv(raw: str) -> tuple[str, ...]:
    """A comma-separated list variable, trimmed and de-duplicated, order preserved."""
    return tuple(dict.fromkeys(value.strip() for value in raw.split(",") if value.strip()))


def _as_int(var: str, raw: str, *, minimum: int | None = None) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise InvalidConfig(var, f"expected an integer, got {raw!r}") from None
    if minimum is not None and value < minimum:
        raise InvalidConfig(var, f"must be >= {minimum}, got {value}")
    return value


def _as_bool(var: str, raw: str) -> bool:
    lowered = raw.lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise InvalidConfig(var, f"expected one of {sorted(_TRUE | _FALSE)}, got {raw!r}")


def _as_choice(var: str, raw: str, allowed: tuple[str, ...]) -> str:
    if raw not in allowed:
        raise InvalidConfig(var, f"expected one of {list(allowed)}, got {raw!r}")
    return raw


def load_config(env: Mapping[str, str] | None = None) -> Config:
    """Build the configuration from ``env`` (``os.environ`` by default).

    Raises :class:`MissingConfig` or :class:`InvalidConfig` naming the offending variable. Callers
    never catch these to carry on with a partial value: Spec §4.3 refuses to start instead.
    """
    env = os.environ if env is None else env

    port = _as_int("VSIR_PORT", _require(env, "VSIR_PORT"), minimum=1)
    if port > 65535:
        raise InvalidConfig("VSIR_PORT", f"must be <= 65535, got {port}")

    api_tokens = tuple(t.strip() for t in _require(env, "VSIR_API_TOKENS").split(",") if t.strip())
    if not api_tokens:
        raise InvalidConfig("VSIR_API_TOKENS", "no non-empty token in the comma-separated list")

    embed_dim = _as_int("VSIR_EMBED_DIM", _optional(env, "VSIR_EMBED_DIM", "1536"))
    if embed_dim not in EMBED_DIMS:
        raise InvalidConfig("VSIR_EMBED_DIM", f"expected one of {list(EMBED_DIMS)}, got {embed_dim}")

    return Config(
        port=port,
        qdrant_url=_require(env, "VSIR_QDRANT_URL"),
        collection=_require(env, "VSIR_COLLECTION"),
        vlm=_as_choice("VSIR_VLM", _require(env, "VSIR_VLM"), VLM_BACKENDS),
        vlm_model=_require(env, "VSIR_VLM_MODEL"),
        embed_model=_require(env, "VSIR_EMBED_MODEL"),
        prompt_version=_require(env, "VSIR_PROMPT_VERSION"),
        read_quota=_as_int("VSIR_READ_QUOTA", _require(env, "VSIR_READ_QUOTA"), minimum=0),
        allow_paid=_as_bool("VSIR_ALLOW_PAID", _require(env, "VSIR_ALLOW_PAID")),
        log_level=_as_choice(
            "VSIR_LOG_LEVEL", _require(env, "VSIR_LOG_LEVEL").upper(), LOG_LEVELS
        ),
        release_id=_require(env, "VSIR_RELEASE_ID"),
        embed_dim=embed_dim,
        runs_collection=_optional(env, "VSIR_RUNS_COLLECTION", "vsir_runs"),
        reads_per_question=_as_int(
            "VSIR_READS_PER_QUESTION", _optional(env, "VSIR_READS_PER_QUESTION", "3"), minimum=1
        ),
        fixture_dir=_optional(env, "VSIR_FIXTURE", ""),
        vlm_tier=_as_choice("VSIR_VLM_TIER", _optional(env, "VSIR_VLM_TIER", "standard"), VLM_TIERS),
        vlm_rpm=_as_int("VSIR_VLM_RPM", _optional(env, "VSIR_VLM_RPM", "60"), minimum=1),
        embed_text_chars=_as_int(
            "VSIR_EMBED_TEXT_CHARS", _optional(env, "VSIR_EMBED_TEXT_CHARS", "2000"), minimum=1
        ),
        doc_store=_optional(env, "VSIR_DOC_STORE", ""),
        safety_doc_types=_csv(_optional(env, "VSIR_SAFETY_DOC_TYPES", "")),
        safety_topics=_csv(_optional(env, "VSIR_SAFETY_TOPICS", "")),
        api_tokens=api_tokens,
        vlm_key=_optional(env, "VSIR_VLM_KEY", ""),
    )
