"""The VLM boundary: what a call *is*, and the Gemini backend that makes one.

Ported with changes from ``impl/app/segment.py``'s Gemini calls. What survives is the shape of the
call — structured output against a Pydantic schema at temperature 0, a retry budget that
distinguishes a transient failure from a bad request, and a truncation that is repaired by
bisecting the window rather than by keeping the partial answer. What changes is fourfold:

* **Rasters, not a PDF slice.** `impl` sliced the PDF and sent the fragment. §6.1 step 06 sends the
  window's **rasters at the pinned dpi 220**, which is what makes ``dpi`` and the ordered page
  image hashes honest inputs to ``extract_key`` (§6.3): the key describes the pixels the model
  actually saw. `impl`'s ``s2_input_mode`` recorded an input mode no code path implemented
  (register A3), and this is the mode.
* **The pin is re-verified here.** `vsir doctor` refuses a model id ending in the floating alias at
  boot (F11), and this backend refuses it again at call time. Two checks for one rule is not
  belt-and-braces: boot runs once per process and a long-lived worker can be handed a
  configuration by a caller that never went through it, so the check that matters is the one
  next to the spend (register B6).
* **A token bucket bounds the burst.** `impl` has jittered backoff and no rate limiter, so a
  full-corpus run's first move is to fire every window at once and then serve out its own 429s at
  exponentially increasing delay. The bucket makes the steady state deliberate instead.
* **No caching decision is taken here.** This module makes calls. Whether a call is needed at all
  is ``vlm/cache.py``'s question, asked before this module is reached — which is what lets the
  stub answer the same question from a frozen response (§15 Factor IV, D10).

**The prompts are files, versioned in lockstep with the key.** ``prompts/s1.md`` and
``prompts/s2.md`` carry the text; :data:`PROMPT_DIGESTS` carries the digest each released version
was published with. Editing a prompt without releasing a new ``VSIR_PROMPT_VERSION`` therefore
fails :func:`prompt` by name rather than serving cached output produced by different instructions —
which is the whole hazard ``prompt_version`` is in the cache key to prevent (F11).
"""
from __future__ import annotations

import hashlib
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Protocol, runtime_checkable

from google import genai
from google.genai import types
from pydantic import BaseModel

from vsir import logging as vsir_logging
from vsir.config import FLOATING_SUFFIX, Config
from vsir.vlm.cache import (EXTRACT, FACTS, READ, Entry, VlmCallFailed, VlmError, VlmTruncated,
                            VlmUnavailable)

_log = vsir_logging.get_logger(__name__)

#: Where the versioned prompt text lives. Files, in the image, released with the code — a prompt
#: is not configuration (§15 Factor III): changing one changes every cache key, so it is a release.
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

#: One stage per call the pipeline makes. ``read`` arrives with the paid read step (§7.2.6, U020);
#: asking for it before its prompt exists is a named refusal, not a fallback to another stage's.
PROMPT_STAGES: tuple[str, ...] = ("s1", "s2")

#: The digest each released prompt version was published with — ``sha256`` over the file's bytes.
#:
#: This is the guard the cache key cannot provide on its own. ``prompt_version`` is a *label*, and
#: a label only describes the text while the two move together; edit ``s2.md`` and leave the label
#: alone and every frozen response in the fixture, and every cached response in production, is
#: output produced by instructions that no longer exist. Recording the digest makes that edit fail
#: here, and the only way through is a new version — which re-keys every response by design.
PROMPT_DIGESTS = MappingProxyType({
    "s2-v1": MappingProxyType({
        "s1": "1aa9320abc7ef034c6291f826bf728a4b40b48482368cd727c2650a37f6793a7",
        "s2": "85f5b47fd4aaee08103b24c65cdc8534a7156b3b924f48f5b94ed885399c4f5c",
    }),
})

#: Ported verbatim from `impl`: the substrings that mark a failure worth trying again. Everything
#: else raises on the first attempt — a bad request is not worth four of them.
RETRYABLE: tuple[str, ...] = ("429", "500", "502", "503", "504", "resource_exhausted",
                              "unavailable", "deadline")

#: Ported from `impl`: four attempts, `min(2**attempt, 8)` seconds plus jitter between them.
MAX_ATTEMPTS = 4
BACKOFF_CEILING_S = 8.0

#: What the provider calls a response it cut off at the output ceiling. §6.2's first bisection
#: trigger, and the one that must never be mistaken for an answer.
TRUNCATED_FINISH_REASONS: tuple[str, ...] = ("MAX_TOKENS", "TRUNCATED")

#: Deterministic extraction. A temperature above zero would make ``extract_key`` a lie: the same
#: pages, model and prompt would return different structure on a re-run that the key calls a hit.
TEMPERATURE = 0.0


class PromptUnavailable(VlmError):
    """The requested prompt is not the released text for the configured version."""

    code = "prompt_unavailable"


class VlmTierUnsupported(VlmError):
    """``VSIR_VLM_TIER=batch`` was asked for and the batch submission path is not built.

    Named rather than silently downgraded. The tier exists because ingestion has no latency
    requirement and the Batch API is half the price (§6.3), so quietly serving a batch request from
    the standard endpoint bills a full-corpus run at twice the rate the cost basis assumes and
    reports success. The tier is deliberately **not** an ``extract_key`` input, so switching it
    re-bills nothing: a run started on `standard` can be finished on `batch` for free.
    """

    code = "vlm_tier_unsupported"


@dataclass(frozen=True)
class Prompt:
    """One stage's released instructions, and the digest that pins them to a version."""

    stage: str
    version: str
    text: str

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def prompt(stage: str, version: str, *, directory: Path | None = None) -> Prompt:
    """The released prompt for ``stage`` at ``version``, or a named refusal.

    Called only where a **live call** is about to be made. Replay never reaches it, which is
    correct: the instructions are an input to the call, and in replay mode there is no call — the
    version's effect is entirely in the cache key that found the frozen response (§6.3).
    """
    if stage not in PROMPT_STAGES:
        raise PromptUnavailable(
            f"no prompt stage {stage!r}: this release ships {list(PROMPT_STAGES)}",
            stage=stage, stages=list(PROMPT_STAGES),
        )
    released = PROMPT_DIGESTS.get(version)
    if released is None:
        raise PromptUnavailable(
            f"VSIR_PROMPT_VERSION={version} is not a released prompt version "
            f"(released: {sorted(PROMPT_DIGESTS)}) — a prompt is part of the release, and a "
            f"version with no text behind it would key a cache to instructions that do not exist",
            stage=stage, prompt_version=version, released=sorted(PROMPT_DIGESTS),
        )
    path = (directory or PROMPT_DIR) / f"{stage}.md"
    if not path.is_file():
        raise PromptUnavailable(f"{path} is missing from the release", stage=stage, path=str(path))
    found = Prompt(stage=stage, version=version, text=path.read_text(encoding="utf-8"))
    if found.digest != released[stage]:
        raise PromptUnavailable(
            f"{path} is not the text released as {version}: it hashes to {found.digest[:16]}… "
            f"and {version} was published as {released[stage][:16]}…. Release a new "
            f"VSIR_PROMPT_VERSION rather than editing a version in place — every cached and "
            f"frozen response under {version} was produced by the published text (F11)",
            stage=stage, prompt_version=version, path=str(path),
            found=found.digest, released=released[stage],
        )
    return found


@dataclass(frozen=True)
class Request:
    """One call to the boundary: which question, about which pixels, under which key.

    ``key`` is not used to *make* the call — it is carried so the backend that answers from a
    frozen response and the backend that answers from the model take the same argument, and so
    every log line and every error names the receipt (§6.3, D10).
    """

    namespace: str
    key: str
    stage: str
    schema: type[BaseModel]
    #: The window's rasters, in **absolute page order**, at the dpi that is in ``key``.
    images: tuple[bytes, ...] = ()
    #: The one line of context the model is given about where this excerpt sits. Never a fact the
    #: model is asked to report back: the page range is ours, from our own windowing (§6.4).
    hint: str = ""
    #: What to call this call in a log line or a refusal. Never part of the key.
    label: str = ""

    def __post_init__(self) -> None:
        if self.namespace not in (FACTS, EXTRACT, READ):
            raise ValueError(f"not a cache namespace: {self.namespace!r}")
        if not self.key:
            raise ValueError("a request carries its cache key: it is the receipt (§6.3)")


@runtime_checkable
class Backend(Protocol):
    """What both backends are. One method, and the same refusals (§15 Factor IV, X)."""

    name: str

    def generate(self, request: Request) -> Entry:
        """The **verbatim** response body, plus what the call reported about itself."""


class TokenBucket:
    """Requests per minute, refilled continuously. Bounds the burst; never bounds the total.

    Written net new. `impl` retries with jittered backoff and rate-limits nothing, so a
    full-corpus run's opening move is to fire every window at once and then serve out its own 429s
    at exponentially increasing delay — the provider's limiter standing in for one we did not
    write, at the cost of a wasted round trip per window in the stage that is 99 % of spend.

    Thread-safe because the embedding pool is a bounded ``ThreadPoolExecutor`` (§4.2) and the
    window fan-out is the same shape. There is no cross-process coordination and there is not meant
    to be: two workers are two buckets, and the provider's own limit is the backstop (D9 makes the
    same trade — a duplicated worker wastes money, it cannot corrupt anything).
    """

    def __init__(self, rate_per_minute: int, *, capacity: int | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if rate_per_minute < 1:
            raise ValueError(f"a rate limit is at least one call a minute, got {rate_per_minute}")
        self.rate_per_minute = rate_per_minute
        #: A burst of one minute's worth by default: the point is to stop a thundering herd, not to
        #: pace a small document into taking a minute.
        self.capacity = max(1, capacity if capacity is not None else rate_per_minute)
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._tokens = float(self.capacity)
        self._updated = clock()

    @property
    def available(self) -> float:
        """Tokens in the bucket right now. Reported, never branched on by a caller."""
        with self._lock:
            self._refill()
            return self._tokens

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._updated)
        self._updated = now
        self._tokens = min(float(self.capacity),
                           self._tokens + elapsed * self.rate_per_minute / 60.0)

    def take(self, tokens: int = 1) -> float:
        """Wait until ``tokens`` are available, then spend them. Returns the seconds waited."""
        if tokens < 1:
            raise ValueError(f"a call costs at least one token, got {tokens}")
        if tokens > self.capacity:
            raise ValueError(
                f"a single call cannot cost {tokens} tokens: the bucket holds {self.capacity}"
            )
        waited = 0.0
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return waited
                shortfall = tokens - self._tokens
                delay = shortfall * 60.0 / self.rate_per_minute
            self._sleep(delay)
            waited += delay


@dataclass
class GeminiBackend:
    """The live backend. Selected by ``VSIR_VLM=gemini`` and by nothing else (§15 Factor X)."""

    model: str
    prompt_version: str
    tier: str
    bucket: TokenBucket
    #: repr=False so no traceback, log line or error message can carry the credential (§15.1).
    key: str = field(repr=False, default="")
    prompt_dir: Path | None = None
    sleep: Callable[[float], None] = time.sleep
    #: Injected in one place so a test can drive the retry ladder without a network. Production
    #: leaves it None and the SDK client is built on first use, from the credential above.
    transport: Callable[..., Any] | None = None
    name: str = "gemini"
    #: The SDK client, built on first use by :meth:`_client` and held for the backend's life. Not
    #: part of the backend's identity, so it is excluded from `repr` and from comparison.
    _sdk_client: Any = field(default=None, repr=False, compare=False)

    @classmethod
    def from_config(cls, cfg: Config) -> "GeminiBackend":
        """Build the backend, refusing anything that would make its output untraceable."""
        if not cfg.vlm_key:
            raise VlmUnavailable(
                "VSIR_VLM=gemini needs VSIR_VLM_KEY: the credential arrives from the platform "
                "secret store at runtime, never from the image (§15 Factor III)",
                vlm=cfg.vlm,
            )
        return cls(model=_pinned(cfg.vlm_model), prompt_version=cfg.prompt_version,
                   tier=cfg.vlm_tier, bucket=TokenBucket(cfg.vlm_rpm), key=cfg.vlm_key)

    def generate(self, request: Request) -> Entry:
        """One live call, rate-limited, retried on a transient failure, verbatim on the way out."""
        if self.tier != "standard":
            raise VlmTierUnsupported(
                f"VSIR_VLM_TIER={self.tier} asks for the Batch API and this release implements the "
                f"standard endpoint only. The tier is not a cache-key input (§6.3), so a run "
                f"started on standard can be finished on batch for free once that path lands",
                tier=self.tier, cache_key=request.key,
            )
        # Before the bucket, and before the loop: an unpinned model id is a configuration
        # refusal, so it must neither spend a rate-limit token nor be reachable from inside the
        # retry ladder. It used to be checked in `_call`, where it was retried three times on the
        # strength of its own class name — "unavailable" is a RETRYABLE marker — and surfaced as
        # `vlm_call_failed` rather than the named refusal F11 asks for.
        model = _pinned(self.model)
        instructions = prompt(request.stage, self.prompt_version, directory=self.prompt_dir)
        parts = [types.Part.from_bytes(data=image, mime_type="image/png")
                 for image in request.images]
        if request.hint:
            parts.append(types.Part(text=request.hint))
        if not parts:
            raise ValueError("a call carries at least one raster or one line of text")

        waited = self.bucket.take()
        last: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self._call(request, parts, instructions, model=model)
            except VlmError:
                # One of ours, and therefore not transient: a typed refusal is the *answer*, not a
                # failure to get one. Re-raised before the retry test rather than after it,
                # because several of our codes contain a RETRYABLE substring and would otherwise
                # be retried on their name.
                raise
            except Exception as failure:  # noqa: BLE001 - the SDK raises a wide range
                last = failure
                blob = f"{type(failure).__name__} {failure}".lower()
                if not any(marker in blob for marker in RETRYABLE) or attempt == MAX_ATTEMPTS:
                    raise VlmCallFailed(
                        f"{request.label or request.stage}: {type(failure).__name__}: {failure}",
                        cache_key=request.key, namespace=request.namespace,
                        attempts=attempt,
                    ) from failure
                delay = min(2.0 ** (attempt - 1), BACKOFF_CEILING_S) + random.random()
                _log.warning("vlm_retry", stage=request.stage, cache_key=request.key, attempt=attempt,
                             attempts=MAX_ATTEMPTS, delay_s=round(delay, 2),
                             detail=type(failure).__name__)
                self.sleep(delay)
                continue

            finish, usage, body = _unpack(response)
            entry = Entry(key=request.key, namespace=request.namespace, body=body, origin="model",
                          finish_reason=finish, usage=usage)
            _log.info("vlm_call", stage=request.stage, namespace=request.namespace,
                      cache_key=request.key, model=self.model, prompt_version=self.prompt_version,
                      tier=self.tier, images=len(request.images), attempt=attempt,
                      rate_limit_wait_s=round(waited, 3), finish_reason=finish, **usage)
            if entry.truncated:
                # Never keep it. A truncated window is a partial answer that reports success, and
                # §6.2's repair is to halve the window and re-bill — never to pad (F13).
                raise VlmTruncated(
                    f"{request.label or request.stage}: the response stopped at the output "
                    f"ceiling ({finish}) — bisect and re-bill, never keep a partial window",
                    cache_key=request.key, namespace=request.namespace,
                    finish_reason=finish,
                )
            return entry
        raise VlmCallFailed(f"{request.label or request.stage}: {last}",
                            cache_key=request.key, namespace=request.namespace,
                            attempts=MAX_ATTEMPTS)

    def _call(self, request: Request, parts: list[Any], instructions: Prompt, *,
              model: str) -> Any:
        """The one place the SDK is touched. Structured output, temperature 0, one Content.

        ``model`` arrives already checked against the pin: resolving it here would put a
        configuration refusal inside the retry ladder (see :meth:`generate`).
        """
        transport = self.transport or self._sdk
        return transport(
            model=model,
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(
                system_instruction=instructions.text,
                response_mime_type="application/json",
                response_schema=response_schema(request.schema),
                temperature=TEMPERATURE,
            ),
        )

    def _client(self) -> Any:
        """One SDK client per backend, built on first use and kept.

        **Not one per call.** `genai.Client(...).models.generate_content(...)` reads as a harmless
        one-liner and is not: the client owns an `httpx` transport and closes it when it is
        finalised, and as a temporary it can be collected while the request it started is still in
        flight. The observable form of that is `RuntimeError: Cannot send a request, as the client
        has been closed` on the *first live S1 call* — invisible to every test, because the stub
        backend never builds a client and the retry ladder is driven through `transport`.

        Keeping it is also the correct thing on its own terms: the connection pool and TLS session
        are reused across a document's windows instead of being rebuilt per call.
        """
        if self._sdk_client is None:
            self._sdk_client = genai.Client(api_key=self.key)
        return self._sdk_client

    def _sdk(self, **call: Any) -> Any:
        return self._client().models.generate_content(**call)


#: JSON Schema keywords `response_schema` has no field for. Passing one is a `400
#: INVALID_ARGUMENT` naming it, so this list is what the API accepts rather than a preference.
#: `additionalProperties` is the one that matters: every model here sets `extra="forbid"` — which
#: is right for *parsing*, since an unexpected field in a paid response is something to refuse
#: rather than drop — and Pydantic renders that as `additionalProperties: false`.
UNSUPPORTED_SCHEMA_KEYS = frozenset({"additionalProperties", "title", "default", "$schema"})


def response_schema(model: type[BaseModel]) -> dict[str, Any]:
    """A Pydantic model as a schema `response_schema` accepts: refs inlined, extras dropped.

    The model class used to be handed to the SDK directly, which reads as the obvious thing and
    fails on the **first live call** with `400 INVALID_ARGUMENT: Unknown name
    "additional_properties" at 'generation_config.response_schema'`. Nothing caught it earlier
    because the stub backend never builds a request and the retry ladder is driven through
    `transport`, so no test had ever produced this payload.

    Two transformations, and no others — anything else would be this module quietly deciding what
    the model may be asked for:

    * **`$ref`/`$defs` are inlined.** A nested model (`DocumentFacts.toc` is a `list[TocEntry]`)
      becomes a `$ref` into `$defs`, and the schema is sent as a tree with no document to resolve
      a pointer against.
    * **Keys with no field on `Schema` are dropped**, per :data:`UNSUPPORTED_SCHEMA_KEYS`.

    The **strict class is still what parses the response** — this is only what describes the shape
    on the way out, so `extra="forbid"` keeps refusing an unexpected field on the way back in.
    """
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].rsplit("/", 1)[-1]
                if name not in defs:
                    raise PromptUnavailable(
                        f"{model.__name__}'s schema references {name!r}, which is not in its own "
                        f"$defs: the schema cannot be sent as a self-contained tree",
                        stage=model.__name__)
                # The sibling keys win: a `$ref` alongside `description` means this use of the
                # definition, described here.
                merged = {**defs[name], **{k: v for k, v in node.items() if k != "$ref"}}
                return resolve(merged)
            return {key: resolve(value) for key, value in node.items()
                    if key not in UNSUPPORTED_SCHEMA_KEYS}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(raw)


def _pinned(model: str) -> str:
    """Re-verify the pin at the point of spend (register B6, F11).

    When a provider repoints a floating alias at a new model version the key string does not change
    but the model behind it does, so a cache serves extractions produced by a *different* model
    under a name that claims otherwise. That is precisely the failure the key exists to prevent.
    """
    if not model:
        raise VlmUnavailable("no VLM model id is configured", model=model)
    if model.endswith(FLOATING_SUFFIX):
        raise VlmUnavailable(
            f"model id {model!r} ends in {FLOATING_SUFFIX}: pin the version (§4.3, F11). "
            f"The previous implementation ran a floating alias and warned about it in its own "
            f"configuration comment without closing it (register B6)",
            model=model, suffix=FLOATING_SUFFIX,
        )
    return model


def _unpack(response: Any) -> tuple[str, dict[str, int], str]:
    """``(finish_reason, usage, verbatim body)`` from an SDK response, defensively.

    Defensively because the three things this needs live in optional, versioned places on the
    response object, and a missing one must not read as a *successful empty* extraction — a window
    that came back with no body and no finish reason has to fail, not publish zero pages.
    """
    candidates = getattr(response, "candidates", None) or ()
    reason = getattr(candidates[0], "finish_reason", "") if candidates else ""
    finish = getattr(reason, "name", None) or str(reason or "STOP")

    metadata = getattr(response, "usage_metadata", None)
    usage = {
        "prompt_tokens": int(getattr(metadata, "prompt_token_count", 0) or 0),
        "output_tokens": int(getattr(metadata, "candidates_token_count", 0) or 0),
        "total_tokens": int(getattr(metadata, "total_token_count", 0) or 0),
    }

    body = getattr(response, "text", None)
    if not body:
        parsed = getattr(response, "parsed", None)
        body = parsed.model_dump_json() if isinstance(parsed, BaseModel) else ""
    if not body:
        raise VlmCallFailed("the response carried no body", finish_reason=finish, **usage)
    return finish, usage, body


def hint(*, start: int, end: int, page_count: int) -> str:
    """The one line of context a window gets. Our own arithmetic, never asked back.

    `impl` adds a second sentence on a Level 2 window warning that a unit may already be open —
    the carry chain that makes that rung sequential, and that v1 does not implement (§2.5 B, §6.2).
    Level 0 and Level 1 windows are cut on the document's own structure, so there is nothing to
    carry and the windows stay parallelisable.
    """
    return f"This excerpt is pages {start}-{end} of {page_count}."
