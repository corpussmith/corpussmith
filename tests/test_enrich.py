"""Tests for OpenAlex-based concept enrichment.

The aggregator and the integration with ``expand()`` are tested with synthetic
OpenAlex JSON — no network required. A network-gated smoke test runs only
when ``ENABLE_NETWORK_TESTS=1`` is set.
"""

from __future__ import annotations

import json
import os
import unittest
from typing import Dict
from unittest.mock import patch

from corpussmith.search.enrich import (
    EnrichedConcept,
    EnrichmentResult,
    _aggregate,
    enrich_from_title,
)
from corpussmith.search.query_expansion import expand


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic OpenAlex /works?search=... response — modelled on the real
# ADHD-paper response we observed during design.
# ─────────────────────────────────────────────────────────────────────────────

ADHD_FIXTURE = {
    "results": [
        {
            "id": "https://openalex.org/W1",
            "title": "Non-pharmacological treatment of ADHD",
            "concepts": [
                {"display_name": "Attention deficit hyperactivity disorder",
                 "score": 0.94, "id": "https://openalex.org/C2779394", "level": 2},
                {"display_name": "Psychiatry", "score": 0.71,
                 "id": "https://openalex.org/C118552586", "level": 1},
                {"display_name": "Cognitive behavioral therapy", "score": 0.62,
                 "id": "https://openalex.org/C2780665704", "level": 3},
                {"display_name": "Mindfulness", "score": 0.58,
                 "id": "https://openalex.org/C29000378", "level": 2},
            ],
            "keywords": [
                {"display_name": "ADHD", "score": 0.9},
                {"display_name": "Mindfulness", "score": 0.8},
            ],
        },
        {
            "id": "https://openalex.org/W2",
            "title": "Long-term outcomes in ADHD",
            "concepts": [
                {"display_name": "Attention deficit hyperactivity disorder",
                 "score": 0.91, "id": "https://openalex.org/C2779394", "level": 2},
                {"display_name": "Psychiatry", "score": 0.78,
                 "id": "https://openalex.org/C118552586", "level": 1},
                {"display_name": "Pediatrics", "score": 0.40,
                 "id": "https://openalex.org/C187212893", "level": 1},
            ],
            "keywords": [
                {"display_name": "ADHD", "score": 0.85},
            ],
        },
        {
            "id": "https://openalex.org/W3",
            "title": "Digital intervention for paediatric ADHD",
            "concepts": [
                {"display_name": "Attention deficit hyperactivity disorder",
                 "score": 0.88, "id": "https://openalex.org/C2779394", "level": 2},
                {"display_name": "Cognitive behavioral therapy", "score": 0.55,
                 "id": "https://openalex.org/C2780665704", "level": 3},
                {"display_name": "Intervention (counseling)", "score": 0.35,
                 "id": "https://openalex.org/C160798450", "level": 2},
                {"display_name": "Singleton noise", "score": 0.10,  # below floor
                 "id": "https://openalex.org/C9999999", "level": 5},
            ],
            "keywords": [
                {"display_name": "Mindfulness", "score": 0.7},
            ],
        },
    ]
}


# ─────────────────────────────────────────────────────────────────────────────
# Aggregator — pure, no network
# ─────────────────────────────────────────────────────────────────────────────

class AggregatorTests(unittest.TestCase):
    def test_cross_paper_count_drives_ranking(self):
        concepts, keywords, titles = _aggregate(ADHD_FIXTURE["results"])
        names = [c.name for c in concepts]
        # ADHD appears in all 3 papers — must rank first.
        self.assertEqual(names[0], "Attention deficit hyperactivity disorder")
        self.assertEqual(concepts[0].cross_paper_count, 3)

    def test_singleton_concepts_dropped(self):
        # Pediatrics + "Intervention (counseling)" appear in only 1 paper each
        # → must be filtered out by the default min_cross_paper_count=2.
        concepts, _, _ = _aggregate(ADHD_FIXTURE["results"])
        names = {c.name for c in concepts}
        self.assertNotIn("Pediatrics", names)
        self.assertNotIn("Intervention (counseling)", names)

    def test_low_score_concepts_dropped(self):
        # "Singleton noise" has score 0.10 (below 0.30 floor) AND only 1 paper.
        concepts, _, _ = _aggregate(ADHD_FIXTURE["results"])
        names = {c.name for c in concepts}
        self.assertNotIn("Singleton noise", names)

    def test_keywords_aggregated_separately(self):
        _, keywords, _ = _aggregate(ADHD_FIXTURE["results"])
        names = {k.name for k in keywords}
        # ADHD (in 2 papers) and Mindfulness (in 2 papers) both qualify.
        self.assertIn("ADHD", names)
        self.assertIn("Mindfulness", names)

    def test_openalex_id_preserved(self):
        concepts, _, _ = _aggregate(ADHD_FIXTURE["results"])
        for c in concepts:
            if c.name == "Attention deficit hyperactivity disorder":
                self.assertEqual(c.openalex_id, "C2779394")
                self.assertEqual(c.level, 2)
                break
        else:
            self.fail("ADHD concept not found")

    def test_avg_score_computed(self):
        concepts, _, _ = _aggregate(ADHD_FIXTURE["results"])
        adhd = next(c for c in concepts
                    if c.name == "Attention deficit hyperactivity disorder")
        # (0.94 + 0.91 + 0.88) / 3 ≈ 0.91
        self.assertAlmostEqual(adhd.avg_score, (0.94 + 0.91 + 0.88) / 3, places=2)

    def test_empty_input(self):
        concepts, keywords, titles = _aggregate([])
        self.assertEqual(concepts, [])
        self.assertEqual(keywords, [])
        self.assertEqual(titles, [])

    def test_sample_titles_collected(self):
        _, _, titles = _aggregate(ADHD_FIXTURE["results"])
        self.assertEqual(len(titles), 3)


# ─────────────────────────────────────────────────────────────────────────────
# enrich_from_title — with injected fetcher (no real HTTP)
# ─────────────────────────────────────────────────────────────────────────────

class EnrichWithInjectedFetcherTests(unittest.TestCase):
    def test_happy_path(self):
        captured: Dict[str, str] = {}

        def fake_fetch(url, headers, timeout):
            captured["url"] = url
            return ADHD_FIXTURE

        result = enrich_from_title(
            "Non-pharmacological treatment of ADHD",
            fetcher=fake_fetch,
        )
        self.assertTrue(result.ok)
        self.assertGreaterEqual(len(result.concepts), 2)
        # Top concept must be ADHD itself.
        self.assertEqual(result.concepts[0].name,
                         "Attention deficit hyperactivity disorder")
        # URL must hit OpenAlex /works?search=…
        self.assertIn("api.openalex.org/works?search=", captured["url"])
        self.assertIn("per-page=", captured["url"])

    def test_disabled_returns_skipped_result(self):
        result = enrich_from_title("anything", enabled=False)
        self.assertFalse(result.ok)
        self.assertTrue(result.skipped)
        self.assertEqual(result.concepts, [])

    def test_empty_title_returns_skipped(self):
        result = enrich_from_title("   ", fetcher=lambda u, h, t: ADHD_FIXTURE)
        self.assertTrue(result.skipped)

    def test_network_failure_returns_skipped_not_raises(self):
        import urllib.error

        def boom(url, headers, timeout):
            raise urllib.error.URLError("DNS unreachable")

        result = enrich_from_title("anything", fetcher=boom)
        self.assertFalse(result.ok)
        self.assertTrue(result.skipped)
        self.assertIn("network", result.error)
        # Caller can still ignore the result; nothing crashed.

    def test_http_error_returns_failed_result(self):
        import urllib.error

        def http_500(url, headers, timeout):
            raise urllib.error.HTTPError(url, 500, "Internal Server Error",
                                          hdrs=None, fp=None)

        result = enrich_from_title("anything", fetcher=http_500)
        self.assertFalse(result.ok)
        self.assertFalse(result.skipped)
        self.assertIn("openalex error", result.error)


# ─────────────────────────────────────────────────────────────────────────────
# expand() with enrichment injected — full plan should pick up enriched
# concepts as the top subjects + emit per-source query templates.
# ─────────────────────────────────────────────────────────────────────────────

class ExpandWithEnrichmentTests(unittest.TestCase):
    def _enricher(self, title):
        return EnrichmentResult(
            concepts=[
                EnrichedConcept(
                    name="Attention deficit hyperactivity disorder",
                    cross_paper_count=3, avg_score=0.91,
                    openalex_id="C2779394", level=2),
                EnrichedConcept(
                    name="Cognitive behavioral therapy",
                    cross_paper_count=2, avg_score=0.59,
                    openalex_id="C2780665704", level=3),
                EnrichedConcept(
                    name="Mindfulness",
                    cross_paper_count=2, avg_score=0.55,
                    openalex_id="C29000378", level=2),
            ],
            keywords=[],
            sample_titles=["a", "b", "c"],
        )

    def test_enrichment_drives_subject_strings(self):
        plan = expand(
            "Non-pharmacological treatment of ADHD: a review",
            enricher=self._enricher,
        )
        subjects = plan.as_subject_strings()
        # The top OpenAlex concept must lead the subjects list.
        self.assertEqual(subjects[0],
                         "Attention deficit hyperactivity disorder")

    def test_enriched_query_appended(self):
        plan = expand(
            "Non-pharmacological treatment of ADHD: a review",
            enricher=self._enricher,
        )
        modes = {q.mode for q in plan.queries}
        self.assertIn("enriched", modes)

    def test_per_source_templates_emitted(self):
        plan = expand(
            "Non-pharmacological treatment of ADHD: a review",
            enricher=self._enricher,
        )
        psq = plan.per_source_queries
        self.assertIn("pubmed", psq)
        self.assertIn("openalex", psq)
        self.assertIn("arxiv", psq)
        # PubMed query must include each enriched concept somehow — with
        # MeSH validation networked-blocked in tests, every term degrades
        # to [Title/Abstract], which is the correct Stage-12 fallback.
        self.assertIn("Attention deficit hyperactivity disorder", psq["pubmed"])
        self.assertTrue("[MeSH]" in psq["pubmed"]
                        or "[Title/Abstract]" in psq["pubmed"])
        # OpenAlex must use the OpenAlex concept ID.
        self.assertIn("concepts.id:C2779394", psq["openalex"])

    def test_disabled_enrichment_path_works(self):
        plan = expand(
            "Non-pharmacological treatment of ADHD: a review",
            include_enrichment=False,
        )
        self.assertIsNotNone(plan.enrichment)
        self.assertTrue(plan.enrichment.skipped)
        # Subjects still produced from salient phrases / bundles.
        self.assertTrue(plan.as_subject_strings())

    def test_skipped_enrichment_does_not_emit_per_source(self):
        plan = expand(
            "Non-pharmacological treatment of ADHD: a review",
            include_enrichment=False,
        )
        self.assertEqual(plan.per_source_queries, {})

    def test_pretty_renders_enrichment_section(self):
        plan = expand(
            "Non-pharmacological treatment of ADHD: a review",
            enricher=self._enricher,
        )
        out = plan.pretty()
        self.assertIn("CONCEPT ENRICHMENT", out)
        self.assertIn("Attention deficit hyperactivity disorder", out)
        self.assertIn("PER-SOURCE QUERIES", out)
        self.assertIn("[pubmed]", out)


# ─────────────────────────────────────────────────────────────────────────────
# Live OpenAlex smoke test — opt-in only.
# ─────────────────────────────────────────────────────────────────────────────

@unittest.skipUnless(
    os.environ.get("ENABLE_NETWORK_TESTS") == "1",
    "set ENABLE_NETWORK_TESTS=1 to run live API tests",
)
class LiveOpenAlexSmokeTests(unittest.TestCase):
    def test_real_call_returns_concepts_for_adhd(self):
        result = enrich_from_title(
            "Non-pharmacological treatment of ADHD overview"
        )
        self.assertTrue(result.ok, msg=f"enrichment failed: {result.error}")
        names = {c.name.lower() for c in result.concepts}
        self.assertTrue(
            any("attention" in n and "deficit" in n for n in names),
            f"expected an ADHD concept; got {names}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Make sure existing tests don't accidentally hit the network. The base
# expand() calls enrichment by default — we patch it to a no-op for the
# non-network tests in OTHER files. They run in their own modules; here we
# only ensure that calling expand() in this file with no fetcher does not
# crash on the offline path.
# ─────────────────────────────────────────────────────────────────────────────

class ExpandOfflineSafetyTests(unittest.TestCase):
    def test_expand_does_not_raise_when_network_down(self):
        # Force the real enricher to take the URLError path.
        import urllib.error

        def net_dead(url, headers, timeout):
            raise urllib.error.URLError("offline")

        with patch("corpussmith.search.enrich._http_fetch", net_dead):
            plan = expand("the neuroplastic brain: current breakthroughs")
        # Plan still produced; enrichment marked skipped/error.
        self.assertIsNotNone(plan.enrichment)
        self.assertFalse(plan.enrichment.ok)
        self.assertTrue(plan.queries)  # non-enrichment queries still there


class HarvestOverridePlumbingTests(unittest.TestCase):
    """Stage 11: per-source query overrides reach run_harvest."""

    def test_run_harvest_signature_accepts_overrides(self):
        # Smoke test only — we don't run a real harvest, just confirm the
        # signature change is in place and the parameter has the right type.
        import inspect
        from corpussmith._legacy import run_harvest
        sig = inspect.signature(run_harvest)
        self.assertIn("per_source_overrides", sig.parameters)
        # Default must be optional / None to keep older callers working.
        self.assertIs(sig.parameters["per_source_overrides"].default, None)

    def test_override_targets_cover_pubmed_family(self):
        # The override map for "pubmed" should reach all three biomedical
        # full-text adapters so MeSH-style queries flow through.
        from corpussmith._legacy import run_harvest
        src = inspect.getsource(run_harvest)
        # Sanity: the targets dict references each PubMed-family source name.
        for name in ("PubMed", "PMC Full-Text", "Europe PMC"):
            self.assertIn(name, src)


import inspect  # noqa: E402 — placed here so the test class can use it


if __name__ == "__main__":
    unittest.main()
