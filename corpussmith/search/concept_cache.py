"""Stage 11c — local TF-IDF concept cache.

Persisted to ``~/.corpussmith/concept_cache.jsonl`` (or the directory pointed
at by ``CORPUSSMITH_CACHE_DIR`` for test isolation).
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


_MIN_CACHE_RECORDS = 8
_MIN_SIMILARITY = 0.30


# ─── path ─────────────────────────────────────────────────────────────────────

def cache_path() -> Path:
    base = os.environ.get("CORPUSSMITH_CACHE_DIR")
    if base:
        return Path(base) / "concept_cache.jsonl"
    return Path.home() / ".corpussmith" / "concept_cache.jsonl"


# ─── data model ───────────────────────────────────────────────────────────────

@dataclass
class CachedRecord:
    title: str
    concepts: list  # List[dict] — serialised EnrichedConcept fields
    ts: str = ""

    def concept_names(self) -> List[str]:
        return [c.get("name", "") for c in self.concepts if c.get("name")]


# ─── persistence ──────────────────────────────────────────────────────────────

def append(title: str, result: "EnrichmentResult") -> None:  # type: ignore[name-defined]
    from corpussmith.search.enrich import EnrichmentResult
    if not isinstance(result, EnrichmentResult):
        return
    if not result.concepts or result.error:
        return

    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "title": title,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "concepts": [
            {
                "name": c.name,
                "cross_paper_count": c.cross_paper_count,
                "avg_score": c.avg_score,
                "openalex_id": c.openalex_id,
                "level": c.level,
                "source": c.source,
            }
            for c in result.concepts
        ],
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_all() -> List[CachedRecord]:
    path = cache_path()
    if not path.exists():
        return []
    records = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    records.append(CachedRecord(
                        title=d.get("title", ""),
                        concepts=d.get("concepts", []),
                        ts=d.get("ts", ""),
                    ))
                except Exception:
                    pass
    except Exception:
        pass
    return records


# ─── TF-IDF helpers ───────────────────────────────────────────────────────────

def _tokenize(text: str) -> List[str]:
    return re.findall(r"\w+", text.lower())


def _build_idf(docs: List[List[str]]) -> Dict[str, float]:
    n = len(docs)
    df: Counter = Counter()
    for tokens in docs:
        for t in set(tokens):
            df[t] += 1
    return {t: math.log((n + 1) / (cnt + 1)) + 1.0 for t, cnt in df.items()}


def _vec(tokens: List[str], idf: Dict[str, float]) -> Dict[str, float]:
    tf = Counter(tokens)
    n = max(len(tokens), 1)
    return {t: (cnt / n) * idf.get(t, 1.0) for t, cnt in tf.items()}


def _cosine(v1: Dict[str, float], v2: Dict[str, float]) -> float:
    common = set(v1) & set(v2)
    if not common:
        return 0.0
    dot = sum(v1[t] * v2[t] for t in common)
    n1 = math.sqrt(sum(x * x for x in v1.values()))
    n2 = math.sqrt(sum(x * x for x in v2.values()))
    if n1 == 0 or n2 == 0:
        return 0.0
    return dot / (n1 * n2)


# ─── lookup ───────────────────────────────────────────────────────────────────

def lookup(
    query: str,
    *,
    min_cache_records: int = _MIN_CACHE_RECORDS,
    min_similarity: float = _MIN_SIMILARITY,
) -> "Optional[EnrichmentResult]":  # type: ignore[name-defined]
    from corpussmith.search.enrich import EnrichedConcept, EnrichmentResult

    records = load_all()
    if len(records) < min_cache_records:
        return None

    titles = [r.title for r in records]
    token_lists = [_tokenize(t) for t in titles]
    idf = _build_idf(token_lists)

    q_tokens = _tokenize(query)
    q_vec = _vec(q_tokens, idf)

    # Score every cached title.
    scored: List[Tuple[float, CachedRecord]] = []
    for tokens, record in zip(token_lists, records):
        v = _vec(tokens, idf)
        sim = _cosine(q_vec, v)
        if sim >= min_similarity:
            scored.append((sim, record))

    if not scored:
        return None

    scored.sort(key=lambda x: -x[0])

    # Aggregate concepts from all selected neighbours.
    # Cross-neighbour count: how many neighbours have this concept?
    concept_counts: Counter = Counter()
    concept_data: Dict[str, dict] = {}
    sample_titles: List[str] = []

    for sim, record in scored:
        sample_titles.append(f"{record.title} (sim={sim:.3f})")
        for c in record.concepts:
            name = c.get("name", "")
            if name:
                concept_counts[name] += 1
                if name not in concept_data:
                    concept_data[name] = c

    # Keep only concepts that appear in >= 2 neighbours.
    n_neighbours = len(scored)
    threshold = 2 if n_neighbours >= 2 else 1
    agg_concepts = []
    for name, count in concept_counts.most_common():
        if count < threshold:
            continue
        c = concept_data[name]
        agg_concepts.append(EnrichedConcept(
            name=name,
            cross_paper_count=c.get("cross_paper_count", count),
            avg_score=c.get("avg_score", 0.5),
            openalex_id=c.get("openalex_id", ""),
            level=c.get("level", 0),
            source=f"cache:{sample_titles[0][:40]}",
        ))

    if not agg_concepts:
        return None

    return EnrichmentResult(
        concepts=agg_concepts,
        keywords=[],
        sample_titles=sample_titles[:5],
        ok=True,
        skipped=False,
    )


# ─── stats ────────────────────────────────────────────────────────────────────

def stats() -> Dict:
    path = cache_path()
    records = load_all()
    if not records:
        return {"exists": path.exists(), "records": 0, "top_domains": []}

    top_concept_counter: Counter = Counter()
    for r in records:
        if r.concepts:
            top_concept_counter[r.concepts[0].get("name", "")] += 1

    return {
        "exists": True,
        "records": len(records),
        "top_domains": top_concept_counter.most_common(10),
        "warming_up": len(records) < _MIN_CACHE_RECORDS,
    }


__all__ = [
    "CachedRecord",
    "append",
    "cache_path",
    "load_all",
    "lookup",
    "stats",
]
