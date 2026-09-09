"""vsir — vision segmentation, index and retrieval (POC Part B).

One codebase, one image, three process types: ``web``, ``ingest-worker`` and one-off ``vsir``
admin commands all run from the same release (Spec §15 Factors I, V, VIII, XII). Modules are added
by the milestone that implements them, so the package is deliberately small at M0 — Spec §4.1 is a
map of where things go, not a checklist of files to create empty.
"""

__version__ = "0.1.0"
