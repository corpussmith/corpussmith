# Changelog

All notable changes to Corpus Smith are documented here.

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
