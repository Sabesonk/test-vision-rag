"""The four content-addressable cache keys of Spec §6.3, and the store they name.

A cache key is a **receipt**. It answers one question — *"has this exact question already been
asked of this exact model?"* — and it earns its keep only if every input that can change the
answer is on it and nothing else is. Get that wrong in either direction and the failure is
expensive rather than noisy: an input missing from the key serves output from a *different* model
or a *different* prompt (F11), and an input on it that cannot change the answer re-bills a
full-corpus run for nothing.

```
facts_key   = sha256( document content hash ‖ resolved vlm model id ‖ prompt_version )
extract_key = sha256( ordered page image hashes ‖ resolved vlm model id ‖ prompt_version
                      ‖ dpi ‖ schema hash )
read_key    = extract_key inputs ‖ question
embed_key   = sha256( composition version ‖ embed model id ‖ composed string )
```

Four deliberate differences from `impl`, each of which closes a register item:

* **S1 is cached at all.** `impl` caches S2 and not S1, and `facts.toc` is what *chooses the
  window ladder* — so every re-run re-bills the cheap call and a different contents list silently
  re-cuts the document and re-bills all of S2 behind it (register B2). ``facts_key`` makes the
  ladder reproducible.
* **``extract_key`` is keyed on the ordered page image hashes**, not on the file hash plus a plan
  hash. Strictly stronger: the key depends on the pixels the model will actually see, so two
  windows of one document can never collide.
* **``s2_input_mode`` is gone and ``dpi`` is in.** `impl` recorded a mode (``"render@300"``) no
  code path implemented (register A3). The dpi is a fact about the render that did happen, and
  since §6.1 step 06 sends **rasters**, it changes what the model sees.
* **The schema is hashed, not versioned by hand.** `impl`'s ``SCHEMA_VERSION`` integer is correct
  only while somebody remembers to bump it (register B1's cousin).

**``VSIR_VLM_TIER`` is deliberately not an input to any of them.** Batch and standard produce the
same output, so putting the tier in a key would re-bill a whole corpus for choosing the 50 %
discount (§6.3).

**What the store is, and is not.** In production the entries live beside the run in the ``vsir_runs``
control plane (D9, U011) — never on the instance's filesystem (§15.2). In replay mode (D10) they
come from ``VSIR_FIXTURE``, a read-only directory of frozen responses checked into the repository,
and a key that is not in it is a typed :class:`FixtureMiss` — never a live call, never a fabricated
response. Both are the *same* code path with a different attached service (§15 Factor IV).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from vsir.config import COMPOSITION_VERSION

#: The three namespaces a frozen response can live under, and the subdirectory each one uses.
#: One namespace per *call*, not per model: two calls that ask different questions must not be
#: able to collide even if their keys somehow did.
FACTS = "facts"
EXTRACT = "extract"
READ = "read"
NAMESPACES: tuple[str, ...] = (FACTS, EXTRACT, READ)

#: The separator between key inputs.
#:
#: Each input is length-prefixed before it is joined, which is not decoration. A plain separator
#: is ambiguous: ``("a|b", "c")`` and ``("a", "b|c")`` concatenate to the same string and would
#: therefore share a key, and one of those inputs — ``prompt_version`` — is operator-supplied.
#: A key that two different configurations can collide on is worse than no key, because the
#: collision serves one configuration's output as the other's and reports a cache hit (F11).
_SEP = "|"


class VlmError(RuntimeError):
    """A typed refusal from the VLM boundary, with a machine-readable code.

    The code is the contract, exactly as it is for the tool surface (§7.3) and the windowing step:
    an operator switches on ``fixture_miss``, not on prose, and the details name the key and the
    directory so the next attempt can be *different* rather than a retry of the same one.
    """

    code = "vlm_error"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        return {"error": self.code, "detail": self.message, **self.details}


class FixtureMiss(VlmError):
    """Replay mode was asked for a key the fixture does not hold (D10).

    This is the one refusal the whole replay design exists to make loud. The two alternatives are
    both worse than an error: a live call turns a free test suite into a billed one and makes CI
    depend on a credential, and a fabricated response makes every green test downstream a
    statement about data no model ever produced.
    """

    code = "fixture_miss"


class VlmUnavailable(VlmError):
    """The configured backend cannot run: no credential, no fixture directory, no such backend."""

    code = "vlm_backend_unavailable"


class VlmTruncated(VlmError):
    """The response stopped at the output-token ceiling. A §6.2 bisection trigger, never a keep."""

    code = "vlm_truncated"


class VlmSchemaInvalid(VlmError):
    """The response does not validate against the demanded schema. Also a bisection trigger."""

    code = "vlm_schema_invalid"


class VlmCallFailed(VlmError):
    """The call did not come back, after the retry budget. Not a bisection trigger: retrying a
    truncation is free money for the provider, but retrying a 503 is the correct response."""

    code = "vlm_call_failed"


def _digest(*inputs: str) -> str:
    """``sha256`` over the length-prefixed concatenation of the inputs (§6.3's ``‖``)."""
    return hashlib.sha256(
        _SEP.join(f"{len(value)}:{value}" for value in inputs).encode("utf-8")
    ).hexdigest()


def facts_key(content_hash: str, *, vlm_model: str, prompt_version: str) -> str:
    """§6.3 — ``sha256(document content hash ‖ resolved vlm model id ‖ prompt_version)``.

    Cached **per document**, which is the fix for register B2: without it every re-run re-bills S1
    and, because S1's contents list picks the ladder, a different answer silently re-cuts the
    document and re-bills all of S2 behind it.
    """
    if not content_hash:
        raise ValueError("facts_key needs the document's content hash")
    return _digest(content_hash, vlm_model, prompt_version)


def extract_key(page_hashes: Sequence[str], *, vlm_model: str, prompt_version: str,
                dpi: int, schema_hash: str) -> str:
    """§6.3 — ``sha256(ordered page image hashes ‖ model ‖ prompt_version ‖ dpi ‖ schema hash)``.

    The hashes are **ordered**: a window is the pages in reading order, and a model shown the same
    pages in a different order is being asked a different question.
    """
    if not page_hashes:
        raise ValueError("extract_key needs at least one page image hash")
    return _digest(",".join(page_hashes), vlm_model, prompt_version, str(dpi), schema_hash)


def read_key(page_hashes: Sequence[str], *, vlm_model: str, prompt_version: str,
             dpi: int, schema_hash: str, question: str) -> str:
    """§6.3 — ``extract_key`` inputs ‖ question. **A new question is a cache miss** (F19).

    That is the whole mechanism F19 rests on, and it is why ``read`` cannot let a caller choose the
    dpi (§7.2.6): a dpi the caller controls is an input to this key that the caller can vary for
    free, so the same question at three dpis would bill three times for one answer.
    """
    if not page_hashes:
        raise ValueError("read_key needs at least one page image hash")
    if not question.strip():
        raise ValueError("read_key needs a question: `read` without one is `fetch` (§7.2.5)")
    return _digest(",".join(page_hashes), vlm_model, prompt_version, str(dpi), schema_hash,
                   question)


def embed_key(composed: str, *, embed_model: str,
              composition_version: str = COMPOSITION_VERSION) -> str:
    """§6.3 — ``sha256(composition version ‖ embed model id ‖ composed string)``.

    `impl` bills one vector per page on **every** run — 142 pages today, 1,440 for the manual it
    cannot ingest (register B5). Along with ``facts_key`` this is what makes "free replay" free.

    ``dim`` is not an input, and that is the spec's design rather than an omission: MRL truncation
    means a change of ``dim`` is a change of **collection** (§6.6, §5.5), so two dims never share a
    namespace to be confused inside. What guards that is the fingerprint, not this key.
    """
    if not composed:
        raise ValueError("embed_key needs the composed string")
    return _digest(composition_version, embed_model, composed)


@dataclass(frozen=True)
class Entry:
    """One frozen response, as it came back: the verbatim body plus what the call reported.

    The body is kept **verbatim** and nothing else is kept, which is the decision the rest of the
    pipeline rests on. Caching a processed ``PageRecord`` instead looks equivalent — it is smaller
    and closer to what the caller wants — but it makes every downstream change unreplayable,
    because the only way to re-derive is to buy the paid call again. Keep the receipt, not your
    summary of it.

    ``finish_reason`` and ``usage`` are the register B1 provenance sidecar: given a bare
    ``{"pages": [...]}`` file you cannot tell which model, prompt or page range produced it, and
    once ``prompt_version`` moves the old files become unidentifiable orphans. They also make one
    replay case reachable that is otherwise not: a call the provider cut off at the output ceiling
    is a truncation on the wire, not a parse error, and replay has to be able to reproduce it.
    """

    key: str
    namespace: str
    body: str
    origin: str = "replay"
    finish_reason: str = "STOP"
    usage: Mapping[str, int] | None = None
    path: str = ""

    @property
    def truncated(self) -> bool:
        """Whether the call stopped at the output ceiling — a §6.2 bisection trigger."""
        return self.finish_reason.upper() in ("MAX_TOKENS", "TRUNCATED")


@dataclass(frozen=True)
class FixtureStore:
    """A read-only content-addressable directory of frozen responses (D10).

    Read-only by design: replay must never be able to *fill* its own cache, or a single live call
    made by accident would be frozen into the repository as though it had been reviewed. The one
    writer is the corpus generator, which runs as its own process (§15 Factor XII) and calls
    :func:`write`.
    """

    root: Path

    def directory(self, namespace: str) -> Path:
        if namespace not in NAMESPACES:
            raise ValueError(f"not a cache namespace: {namespace!r} (expected {list(NAMESPACES)})")
        return self.root / namespace

    def path(self, namespace: str, key: str) -> Path:
        """Where a key's verbatim response lives. Keyed on the key **alone**.

        No revision, no run id, no doc_id: `impl` put the revision in the path, so correcting a
        metadata field moved the whole store and re-billed ~99 % of extraction spend. The key
        already carries the content hash, so the path needs nothing else.
        """
        return self.directory(namespace) / f"{key}.json"

    def meta_path(self, namespace: str, key: str) -> Path:
        return self.directory(namespace) / f"{key}.meta.json"

    def get(self, namespace: str, key: str) -> Entry:
        """The frozen response, or :class:`FixtureMiss`. Never a fabricated body."""
        body_path = self.path(namespace, key)
        if not body_path.is_file():
            raise FixtureMiss(
                f"no frozen {namespace} response for key {key} under {body_path.parent}: "
                f"replay mode never makes a live call and never invents one (D10)",
                namespace=namespace, cache_key=key,
                fixture=str(body_path.parent),
            )
        meta: dict[str, Any] = {}
        meta_path = self.meta_path(namespace, key)
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        usage = meta.get("usage")
        return Entry(
            key=key, namespace=namespace, body=body_path.read_text(encoding="utf-8"),
            origin="replay", finish_reason=str(meta.get("finish_reason", "STOP")),
            usage={str(k): int(v) for k, v in usage.items()} if isinstance(usage, dict) else None,
            path=str(body_path),
        )

    def has(self, namespace: str, key: str) -> bool:
        return self.path(namespace, key).is_file()


def write(root: Path, namespace: str, key: str, body: str,
          *, meta: Mapping[str, Any] | None = None) -> Path:
    """Freeze one response into a fixture directory. The **generator's** door, not the pipeline's.

    Kept a module function rather than a :class:`FixtureStore` method on purpose: the store a
    running process holds is read-only, and the only thing that may add to a fixture is the
    corpus producer — ``python -m vsir.eval.synthetic_pdf`` at M2a, the one paid ingest at M2b.
    """
    store = FixtureStore(root)
    destination = store.path(namespace, key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(body, encoding="utf-8")
    if meta:
        store.meta_path(namespace, key).write_text(
            json.dumps(dict(meta), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination
