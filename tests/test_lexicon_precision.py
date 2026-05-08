"""Lexicon-precision regressions.

Two failure modes we want to keep dead:

1. A common single-word content term (e.g. "processing") inside a long brief
   used to drag in any multi-word seed it was a substring of — most visibly
   the *music* lexicon's ``auditory processing`` bundle (psychoacoustics,
   cochlear processing, …) firing on a neuroscience capacity-to-love brief.

2. The salient-phrase ranker used to prefer syntactic chunks like
   ``"Investigation Across Trauma"`` over the conceptual phrase the author
   actually repeats (``"capacity to love"``), because it scored on
   token-frequency without weighing whole-phrase recurrence.
"""

from __future__ import annotations

import unittest

from corpussmith.search.lexicon import find_bundles, _seed_matches_term
from corpussmith.search.query_expansion import expand
from corpussmith.search.title_parser import salient_phrases


CAPACITY_TO_LOVE_BRIEF = (
    "Neurobiological and Relational Determinants of the Capacity to Love: "
    "A Multimodal Investigation Across Trauma, Personality Pathology, "
    "Psychosis, and Eating Disorders. "
    "The capacity to love is conceptualized as an emergent neuropsychiatric "
    "function arising from the interaction between biological integrity, "
    "neural processing, social cognition, Theory of Mind, developmental "
    "modulation by trauma, and personality organization. "
    "Capacity to love is operationalizable through mentalization, affect "
    "tolerance, attachment, and reciprocity. "
    "Eating disorders manifest disturbance of body-self representation."
)


class SeedMatchRuleTests(unittest.TestCase):
    def test_single_word_seed_requires_whole_word_term(self):
        # "processing" alone must NOT match the seed "auditory processing".
        self.assertFalse(_seed_matches_term("auditory processing", "processing"))
        # But a multi-word term containing "auditory processing" as words does.
        self.assertTrue(_seed_matches_term("auditory processing",
                                            "central auditory processing"))

    def test_equal_slugs_always_match(self):
        self.assertTrue(_seed_matches_term("theory of mind", "theory of mind"))
        self.assertTrue(_seed_matches_term("trauma", "trauma"))

    def test_single_word_seed_matches_inside_multi_word_term(self):
        # seed "trauma" matches inside "early trauma exposure"
        self.assertTrue(_seed_matches_term("trauma", "early trauma exposure"))

    def test_no_partial_substring_match(self):
        # "audit" must not match "auditory" via substring.
        self.assertFalse(_seed_matches_term("audit", "auditory"))

    def test_single_word_term_does_not_drag_multi_word_seed(self):
        # The historical bug: "processing" → "auditory processing".
        self.assertFalse(_seed_matches_term("auditory processing", "processing"))


class CapacityToLoveBriefBundleTests(unittest.TestCase):
    """Real-world: the researcher's brief should match concept bundles, NOT
    the music lexicon's psychoacoustics bundle."""

    def setUp(self):
        plan = expand(CAPACITY_TO_LOVE_BRIEF)
        # Each bundle is a list of strings; flatten and lowercase.
        self.bundle_terms = {
            t.lower() for bundle in plan.keyword_bundles for t in bundle
        }

    def test_does_not_trigger_psychoacoustics(self):
        self.assertNotIn("psychoacoustics", self.bundle_terms,
                         "psychoacoustics bundle leaked from music lexicon")
        self.assertNotIn("auditory cortex", self.bundle_terms)

    def test_triggers_theory_of_mind_bundle(self):
        # Either the seed itself or a synonym should be present.
        self.assertTrue(
            "theory of mind" in self.bundle_terms
            or "mentalization" in self.bundle_terms,
            f"theory-of-mind bundle missing — got {self.bundle_terms}",
        )

    def test_triggers_eating_disorders_bundle(self):
        self.assertTrue(
            "eating disorders" in self.bundle_terms
            or "anorexia nervosa" in self.bundle_terms,
            f"eating-disorders bundle missing — got {self.bundle_terms}",
        )


class SalientPhraseRankingTests(unittest.TestCase):
    """The phrase the author repeats verbatim should outrank syntactic
    chunks that survive the stopword filter."""

    def test_capacity_to_love_outranks_investigation_across_trauma(self):
        phrases = salient_phrases(CAPACITY_TO_LOVE_BRIEF, max_phrases=8)
        lower = [p.lower() for p in phrases]
        # The conceptual phrase must be present.
        self.assertTrue(any("capacity" in p and "love" in p for p in lower),
                        f"capacity-to-love missing from salient phrases: {phrases}")
        # And — if both are present — the conceptual phrase should outrank
        # the connector-heavy chunk.
        try:
            cap_idx = next(i for i, p in enumerate(lower)
                           if "capacity" in p and "love" in p)
            inv_idx = next(i for i, p in enumerate(lower)
                           if "investigation" in p and "across" in p)
        except StopIteration:
            return  # one of them isn't there — earlier assertion still wins
        self.assertLess(cap_idx, inv_idx,
                        f"capacity-to-love should rank above the "
                        f"investigation-across-trauma chunk; got {phrases}")


if __name__ == "__main__":
    unittest.main()
