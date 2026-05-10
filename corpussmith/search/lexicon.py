"""Load domain lexicons from JSON files bundled in `corpussmith/lexicons/`.

A lexicon is a simple mapping:
  {
    "domain": "neuroscience",
    "seeds": {
      "neuroplasticity": [
        "synaptic plasticity",
        "brain plasticity",
        "neural reorganization",
        "cortical remapping"
      ],
      ...
    },
    "multilingual": {
      "neuroplasticity": ["νευροπλαστικότητα", "neuroplasticité",
                          "Neuroplastizität"]
    }
  }

Users can add/edit files — it's just JSON. No training, no models.
"""

from __future__ import annotations

import json
import re
import unicodedata
from importlib import resources
from typing import Dict, List, Tuple

# Cached after first load.
_CACHE: Dict[str, Dict] = {}


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def _slug(s: str) -> str:
    return _strip_accents(s.lower()).strip()


def load_all() -> Dict[str, Dict]:
    """Load and cache every JSON in `corpussmith/lexicons/`."""
    if _CACHE:
        return _CACHE
    try:
        pkg_files = resources.files("corpussmith").joinpath("lexicons")
        for p in pkg_files.iterdir():
            if p.name.endswith(".json"):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                domain = data.get("domain") or p.stem
                _CACHE[domain] = data
    except Exception:
        # Missing lexicons shouldn't break the app — expansion just degrades
        # to token-based only.
        pass
    return _CACHE


def _seed_matches_term(seed: str, term: str) -> bool:
    """True when all words of *seed* appear as whole words in *term*.

    This is intentionally one-directional: a single-word input term cannot
    drag in a multi-word seed that happens to share one of its words.
    """
    seed_s = _slug(seed)
    term_s = _slug(term)
    if seed_s == term_s:
        return True
    for word in seed_s.split():
        if not re.search(r"\b" + re.escape(word) + r"\b", term_s):
            return False
    return True


def find_bundles(terms: List[str]) -> List[List[str]]:
    """For each matched seed, return a bundle of synonyms/related terms.

    Matching is case + accent insensitive. All words of a seed must appear as
    whole words inside an input term (not the reverse) to prevent a short
    input word from dragging in an unrelated multi-word seed.
    """
    lex = load_all()
    if not lex:
        return []

    bundles: List[List[str]] = []
    seen_seeds = set()

    for domain_data in lex.values():
        seeds = domain_data.get("seeds") or {}
        for seed, synonyms in seeds.items():
            seed_slug = _slug(seed)
            if seed_slug in seen_seeds:
                continue
            matched = any(_seed_matches_term(seed_slug, _slug(t)) for t in terms if t)
            if matched:
                seen_seeds.add(seed_slug)
                bundle = [seed] + [s for s in synonyms if s]
                # De-dupe case-insensitively while preserving original casing.
                dedup: List[str] = []
                seen_vals = set()
                for v in bundle:
                    k = v.lower()
                    if k not in seen_vals:
                        seen_vals.add(k)
                        dedup.append(v)
                bundles.append(dedup)
    return bundles


def multilingual_for(terms: List[str]) -> List[str]:
    """Return non-English variants matched against the given terms."""
    lex = load_all()
    if not lex:
        return []
    slugs = [_slug(t) for t in terms if t]
    out: List[str] = []
    seen = set()
    for domain_data in lex.values():
        ml = domain_data.get("multilingual") or {}
        for key, variants in ml.items():
            key_slug = _slug(key)
            if not any(key_slug in s or s in key_slug for s in slugs if s):
                continue
            for v in variants:
                if v and v.lower() not in seen:
                    seen.add(v.lower())
                    out.append(v)
    return out


__all__ = ["load_all", "find_bundles", "multilingual_for", "_seed_matches_term"]
