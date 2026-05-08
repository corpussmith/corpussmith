"""Pytest session config.

Two safeties applied to every test:

1. **No real network.** Production ``expand()`` calls ``enrich_from_title``,
   which would hit OpenAlex. We replace the underlying HTTP fetcher with a
   ``URLError``-raising stub so the enricher's offline path is exercised.
   Set ``ENABLE_NETWORK_TESTS=1`` to opt in to real network calls.

2. **No real concept cache.** ``enrich_from_title`` reads / writes
   ``~/.corpussmith/concept_cache.jsonl`` by default. We redirect the cache
   to a per-test temp directory so test runs cannot pollute (or be polluted
   by) the user's real cache.
"""

from __future__ import annotations

import os
import urllib.error

import pytest


@pytest.fixture(autouse=True)
def _block_real_openalex(monkeypatch):
    if os.environ.get("ENABLE_NETWORK_TESTS") == "1":
        return

    def _no_network(url, headers, timeout):
        raise urllib.error.URLError(
            "network blocked in tests — set ENABLE_NETWORK_TESTS=1 to allow"
        )

    monkeypatch.setattr(
        "corpussmith.search.enrich._http_fetch",
        _no_network,
    )
    # Same block for MeSH validation (Stage 12).
    monkeypatch.setattr(
        "corpussmith.search.mesh._http_fetch",
        _no_network,
    )


@pytest.fixture(autouse=True)
def _isolate_concept_cache(tmp_path, monkeypatch):
    """Redirect the local concept cache to a per-test temp directory."""
    monkeypatch.setenv("SCHOLARFORGE_CACHE_DIR", str(tmp_path / "sf_cache"))
