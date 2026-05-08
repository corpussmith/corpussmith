"""Tests for Stage 12 — MeSH descriptor validation.

The validator hits NLM's lookup endpoint. Real network calls are blocked by
``conftest._block_real_openalex`` (which also patches mesh._http_fetch);
tests here either inject a deterministic fetcher or exercise the offline
fallback path.
"""

from __future__ import annotations

import unittest
import urllib.error
from unittest.mock import patch

from corpussmith.search.mesh import (
    ValidatedTerm,
    build_pubmed_query,
    validate,
)


# Synthetic NLM responses — modelled on the real shape we observed in design.
NLM_HITS = {
    "mindfulness":
        [{"resource": "http://id.nlm.nih.gov/mesh/D064866",
          "label": "Mindfulness"}],
    "cognitive behavioral therapy":
        [{"resource": "http://id.nlm.nih.gov/mesh/D015928",
          "label": "Cognitive Behavioral Therapy"}],
    "psychology":
        [{"resource": "http://id.nlm.nih.gov/mesh/D011584",
          "label": "Psychology"}],
    # contains-style canonicalisation
    "eating disorders":
        [{"resource": "http://id.nlm.nih.gov/mesh/D001068",
          "label": "Feeding and Eating Disorders"}],
}


def _fake_fetcher(url, headers, timeout):
    # Pull the label= param out of the URL.
    import urllib.parse
    q = urllib.parse.urlparse(url).query
    params = dict(urllib.parse.parse_qsl(q))
    label = (params.get("label") or "").lower()
    match = params.get("match", "exact")

    # exact: only return on exact lowercase match.
    if match == "exact":
        return NLM_HITS.get(label, [])
    # contains: match if our key is a substring or vice versa.
    for key, hits in NLM_HITS.items():
        if label in key or key in label:
            return hits
    return []


class ValidateUnitTests(unittest.TestCase):
    def test_real_descriptor_passes(self):
        out = validate(["Mindfulness"], fetcher=_fake_fetcher,
                       use_cache=False, write_cache=False)
        self.assertEqual(len(out), 1)
        v = out[0]
        self.assertTrue(v.is_mesh)
        self.assertEqual(v.canonical, "Mindfulness")
        self.assertEqual(v.descriptor_id, "D064866")

    def test_canonicalisation_via_contains(self):
        out = validate(["eating disorders"], fetcher=_fake_fetcher,
                       use_cache=False, write_cache=False)
        v = out[0]
        self.assertTrue(v.is_mesh)
        self.assertEqual(v.canonical, "Feeding and Eating Disorders")
        self.assertIn("canonicalised", v.note)

    def test_unknown_term_fallback(self):
        out = validate(["Capacity to Love"], fetcher=_fake_fetcher,
                       use_cache=False, write_cache=False)
        v = out[0]
        self.assertFalse(v.is_mesh)
        self.assertEqual(v.canonical, "Capacity to Love")
        self.assertIn("Title/Abstract", v.as_pubmed_term())

    def test_pubmed_term_format_real_descriptor(self):
        v = ValidatedTerm("Mindfulness", True, "Mindfulness", "D064866")
        self.assertEqual(v.as_pubmed_term(), '"Mindfulness"[MeSH]')

    def test_pubmed_term_format_fallback(self):
        v = ValidatedTerm("Capacity to Love", False, "Capacity to Love")
        self.assertEqual(v.as_pubmed_term(), '"Capacity to Love"[Title/Abstract]')

    def test_build_pubmed_query_mixed(self):
        out = validate(
            ["Mindfulness", "Capacity to Love", "Cognitive Behavioral Therapy"],
            fetcher=_fake_fetcher, use_cache=False, write_cache=False,
        )
        q = build_pubmed_query(out)
        self.assertIn('"Mindfulness"[MeSH]', q)
        self.assertIn('"Capacity to Love"[Title/Abstract]', q)
        self.assertIn('"Cognitive Behavioral Therapy"[MeSH]', q)
        self.assertEqual(q.count("AND"), 2)


class ValidateNetworkFailureTests(unittest.TestCase):
    def test_network_dead_first_call_short_circuits_rest(self):
        called = []

        def boom(url, headers, timeout):
            called.append(url)
            raise urllib.error.URLError("DNS unreachable")

        out = validate(["Mindfulness", "Truffle", "Yoga"], fetcher=boom,
                       use_cache=False, write_cache=False)
        # All three return fallback; only one network call made (then we
        # mark the network dead and stop trying).
        self.assertEqual(len(out), 3)
        self.assertTrue(all(not v.is_mesh for v in out))
        self.assertEqual(len(called), 1)


class ValidateCacheTests(unittest.TestCase):
    def test_cache_hit_skips_network_call(self):
        # First call populates cache.
        first = validate(["Mindfulness"], fetcher=_fake_fetcher)
        self.assertTrue(first[0].is_mesh)

        # Second call must NOT touch the fetcher at all.
        called = []

        def boom(url, headers, timeout):
            called.append(url)
            raise AssertionError("cache must be used; no network call expected")

        second = validate(["Mindfulness"], fetcher=boom)
        self.assertTrue(second[0].is_mesh)
        self.assertEqual(called, [])

    def test_cache_lowercase_normalisation(self):
        validate(["Mindfulness"], fetcher=_fake_fetcher)
        # Different casing on the second call must still hit the cache.
        called = []

        def boom(url, headers, timeout):
            called.append(url)
            raise AssertionError("cache lookup must be case-insensitive")

        out = validate(["mindfulness"], fetcher=boom)
        self.assertTrue(out[0].is_mesh)
        self.assertEqual(called, [])


class ExpandUsesValidatedQueryTests(unittest.TestCase):
    """End-to-end: expand() should produce a PubMed query with [MeSH] for
    real descriptors and [Title/Abstract] for non-descriptors."""

    def test_pubmed_query_uses_mixed_form(self):
        from corpussmith.search.enrich import EnrichedConcept, EnrichmentResult
        from corpussmith.search.query_expansion import expand

        def fake_enricher(_title):
            return EnrichmentResult(
                concepts=[
                    EnrichedConcept(name="Mindfulness", cross_paper_count=5,
                                    avg_score=0.7, openalex_id="C29000378",
                                    level=2),
                    EnrichedConcept(name="Capacity to Love",
                                    cross_paper_count=3, avg_score=0.6,
                                    openalex_id="CXXX", level=3),
                    EnrichedConcept(name="Cognitive Behavioral Therapy",
                                    cross_paper_count=4, avg_score=0.65,
                                    openalex_id="C2780665704", level=3),
                ],
                keywords=[],
                sample_titles=["a"],
            )

        with patch("corpussmith.search.mesh._http_fetch", _fake_fetcher):
            plan = expand(
                "Capacity to Love and ADHD: a multimodal review",
                enricher=fake_enricher,
            )

        pubmed_q = plan.per_source_queries.get("pubmed", "")
        self.assertIn('"Mindfulness"[MeSH]', pubmed_q)
        self.assertIn('"Cognitive Behavioral Therapy"[MeSH]', pubmed_q)
        self.assertIn('"Capacity to Love"[Title/Abstract]', pubmed_q)
        # Notes should record the validation outcome.
        joined_notes = " | ".join(plan.notes)
        self.assertIn("validated MeSH terms", joined_notes)
        self.assertIn("Title/Abstract", joined_notes)


if __name__ == "__main__":
    unittest.main()
