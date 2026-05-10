"""QueryPlan — the deterministic, human-readable search strategy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from corpussmith.search.enrich import EnrichmentResult


@dataclass(frozen=True)
class Query:
    text: str
    mode: str   # broad | focused | phrase | review | recency | multilingual | enriched
    reason: str = ""


@dataclass
class QueryPlan:
    raw_input: str
    classification: str
    title: str = ""
    subtitle: str = ""
    salient_phrases: List[str] = field(default_factory=list)
    keyword_bundles: List[List[str]] = field(default_factory=list)
    multilingual_terms: List[str] = field(default_factory=list)
    queries: List[Query] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    # Stage 11 additions
    enrichment: Optional["EnrichmentResult"] = None
    per_source_queries: Dict[str, str] = field(default_factory=dict)

    def as_subject_strings(self) -> List[str]:
        if self.enrichment and self.enrichment.ok and self.enrichment.concepts:
            out: List[str] = []
            seen = set()
            for c in self.enrichment.concepts:
                k = c.name.lower().strip()
                if k and k not in seen:
                    seen.add(k)
                    out.append(c.name)
            return out

        # Fallback: phrases + bundles
        out = []
        seen = set()
        def add(x: str) -> None:
            k = x.lower().strip()
            if k and k not in seen:
                seen.add(k)
                out.append(x.strip())
        for p in self.salient_phrases[:3]:
            add(p)
        for bundle in self.keyword_bundles[:2]:
            for kw in bundle[:3]:
                add(kw)
        if not out:
            add(self.raw_input)
        return out

    def pretty(self, width: int = 76) -> str:
        lines: List[str] = []
        sep = "─" * width

        def row(label: str, value: str) -> None:
            lines.append(f"  {label:<20} {value}")

        lines.append(sep)
        lines.append("  QUERY PLAN")
        lines.append(sep)
        row("INPUT CLASSIFICATION", self.classification)
        if self.title:
            row("TITLE", self.title)
        if self.subtitle:
            row("SUBTITLE", self.subtitle)
        if self.salient_phrases:
            row("SALIENT PHRASES", " · ".join(f'"{p}"' for p in self.salient_phrases))
        for i, bundle in enumerate(self.keyword_bundles, start=1):
            row(f"KEYWORD BUNDLE {i}", " · ".join(bundle))
        if self.multilingual_terms:
            row("MULTILINGUAL", " · ".join(self.multilingual_terms))

        if self.enrichment and self.enrichment.ok and self.enrichment.concepts:
            lines.append("")
            lines.append("  CONCEPT ENRICHMENT")
            for c in self.enrichment.concepts[:5]:
                lines.append(f"    [{c.cross_paper_count}×]  {c.name}")

        lines.append("")
        lines.append("  QUERIES")
        for q in self.queries:
            tag = f"[{q.mode}]".ljust(14)
            lines.append(f"    {tag} {q.text}")

        if self.per_source_queries:
            lines.append("")
            lines.append("  PER-SOURCE QUERIES")
            for source, query in self.per_source_queries.items():
                lines.append(f"    [{source}]  {query[:100]}")

        if self.notes:
            lines.append("")
            lines.append("  NOTES")
            for n in self.notes:
                lines.append(f"    · {n}")
        lines.append(sep)
        return "\n".join(lines)


__all__ = ["Query", "QueryPlan"]
