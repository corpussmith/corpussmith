"""Stage 12 — MeSH descriptor validation against the NLM vocabulary.

Calls NLM's lookup endpoint. Network failures short-circuit after the first
dead call so the full term list degrades gracefully offline.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional


_NLM_BASE = "https://id.nlm.nih.gov/mesh/lookup/descriptor"
_TIMEOUT = 8

# In-memory cache: lowercase term → ValidatedTerm (or None for known misses)
_MEM: Dict[str, Optional["ValidatedTerm"]] = {}


@dataclass
class ValidatedTerm:
    original: str
    is_mesh: bool
    canonical: str
    descriptor_id: str = ""
    note: str = ""

    def as_pubmed_term(self) -> str:
        if self.is_mesh:
            return f'"{self.canonical}"[MeSH]'
        return f'"{self.canonical}"[Title/Abstract]'


def _http_fetch(url: str, headers: Dict[str, str], timeout: int):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read(1 * 1024 * 1024).decode())


def _lookup_nlm(
    label: str,
    match: str,
    fetcher: Callable,
) -> List[Dict]:
    params = urllib.parse.urlencode({"label": label, "match": match, "limit": 5})
    url = f"{_NLM_BASE}?{params}"
    headers = {"Accept": "application/json"}
    return fetcher(url, headers, _TIMEOUT) or []


def _validate_one(
    term: str,
    fetcher: Callable,
    network_dead: bool,
    use_cache: bool,
    write_cache: bool,
) -> tuple[Optional["ValidatedTerm"], bool]:
    """Return (ValidatedTerm, network_dead).  If network_dead already True, skip."""
    key = term.lower()

    if use_cache and key in _MEM:
        cached = _MEM[key]
        return (cached or ValidatedTerm(term, False, term)), network_dead

    if network_dead:
        result = ValidatedTerm(term, False, term)
        return result, True

    try:
        # Exact match first
        hits = _lookup_nlm(key, "exact", fetcher)
        if hits:
            h = hits[0]
            label = h.get("label", term)
            did = h.get("resource", "").split("/")[-1]
            note = "canonicalised" if label.lower() != key else ""
            result = ValidatedTerm(term, True, label, did, note)
        else:
            # Contains fallback
            hits2 = _lookup_nlm(key, "contains", fetcher)
            if hits2:
                h = hits2[0]
                label = h.get("label", term)
                did = h.get("resource", "").split("/")[-1]
                result = ValidatedTerm(term, True, label, did, "canonicalised")
            else:
                result = ValidatedTerm(term, False, term)
    except urllib.error.URLError:
        result = ValidatedTerm(term, False, term)
        network_dead = True
    except Exception:
        result = ValidatedTerm(term, False, term)

    if write_cache and result.is_mesh:
        _MEM[key] = result

    return result, network_dead


def validate(
    terms: List[str],
    *,
    fetcher: Optional[Callable] = None,
    use_cache: bool = True,
    write_cache: bool = True,
) -> List[ValidatedTerm]:
    _fetch = fetcher or _http_fetch
    out: List[ValidatedTerm] = []
    network_dead = False

    for term in terms:
        vt, network_dead = _validate_one(
            term, _fetch, network_dead, use_cache, write_cache
        )
        out.append(vt)

    return out


def build_pubmed_query(terms: List[ValidatedTerm]) -> str:
    return " AND ".join(t.as_pubmed_term() for t in terms)


__all__ = ["ValidatedTerm", "validate", "build_pubmed_query", "_http_fetch"]
