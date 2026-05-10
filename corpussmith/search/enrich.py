"""Stage 11 — OpenAlex concept enrichment."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


_OA_BASE = "https://api.openalex.org/works"
_PER_PAGE = 5
_TIMEOUT = 10
_MIN_CROSS_PAPER = 2
_MIN_AVG_SCORE = 0.30


@dataclass
class EnrichedConcept:
    name: str
    cross_paper_count: int
    avg_score: float
    openalex_id: str
    level: int
    source: str = "openalex"


@dataclass
class EnrichmentResult:
    concepts: List[EnrichedConcept] = field(default_factory=list)
    keywords: List[EnrichedConcept] = field(default_factory=list)
    sample_titles: List[str] = field(default_factory=list)
    ok: bool = False
    skipped: bool = False
    error: str = ""

    def __post_init__(self) -> None:
        if self.concepts and not self.error and not self.skipped and not self.ok:
            self.ok = True


# ─── HTTP layer (replaceable in tests) ────────────────────────────────────────

def _http_fetch(url: str, headers: Dict[str, str], timeout: int) -> Dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read(4 * 1024 * 1024).decode())


# ─── aggregator ───────────────────────────────────────────────────────────────

def _aggregate(
    results: List[Dict],
    min_cross_paper: int = _MIN_CROSS_PAPER,
    min_score: float = _MIN_AVG_SCORE,
) -> Tuple[List[EnrichedConcept], List[EnrichedConcept], List[str]]:
    concept_papers: Dict[str, List[float]] = {}
    concept_meta: Dict[str, Tuple[str, int]] = {}  # name → (openalex_id, level)
    keyword_papers: Dict[str, List[float]] = {}
    titles: List[str] = []

    for work in results:
        t = (work.get("title") or "").strip()
        if t:
            titles.append(t)
        for c in work.get("concepts") or []:
            name = (c.get("display_name") or "").strip()
            score = float(c.get("score") or 0)
            oid = (c.get("id") or "").split("/")[-1]
            level = int(c.get("level") or 0)
            if not name or score < min_score:
                continue
            concept_papers.setdefault(name, []).append(score)
            concept_meta[name] = (oid, level)
        for k in work.get("keywords") or []:
            name = (k.get("display_name") or "").strip()
            score = float(k.get("score") or 0)
            if name:
                keyword_papers.setdefault(name, []).append(score)

    concepts: List[EnrichedConcept] = []
    for name, scores in concept_papers.items():
        if len(scores) < min_cross_paper:
            continue
        oid, level = concept_meta[name]
        concepts.append(EnrichedConcept(
            name=name,
            cross_paper_count=len(scores),
            avg_score=sum(scores) / len(scores),
            openalex_id=oid,
            level=level,
        ))
    concepts.sort(key=lambda c: (-c.cross_paper_count, -c.avg_score))

    keywords: List[EnrichedConcept] = []
    for name, scores in keyword_papers.items():
        if len(scores) < min_cross_paper:
            continue
        keywords.append(EnrichedConcept(
            name=name,
            cross_paper_count=len(scores),
            avg_score=sum(scores) / len(scores),
            openalex_id="",
            level=0,
        ))
    keywords.sort(key=lambda k: (-k.cross_paper_count, -k.avg_score))

    return concepts, keywords, titles


# ─── public API ───────────────────────────────────────────────────────────────

def enrich_from_title(
    title: str,
    *,
    fetcher: Optional[Callable] = None,
    enabled: bool = True,
    use_cache: bool = True,
    write_cache: bool = True,
) -> EnrichmentResult:
    if not enabled:
        return EnrichmentResult(ok=False, skipped=True)

    title = (title or "").strip()
    if not title:
        return EnrichmentResult(ok=False, skipped=True)

    # Cache lookup
    if use_cache:
        from corpussmith.search import concept_cache
        cached = concept_cache.lookup(title)
        if cached is not None:
            return cached

    _fetch = fetcher or _http_fetch
    params = urllib.parse.urlencode({
        "search": title,
        "per-page": _PER_PAGE,
        "select": "id,title,concepts,keywords",
    })
    url = f"{_OA_BASE}?{params}"
    headers = {"Accept": "application/json", "User-Agent": "corpussmith/3"}

    try:
        data = _fetch(url, headers, _TIMEOUT)
    except urllib.error.HTTPError as exc:
        return EnrichmentResult(ok=False, skipped=False,
                                error=f"openalex error {exc.code}: {exc.reason}")
    except (urllib.error.URLError, OSError) as exc:
        return EnrichmentResult(ok=False, skipped=True,
                                error=f"network error: {exc}")

    works = (data or {}).get("results") or []
    concepts, keywords, sample_titles = _aggregate(works)

    result = EnrichmentResult(
        concepts=concepts,
        keywords=keywords,
        sample_titles=sample_titles,
        ok=bool(concepts),
        skipped=False,
    )

    if write_cache and result.ok:
        from corpussmith.search import concept_cache
        concept_cache.append(title, result)

    return result


__all__ = [
    "EnrichedConcept",
    "EnrichmentResult",
    "_aggregate",
    "enrich_from_title",
    "_http_fetch",
]
