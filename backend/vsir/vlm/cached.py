"""The read/write cache in front of the boundary — what makes `--resume` free (§6.3, D9, U025).

`vlm/cache.py::ControlPlaneStore` is the store; this is the :class:`~vsir.vlm.client.Backend` that
uses it. `serve/tools/read.py` has done the same thing inline since U020 — *ask the store, call the
model on a miss, write the answer back* — and step 06 needs exactly that behaviour, so it is a
wrapper rather than a second copy of the three lines.

**Why a wrapper and not a step**, the same reason :mod:`vsir.vlm.record` gives: S1 and S2 are called
from two different places and §6.2's bisection makes more calls mid-flight, each under its own key.
A cache wired per step would serve the windows a clean run produced and re-bill the halves a
bisected one did — which is the run whose receipts are most worth keeping. Wrapping the boundary
catches every call by construction, including the halves.

**This is what a resume is.** Without it, `vsir ingest --resume <run_id>` re-runs step 06 from
window 1 and pays for every window the killed run had already finished; the run record says which
windows were done, but a window state is not a window's answer. With it, the killed run's finished
windows come back from `vsir_runs` under the keys they were billed under, and the resume pays for
at most the one window that was in flight (§15 Factor IX, F17). The register's **E2** entry is the
same failure seen from `impl`: a restart stranded a paid run with nothing to resume from.

**It wraps the stub too, and that is deliberate** (§15 Factor IV, X). Replay costs nothing, so
caching it saves nothing — but a cache that is only in the path when the expensive backend is
selected is a code path the free test levels never exercise, and the resume this exists for would
then be proven only by a run nobody can afford to make. `origin` tells the two apart in the event
stream exactly as it does for `read`: `replay` the first time, `cache` the second.

**A cache write is not part of the answer.** :meth:`ControlPlaneStore.put` swallows its own
failures and logs them, so a store that will not take the entry costs the next run a re-bill and
costs this one nothing. A failure on the way *out* is left to raise — guessing *"probably not
cached"* during an outage is how an outage becomes an unmetered afternoon.
"""
from __future__ import annotations

from dataclasses import dataclass

from vsir import logging as vsir_logging
from vsir.vlm.cache import ControlPlaneStore, Entry
from vsir.vlm.client import Backend, Request

_log = vsir_logging.get_logger(__name__)


@dataclass(frozen=True)
class CachingBackend:
    """Wraps a backend with the durable store of §6.3. Reads before it calls, writes after."""

    inner: Backend
    store: ControlPlaneStore
    vlm_model: str = ""
    prompt_version: str = ""

    @property
    def name(self) -> str:
        """The wrapped backend's name. A cache is not a backend anyone selects (§15 X)."""
        return getattr(self.inner, "name", "unknown")

    @property
    def recorded(self) -> list:
        """The recorder's tally, if one is underneath. Composition order must not hide it.

        `vsir ingest --record` reports ``len(backend.recorded)`` and the CLI wraps the recorder
        first so it freezes what the model actually answered — a cache hit is not a receipt. This
        property is what keeps that tally reachable through the outer wrapper instead of making
        the CLI know which order the two were composed in.
        """
        return list(getattr(self.inner, "recorded", ()))

    def generate(self, request: Request) -> Entry:
        """The cached response for this key, or the wrapped backend's — and then the cache."""
        entry = self.store.get(request.namespace, request.key)
        if entry is not None:
            _log.info("vlm_cache_hit", stage=request.stage, namespace=request.namespace,
                      cache_key=request.key, bytes=len(entry.body), label=request.label)
            return entry
        entry = self.inner.generate(request)
        self.store.put(entry, vlm_model=self.vlm_model, prompt_version=self.prompt_version)
        return entry


def caching(inner: Backend, client, collection: str, *, vlm_model: str = "",
            prompt_version: str = "") -> CachingBackend:
    """Wrap ``inner`` so every response it gives is read from and written to ``collection``."""
    return CachingBackend(inner=inner, store=ControlPlaneStore(client, collection),
                          vlm_model=vlm_model, prompt_version=prompt_version)
