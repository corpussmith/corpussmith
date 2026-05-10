"""Turn a researcher's raw input into a `QueryPlan` of concrete queries."""

from __future__ import annotations

from datetime import datetime
from typing import Callable, List, Optional

from corpussmith.search.input_classifier import classify as classify_input
from corpussmith.search.title_parser import parse as parse_title
from corpussmith.search.lexicon import find_bundles, multilingual_for
from corpussmith.search.query_plan import Query, QueryPlan


REVIEW_TAIL = 'review OR "meta-analysis" OR "systematic review"'


def _dedupe(items: List[str]) -> List[str]:
    out, seen = [], set()
    for x in items:
        k = x.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(x.strip())
    return out


def expand(
    raw: str,
    *,
    include_review: bool = True,
    include_recency: bool = False,
    include_multilingual: bool = False,
    now_year: Optional[int] = None,
    enricher: Optional[Callable] = None,
    include_enrichment: bool = True,
) -> QueryPlan:
    cls = classify_input(raw)
    parsed = parse_title(raw)
    plan = QueryPlan(
        raw_input=raw,
        classification=f"{cls.kind} ({cls.reason})",
        title=parsed.title,
        subtitle=parsed.subtitle,
        salient_phrases=list(parsed.salient_phrases),
    )

    # Include the full raw input so multi-word seeds (e.g. "theory of mind")
    # can match even when stopwords prevent phrase extraction.
    lookup_terms = list(parsed.salient_phrases) + [parsed.title] + list(parsed.content_words) + [raw]
    bundles = find_bundles(_dedupe(lookup_terms))
    plan.keyword_bundles = bundles
    if include_multilingual:
        plan.multilingual_terms = multilingual_for(_dedupe(lookup_terms))

    # ── standard queries ───────────────────────────────────────────────────
    if cls.kind == "exact_phrase":
        plan.queries.append(Query(raw.strip().strip('"').strip("'"),
                                  "phrase", "user supplied quoted phrase"))
        plan.queries.append(Query(raw.strip().strip('"').strip("'"),
                                  "broad", "same phrase, unquoted"))
        plan.notes.append("exact_phrase inputs skip bundle expansion")
    elif cls.kind == "keyword_list":
        parts = _dedupe([p.strip() for p in raw.split(",") if p.strip()])
        plan.queries.append(Query(" ".join(parts), "broad", "all keywords together"))
        for p in parts[:3]:
            plan.queries.append(Query(f'"{p}"', "phrase", "per-keyword phrase"))
        if include_review and parts:
            plan.queries.append(Query(f"{parts[0]} {REVIEW_TAIL}", "review",
                                      "first keyword + review tail"))
    else:
        content = " ".join(parsed.content_words) or raw.strip()
        plan.queries.append(Query(content, "broad", "content words joined"))

        if bundles and parsed.title:
            kw = bundles[0][1] if len(bundles[0]) > 1 else bundles[0][0]
            plan.queries.append(Query(f'"{parsed.title}" {kw}', "focused",
                                      "title + bundle synonym"))
        elif parsed.title:
            plan.queries.append(Query(f'"{parsed.title}"', "focused", "title as anchor"))

        if parsed.salient_phrases:
            plan.queries.append(Query(f'"{parsed.salient_phrases[0]}"', "phrase",
                                      "top salient phrase"))

        if include_review:
            anchor = parsed.salient_phrases[0] if parsed.salient_phrases else content
            plan.queries.append(Query(f"{anchor} {REVIEW_TAIL}", "review",
                                      "anchor + review/meta-analysis tail"))

        if include_recency:
            year_now = now_year or datetime.now().year
            span = f"{year_now - 2}..{year_now}"
            anchor = parsed.salient_phrases[0] if parsed.salient_phrases else content
            plan.queries.append(Query(f"{anchor} {span}", "recency",
                                      f"anchor + {span}"))

        if include_multilingual:
            for variant in plan.multilingual_terms[:3]:
                plan.queries.append(Query(variant, "multilingual",
                                          "non-English variant from lexicon"))

    # De-duplicate
    dedup: List[Query] = []
    seen_q = set()
    for q in plan.queries:
        k = (q.text.lower(), q.mode)
        if k not in seen_q:
            seen_q.add(k)
            dedup.append(q)
    plan.queries = dedup

    if not bundles:
        plan.notes.append("no domain lexicon matched — bundle expansion skipped")

    # ── enrichment (Stage 11) ──────────────────────────────────────────────
    if not include_enrichment:
        from corpussmith.search.enrich import EnrichmentResult
        plan.enrichment = EnrichmentResult(ok=False, skipped=True)
        return plan

    if enricher is not None:
        enrichment = enricher(raw)
    else:
        from corpussmith.search.enrich import enrich_from_title
        enrichment = enrich_from_title(raw)

    plan.enrichment = enrichment

    if enrichment.ok and enrichment.concepts:
        # Enriched query
        names = [c.name for c in enrichment.concepts[:3]]
        plan.queries.append(Query(" ".join(names), "enriched",
                                  "OpenAlex concept enrichment"))

        # Per-source queries with MeSH validation (Stage 12)
        from corpussmith.search.mesh import validate, build_pubmed_query
        validated = validate([c.name for c in enrichment.concepts])
        plan.per_source_queries["pubmed"] = build_pubmed_query(validated)

        openalex_parts = [
            f"concepts.id:{c.openalex_id}"
            for c in enrichment.concepts
            if c.openalex_id
        ]
        if openalex_parts:
            plan.per_source_queries["openalex"] = " AND ".join(openalex_parts)

        arxiv_parts = [f'"{c.name}"' for c in enrichment.concepts]
        plan.per_source_queries["arxiv"] = " ".join(arxiv_parts)

        mesh_count = sum(1 for v in validated if v.is_mesh)
        fallback_count = sum(1 for v in validated if not v.is_mesh)
        plan.notes.append(
            f"{mesh_count} validated MeSH terms; {fallback_count} Title/Abstract fallbacks"
        )

    return plan


__all__ = ["expand"]
