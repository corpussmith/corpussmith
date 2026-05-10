# Changelog

All notable changes to Corpus Smith are documented here.

---

## v3.5.0-beta.1 (2026-05-08)

### Added
- **Stage 10 — Research-brief ingest.** `corpussmith search --from <file>` seeds
  a full harvest from any PDF, DOCX, Markdown, or plain-text research brief.
  The wizard now optionally asks for a brief at project creation time.
  `import` writes `.extracted.txt` sidecars for single-document imports.
  New module: `corpussmith/search/brief.py`.
- **Stage 11 — OpenAlex concept enrichment.** After query expansion, the top 5
  OpenAlex works matching the title are fetched; concepts appearing in ≥2 papers
  with avg score ≥0.30 are promoted as the primary query signal. Per-source query
  templates emitted: PubMed MeSH, OpenAlex `concepts.id` filter, arXiv phrase
  query. `--no-enrich` flag for offline use. New module: `corpussmith/search/enrich.py`.
- **Stage 11c — Local concept cache.** TF-IDF nearest-neighbour cache for
  enrichment results — searches return instantly after the first run on a topic.
  Stored as JSONL under `~/.corpussmith/concept_cache.jsonl`.
  New module: `corpussmith/search/concept_cache.py`.
- **Stage 12 — NLM MeSH descriptor validation.** Every PubMed concept term is
  validated against NLM's controlled vocabulary via the lookup API. Exact and
  contains-fallback matching; auto-canonicalisation; in-memory cache; graceful
  offline degradation. New module: `corpussmith/search/mesh.py`.
- **Stage 13 — `corpussmith cache` CLI verb.** `stats`, `clear`, `show <title>`,
  and `export <path>` (JSONL or CSV) for the local concept cache.

### Changed
- `query_expansion.py`: enrichment concepts now produce per-source queries in
  `QueryPlan.per_source_queries`; `QueryPlan.pretty()` shows enrichment section.
- `lexicon.py`: whole-word boundary matching in bundle seed lookup.
- `title_parser.py`: two-pass salient-phrase extraction (verbatim recurrence
  first, then content-word runs) for more stable phrase ranking.
- `onboarding.py`: wizard asks for optional research-brief path.
- Premium stubs: all six unimplemented features delegate to
  `corpussmith_premium.*` when the private wheel is installed.

### Tests
- Suite expanded from 95 to **177 passing, 2 skipped**.

---

## v3.4.0-beta.1 (2026-04-23)

### Changed
- **Renamed project from ScholarForge to Corpus Smith.** Package name is now
  `corpussmith`; CLI command is now `corpussmith`; environment-variable prefix
  is now `CORPUSSMITH_*`; global config file is now `~/.corpussmith.toml`.

### Added
- Modular package architecture (`corpussmith/` package replacing the monolithic script)
- New CLI verbs: `new`, `search`, `import`, `build`, `export`, `review-project`,
  `config`, `premium`
- Project workspaces with `project.toml`
- Beginner onboarding wizard (plain-English, numbered menus, sensible defaults)
- Trust labels and provenance metadata on every harvested record
- BibTeX, CSL-JSON, and annotated Markdown bibliography exports
- Title/question → deterministic query expansion (no AI dependency)
- Domain lexicons: biology, neuroscience, psychiatry, classics, philosophy, music
- Premium feature stubs with activation gate: atlas, clusters, contradictions,
  thesis-pack, book-pack, memory-graph
- Static promotional site in `site/` (6 pages)
- 95-test suite covering exports, onboarding, premium, projects, query expansion,
  site, smoke, trust, and TUI banner

---

## v3.3.0 (2026-03-30)

### Added
- +7 new sources → 20 total: Figshare, HAL, SSRN, Paperity, PMC Full-Text,
  OA.mg, EThOS/DART-Europe

---

## v3.2.0

### Changed
- Removed book/paper mode split — all sources always active

### Added
- arXiv, Europe PMC, Zenodo, CORE, DOAJ, OpenAIRE (13 sources total)

---

## v3.1.0

### Added
- Full Unicode support + accent-normalised matching
- Inline `h` help at every interactive prompt
- `--explain FIELD` CLI flag
- Pipeline mode

---

## v3.0.0

### Added
- Initial release: combined bibliography harvester + knowledge dataset builder
