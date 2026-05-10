"""Tests for the local concept cache (Stage 11c).

The cache is a TF-IDF nearest-neighbour over past `(title, concepts)` pairs
saved to ``~/.corpussmith/concept_cache.jsonl``. The conftest redirects the
cache to a per-test tmp dir so we never pollute the user's real cache.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from corpussmith.search.concept_cache import (
    CachedRecord,
    append,
    cache_path,
    load_all,
    lookup,
    stats,
)
from corpussmith.search.enrich import (
    EnrichedConcept,
    EnrichmentResult,
    enrich_from_title,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _mk_result(concepts, keywords=()):
    return EnrichmentResult(
        concepts=[EnrichedConcept(**c) for c in concepts],
        keywords=[EnrichedConcept(**k) for k in keywords],
        sample_titles=[],
    )


ADHD_CONCEPTS = [
    dict(name="Attention deficit hyperactivity disorder",
         cross_paper_count=8, avg_score=0.66,
         openalex_id="C2779394", level=2),
    dict(name="Cognitive behavioral therapy",
         cross_paper_count=4, avg_score=0.55,
         openalex_id="C2780665704", level=3),
    dict(name="Mindfulness",
         cross_paper_count=3, avg_score=0.58,
         openalex_id="C29000378", level=2),
]

TRUFFLE_CONCEPTS = [
    dict(name="Truffle", cross_paper_count=4, avg_score=0.94,
         openalex_id="C2775844422", level=2),
    dict(name="Ecology", cross_paper_count=6, avg_score=0.43,
         openalex_id="C18903297", level=1),
]


# ─────────────────────────────────────────────────────────────────────────────
# Append / load
# ─────────────────────────────────────────────────────────────────────────────

class CachePersistenceTests(unittest.TestCase):
    def test_append_creates_file(self):
        self.assertFalse(cache_path().exists())
        append("ADHD non-pharmacological treatment review",
               _mk_result(ADHD_CONCEPTS))
        self.assertTrue(cache_path().exists())
        records = load_all()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].title,
                         "ADHD non-pharmacological treatment review")
        self.assertEqual(len(records[0].concepts), 3)

    def test_append_skips_empty_results(self):
        append("nothing", EnrichmentResult())
        self.assertFalse(cache_path().exists())

    def test_append_skips_failed_results(self):
        append("nothing", EnrichmentResult(error="boom"))
        self.assertFalse(cache_path().exists())

    def test_multiple_records_each_one_line(self):
        append("a", _mk_result(ADHD_CONCEPTS))
        append("b", _mk_result(TRUFFLE_CONCEPTS))
        with cache_path().open() as f:
            lines = [l for l in f if l.strip()]
        self.assertEqual(len(lines), 2)


# ─────────────────────────────────────────────────────────────────────────────
# Lookup — TF-IDF semantics
# ─────────────────────────────────────────────────────────────────────────────

class CacheLookupTests(unittest.TestCase):
    """The min-cache-records floor is bypassed in these tests via
    ``min_cache_records=1`` so we can exercise the matching logic on small
    fixtures. Production keeps the floor at 8 to suppress IDF degeneracy on
    fresh installs."""

    def setUp(self):
        # Build a small but realistic cache.
        append("Non-pharmacological treatment of ADHD overview",
               _mk_result(ADHD_CONCEPTS))
        append("Cognitive behavioral therapy in ADHD adolescents",
               _mk_result(ADHD_CONCEPTS))
        append("Mindfulness-based interventions for adult ADHD",
               _mk_result(ADHD_CONCEPTS))
        append("Tuber aestivum ecology in oak forests",
               _mk_result(TRUFFLE_CONCEPTS))
        append("Distribution of summer truffle in Mediterranean ecosystems",
               _mk_result(TRUFFLE_CONCEPTS))

    def test_returns_none_when_cache_empty(self):
        os.environ["CORPUSSMITH_CACHE_DIR"] = "/tmp/sf_test_empty_cache_xyz"
        try:
            result = lookup("anything", min_cache_records=1)
            self.assertIsNone(result)
        finally:
            del os.environ["CORPUSSMITH_CACHE_DIR"]

    def test_close_match_returns_concepts(self):
        result = lookup("Non-pharmacological treatments for ADHD in adults",
                        min_cache_records=1, min_similarity=0.25)
        self.assertIsNotNone(result)
        self.assertTrue(result.ok)
        names = {c.name for c in result.concepts}
        self.assertIn("Attention deficit hyperactivity disorder", names)

    def test_unrelated_query_returns_none(self):
        result = lookup("quantum chromodynamics lattice gauge symmetries",
                        min_cache_records=1)
        self.assertIsNone(result)

    def test_returns_neighbours_only_above_threshold(self):
        result = lookup("foo bar baz", min_similarity=0.5,
                        min_cache_records=1)
        self.assertIsNone(result)

    def test_cross_neighbour_count_filters_singletons(self):
        append("Quantum chromodynamics lattice gauge",
               _mk_result([dict(name="Quantum field theory",
                                cross_paper_count=1, avg_score=0.9,
                                openalex_id="CXXX", level=2)]))
        result = lookup("ADHD non-pharmacological treatment",
                        min_cache_records=1, min_similarity=0.25)
        self.assertIsNotNone(result)
        names = {c.name for c in result.concepts}
        self.assertNotIn("Quantum field theory", names)

    def test_source_marker_is_cache(self):
        result = lookup("Non-pharmacological treatments for ADHD",
                        min_cache_records=1, min_similarity=0.25)
        self.assertIsNotNone(result)
        for c in result.concepts:
            self.assertTrue(c.source.startswith("cache:"),
                            f"expected cache: source, got {c.source}")

    def test_sample_titles_show_provenance(self):
        result = lookup("Non-pharmacological treatments for ADHD",
                        min_cache_records=1, min_similarity=0.25)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(len(result.sample_titles), 1)
        self.assertIn("sim=", result.sample_titles[0])

    def test_min_cache_records_floor_skips_tiny_cache(self):
        # With the production floor of 8 records and only 5 here, lookup
        # must return None even on an obvious near-match.
        result = lookup("Non-pharmacological treatments for ADHD")
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# Integration with enrich_from_title
# ─────────────────────────────────────────────────────────────────────────────

class EnrichWithCacheIntegrationTests(unittest.TestCase):
    def test_first_call_misses_cache_then_writes_it(self):
        fetched = []

        def fake_fetch(url, headers, timeout):
            fetched.append(url)
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "title": "ADHD review",
                        "concepts": [
                            {"display_name": "Attention deficit hyperactivity disorder",
                             "score": 0.91, "id": "https://openalex.org/C2779394",
                             "level": 2},
                        ],
                        "keywords": [],
                    },
                    {
                        "id": "https://openalex.org/W2",
                        "title": "ADHD therapy",
                        "concepts": [
                            {"display_name": "Attention deficit hyperactivity disorder",
                             "score": 0.88, "id": "https://openalex.org/C2779394",
                             "level": 2},
                        ],
                        "keywords": [],
                    },
                ]
            }

        result = enrich_from_title(
            "Non-pharmacological treatment of ADHD",
            fetcher=fake_fetch,
        )
        self.assertTrue(result.ok)
        # Network was hit once.
        self.assertEqual(len(fetched), 1)
        # Cache now has one record.
        self.assertEqual(len(load_all()), 1)

    def test_second_similar_call_hits_cache_no_network(self):
        # Pre-populate enough records to clear the min-cache-records floor.
        # We seed 8 ADHD-flavoured records and 2 unrelated ones so IDF has
        # enough variety to discriminate; production behaviour matches.
        for i in range(8):
            append(f"ADHD non-pharmacological treatment overview part {i}",
                   _mk_result(ADHD_CONCEPTS))
        append("Tuber aestivum oak forests", _mk_result(TRUFFLE_CONCEPTS))
        append("Distribution of summer truffle", _mk_result(TRUFFLE_CONCEPTS))

        called = []

        def fetcher_should_not_be_called(url, headers, timeout):
            called.append(url)
            raise AssertionError("network should not be hit on cache hit")

        result = enrich_from_title(
            "Non-pharmacological treatment of ADHD: review",
            fetcher=fetcher_should_not_be_called,
        )
        self.assertTrue(result.ok)
        self.assertEqual(called, [])
        # Source must indicate cache provenance.
        self.assertTrue(any(c.source.startswith("cache:") for c in result.concepts))

    def test_use_cache_false_bypasses_cache(self):
        for i in range(8):
            append(f"ADHD non-pharmacological treatment overview {i}",
                   _mk_result(ADHD_CONCEPTS))

        def fake_fetch(url, headers, timeout):
            return {"results": []}

        # Even with a cache hit available, use_cache=False forces network.
        result = enrich_from_title(
            "ADHD non-pharmacological treatment review",
            fetcher=fake_fetch,
            use_cache=False,
        )
        # Empty network response → no concepts; but importantly, the cache
        # was NOT used (otherwise we'd have ADHD_CONCEPTS back).
        self.assertEqual(result.concepts, [])

    def test_write_cache_false_suppresses_persistence(self):
        def fake_fetch(url, headers, timeout):
            return {
                "results": [
                    {"title": "x",
                     "concepts": [{"display_name": "X", "score": 0.9,
                                   "id": "https://openalex.org/CX", "level": 2}],
                     "keywords": []},
                    {"title": "y",
                     "concepts": [{"display_name": "X", "score": 0.9,
                                   "id": "https://openalex.org/CX", "level": 2}],
                     "keywords": []},
                ]
            }
        result = enrich_from_title(
            "anything",
            fetcher=fake_fetch,
            write_cache=False,
        )
        self.assertTrue(result.ok)
        self.assertEqual(len(load_all()), 0)


# ─────────────────────────────────────────────────────────────────────────────
# Stats
# ─────────────────────────────────────────────────────────────────────────────

class CacheStatsTests(unittest.TestCase):
    def test_stats_on_empty(self):
        s = stats()
        self.assertFalse(s["exists"])
        self.assertEqual(s["records"], 0)

    def test_stats_after_appends(self):
        append("a", _mk_result(ADHD_CONCEPTS))
        append("b", _mk_result(TRUFFLE_CONCEPTS))
        s = stats()
        self.assertTrue(s["exists"])
        self.assertEqual(s["records"], 2)
        # Top domain should reflect the top concept of each record.
        names = {n for n, _ in s["top_domains"]}
        self.assertIn("Attention deficit hyperactivity disorder", names)
        self.assertIn("Truffle", names)


if __name__ == "__main__":
    unittest.main()
