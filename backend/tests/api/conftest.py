"""Shared setup for L2/L3 — the collection the test stack's Qdrant must hold.

An instance with no collection is deliberately **not ready** (§15.1), so every test that expects a
green `/ready` needs the collection to exist first. Creating it here, from the same
`core.indexed.create_collection` the CLI uses, is also the only way these tests prove the real
creation path rather than a fixture's idea of it.
"""
from __future__ import annotations

import os

import pytest
from qdrant_client import QdrantClient

from vsir.core.indexed import create_collection

QDRANT_URL = os.environ.get("VSIR_TEST_QDRANT_URL", "http://localhost:6335")
BASE_URL = os.environ.get("VSIR_TEST_BASE_URL", "http://localhost:8001")
COLLECTION = "vsir_pages"
EMBED_DIM = 1536


@pytest.fixture(scope="session")
def qdrant() -> QdrantClient:
    client = QdrantClient(url=QDRANT_URL, timeout=30, check_compatibility=False)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture(scope="session")
def pages_collection(qdrant: QdrantClient) -> str:
    """The collection, created from `INDEXED` exactly as `vsir doctor --create-collection` does."""
    name = f"{COLLECTION}_{EMBED_DIM}"
    create_collection(qdrant, name, EMBED_DIM, recreate=True)
    return name
