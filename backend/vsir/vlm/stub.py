"""The replay backend (D10). Written net new; selected by ``VSIR_VLM=stub`` and nothing else.

This is the module that makes the rest of the system free to test. Spec §12.2 is absolute about
it: **L0–L3 and E2E must never call Gemini.** They run in replay mode — ``VSIR_VLM=stub`` plus
``VSIR_FIXTURE=<dir>`` — where both S2 extraction and ``read`` are served from responses frozen
under exactly the keys of §6.3, and a key the fixture does not hold is a typed ``fixture_miss``.

Three things it deliberately does **not** do, each of which is the failure it exists to prevent:

* **it never makes a live call.** A stub that fell back to the model on a miss would turn a free CI
  run into a billed one and make the suite depend on a credential nobody meant to give it;
* **it never fabricates a response.** A stub that synthesised a plausible ``WindowOut`` on a miss
  would make every green test downstream a statement about data no model ever produced — the most
  expensive kind of green there is;
* **it never looks at the pixels.** The rasters are on the request because the *key* was computed
  from them, and the key is what selects the frozen answer. A stub that inspected the images would
  be a second extractor, with its own opinions, in the path the tests trust.

**It is the same code path as production with a different attached service** (§15 Factor IV, X) —
not a test-only branch and not a monkeypatch. Nothing here reads a test-harness variable and
nothing branches on one — §12.5's conformance grep bans that shape outright, and it is right to:
the backend is a configuration lookup, so the path the tests exercise is the path that ships.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vsir import logging as vsir_logging
from vsir.config import Config
from vsir.vlm.cache import Entry, FixtureStore, VlmTruncated, VlmUnavailable
from vsir.vlm.client import Request

_log = vsir_logging.get_logger(__name__)


@dataclass(frozen=True)
class StubBackend:
    """Serves frozen responses out of one read-only directory, by key."""

    store: FixtureStore
    name: str = "stub"

    @classmethod
    def from_config(cls, cfg: Config) -> "StubBackend":
        """A stub without a fixture directory is refused, by name.

        Silently answering nothing would be the worst of the three options: a suite that skipped
        every fixture-consuming test would be a green run that asserted nothing, which is exactly
        what ``vsir demo exact --synthetic`` refuses for the M1 corpus.
        """
        if not cfg.fixture_dir:
            raise VlmUnavailable(
                "VSIR_VLM=stub needs VSIR_FIXTURE=<dir>: replay mode serves frozen responses by "
                "cache key, and with nowhere to read them from there is nothing to serve (D10)",
                vlm=cfg.vlm, fixture="",
            )
        root = Path(cfg.fixture_dir)
        if not root.is_dir():
            raise VlmUnavailable(
                f"VSIR_FIXTURE={cfg.fixture_dir} is not a directory: replay mode never makes a "
                f"live call, so a missing fixture directory is a refusal rather than a fallback",
                vlm=cfg.vlm, fixture=str(root),
            )
        return cls(store=FixtureStore(root))

    def generate(self, request: Request) -> Entry:
        """The frozen response for ``request.key``, verbatim, or :class:`FixtureMiss`."""
        entry = self.store.get(request.namespace, request.key)
        _log.info("vlm_replay", stage=request.stage, namespace=request.namespace,
                  cache_key=request.key, path=entry.path, bytes=len(entry.body),
                  finish_reason=entry.finish_reason, images=len(request.images))
        if entry.truncated:
            # The provenance sidecar recorded a call the provider cut off at the output ceiling.
            # Replay has to be able to reproduce that: it is a truncation on the wire rather than a
            # parse failure, and §6.2's repair — bisect and re-bill — is only exercised if the
            # frozen corpus can express it (F13).
            raise VlmTruncated(
                f"{request.label or request.stage}: the frozen response for {request.key} was "
                f"recorded as {entry.finish_reason} — bisect and re-bill, never keep a partial "
                f"window",
                cache_key=request.key, namespace=request.namespace,
                finish_reason=entry.finish_reason,
            )
        return entry
