"""Command-line entry point.

New in Stage 4:
  corpussmith new              — create a project workspace
  corpussmith search           — title / question / keyword search → query plan → harvest
  corpussmith import DIR       — pull documents from a folder into the project corpus
  corpussmith build            — run the forge stage over the project corpus
  corpussmith review-project   — terminal report of project state

Legacy verbs (harvest / forge / pipeline) continue to work via the legacy
monolith and print a deprecation hint.

The dispatcher is a thin custom argument parser so we don't conflict with the
legacy argparse invoked by the monolith.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

import corpussmith as _pkg


NEW_VERBS = {"new", "search", "search-draft", "search_draft", "import", "build", "review-project", "review_project", "export", "config", "premium", "cache"}

# Global flags that can precede a new verb without breaking dispatch.
# These mirror the legacy top-level flags so invocations like
#   corpussmith.py --no-banner --no-color new --name foo
# still land in the new-verb handler rather than legacy argparse.
_PASSTHROUGH_FLAGS = {"--no-banner", "--no-color", "--verbose", "-v"}


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Skip leading passthrough flags to find the first positional. If it's a
    # new verb, dispatch here; otherwise hand off to the legacy CLI so flags
    # like --help / --version / --deps / --explain / --no-banner keep working.
    i = 0
    while i < len(argv) and argv[i] in _PASSTHROUGH_FLAGS:
        i += 1
    if i < len(argv) and argv[i] in NEW_VERBS:
        leading = argv[:i]
        verb = argv[i].replace("-", "_")
        rest = argv[i + 1:]
        # Apply leading flags that the new handlers care about.
        if "--no-color" in leading:
            import os
            os.environ["NO_COLOR"] = "1"
        handler = {
            "new": _cmd_new,
            "search": _cmd_search,
            "search_draft": _cmd_search_draft,
            "import": _cmd_import,
            "build": _cmd_build,
            "review_project": _cmd_review,
            "export": _cmd_export,
            "config": _cmd_config,
            "premium": _cmd_premium,
            "cache": _cmd_cache,
        }[verb]
        return handler(rest)

    # Legacy path (harvest / forge / pipeline / --help / --version / --deps /
    # --explain / interactive menu).
    from corpussmith._legacy import main as legacy_main
    return legacy_main()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _pop_option(argv: List[str], *names: str, default: Optional[str] = None) -> Optional[str]:
    """Remove `--name value` (or `-n value`) from argv and return value."""
    for n in names:
        if n in argv:
            i = argv.index(n)
            if i + 1 < len(argv):
                val = argv[i + 1]
                del argv[i:i + 2]
                return val
    return default


def _pop_flag(argv: List[str], *names: str) -> bool:
    for n in names:
        if n in argv:
            argv.remove(n)
            return True
    return False


def _resolve_project(argv: List[str]) -> "Project":
    from corpussmith.projects.workspace import Project
    path = _pop_option(argv, "--project", "-p")
    target = Path(path).expanduser().resolve() if path else Path.cwd()
    # Walk up to find a project
    for p in [target, *target.parents]:
        if Project.is_project(p):
            return Project.load(p)
    raise SystemExit(
        "error: no Corpus Smith project found. Run `corpussmith new` first."
    )


# ─────────────────────────────────────────────────────────────────────────────
# new
# ─────────────────────────────────────────────────────────────────────────────

def _cmd_new(argv: List[str]) -> int:
    from corpussmith.projects.workspace import Project

    force_wizard = _pop_flag(argv, "--wizard", "-w")
    skip_wizard = _pop_flag(argv, "--skip-wizard", "--no-wizard")

    name = _pop_option(argv, "--name", "-n")
    goal = _pop_option(argv, "--goal", "-g", default="")
    kind = _pop_option(argv, "--kind", "-k", default="exploration")
    langs = _pop_option(argv, "--languages", "-l", default="en")
    field = _pop_option(argv, "--field", default="")
    recency = _pop_option(argv, "--recency", default="any")
    trust_floor = _pop_option(argv, "--trust-floor", default="any")

    path_str = argv[0] if argv else "."
    root = Path(path_str).expanduser().resolve()

    # Wizard decision: explicit --wizard wins, --skip-wizard wins against auto.
    # Otherwise, launch the wizard when no power-user flags were supplied AND
    # stdin is a TTY (interactive). This keeps `corpussmith new` beginner-
    # friendly while preserving scriptability.
    no_flag_path = (
        name is None and not goal and kind == "exploration"
        and langs == "en" and not field
        and recency == "any" and trust_floor == "any"
    )
    want_wizard = force_wizard or (not skip_wizard and no_flag_path and sys.stdin.isatty())

    if want_wizard:
        from corpussmith.app.onboarding import run_wizard
        answers = run_wizard(sys.stdin, sys.stdout, default_name=root.name)
        if answers is None:
            return 1
        try:
            project = Project.create(root=root, **answers.to_project_kwargs())
        except FileExistsError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    else:
        if not name:
            name = root.name
        try:
            project = Project.create(
                root=root,
                name=name,
                research_goal=goal or "",
                project_kind=kind,
                languages=[s.strip() for s in langs.split(",") if s.strip()],
                research_field=field or "",
                recency=recency,
                trust_floor=trust_floor,
            )
        except FileExistsError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

    print(f"created project '{project.config.name}' at {project.root}")
    for sub in ("sources", "downloads", "corpus", "reports", "exports"):
        print(f"  {sub}/")
    print(f"  project.toml")
    print()
    print("next:")
    print(f"  corpussmith search --project \"{project.root}\" \"<title or question>\"")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# search
# ─────────────────────────────────────────────────────────────────────────────

def _cmd_search(argv: List[str]) -> int:
    from corpussmith.search.query_expansion import expand

    include_multilingual = _pop_flag(argv, "--multilingual")
    include_recency = _pop_flag(argv, "--recent")
    no_review = _pop_flag(argv, "--no-review")
    dry_run = _pop_flag(argv, "--dry-run")
    max_results = int(_pop_option(argv, "--max-results", default="25") or 25)
    min_score = float(_pop_option(argv, "--min-score", default="10") or 10)
    skip_download = _pop_flag(argv, "--no-download")
    brief_from = _pop_option(argv, "--from")

    project = _resolve_project(argv)

    if brief_from:
        from corpussmith.search.brief import extract, BriefExtractionError
        brief_path = Path(brief_from).expanduser().resolve()
        try:
            brief = extract(brief_path)
        except BriefExtractionError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"Loaded research brief: {brief.title}")
        raw = brief.seed_text

        # Copy brief into corpus/
        corpus_dir = project.root / "corpus"
        corpus_dir.mkdir(exist_ok=True)
        import shutil
        dest_brief = corpus_dir / f"brief{brief_path.suffix}"
        shutil.copy2(str(brief_path), str(dest_brief))
        extracted_path = corpus_dir / "brief.extracted.txt"
        extracted_path.write_text(brief.seed_text, encoding="utf-8")
    else:
        raw = " ".join(argv).strip()

    if not raw:
        print("error: provide a title, question, or keyword list", file=sys.stderr)
        return 1

    plan = expand(
        raw,
        include_review=not no_review,
        include_recency=include_recency,
        include_multilingual=include_multilingual,
    )
    print(plan.pretty())

    project.record_search(raw, plan.classification, len(plan.queries))

    if dry_run:
        print("\n--dry-run: not executing harvest")
        return 0

    from corpussmith._legacy import run_harvest, _print_harvest_final
    subjects = plan.as_subject_strings()
    print(f"\nrunning harvest with {len(subjects)} subject(s): {subjects}")
    result = run_harvest(
        subjects=subjects,
        output_dir=project.root,
        max_results=max_results,
        min_score=min_score,
        max_downloads=100,
        skip_download=skip_download,
        verbose=False,
    )
    _print_harvest_final(result)
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# search-draft  (Premium)
# ─────────────────────────────────────────────────────────────────────────────

def _cmd_search_draft(argv: List[str]) -> int:
    """corpussmith search-draft [--project DIR] [options] DRAFT_PATH

    Premium feature. Reads a PDF, DOCX, or plain-text draft and seeds a
    full 20-source literature harvest from the document's own language —
    no keyword typing required.

    Options
    -------
    --max-results N    Results per source (default: 25)
    --min-score N      Relevance threshold (default: 10)
    --no-download      Metadata only, skip file downloads
    --dry-run          Show query plan without running harvest
    --multilingual     Add multilingual query variants
    --recent           Bias toward recent publications
    --no-review        Skip review/meta-analysis query variant
    """
    from corpussmith.premium import require
    require("search-draft")

    include_multilingual = _pop_flag(argv, "--multilingual")
    include_recency      = _pop_flag(argv, "--recent")
    no_review            = _pop_flag(argv, "--no-review")
    dry_run              = _pop_flag(argv, "--dry-run")
    max_results          = int(_pop_option(argv, "--max-results", default="25") or 25)
    min_score            = float(_pop_option(argv, "--min-score", default="10") or 10)
    skip_download        = _pop_flag(argv, "--no-download")

    project = _resolve_project(argv)

    draft_path: Optional[Path] = None
    for arg in argv:
        if not arg.startswith("-"):
            draft_path = Path(arg).expanduser().resolve()
            break

    if draft_path is None:
        print("error: specify a draft file (PDF, DOCX, or TXT)", file=sys.stderr)
        print("  corpussmith search-draft --project DIR path/to/draft.pdf", file=sys.stderr)
        return 1

    if not draft_path.exists():
        print(f"error: file not found: {draft_path}", file=sys.stderr)
        return 1

    from corpussmith.premium.search_draft import SUPPORTED_EXTENSIONS
    if draft_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        exts = "  ".join(sorted(SUPPORTED_EXTENSIONS))
        print(f"error: unsupported format '{draft_path.suffix}'. Supported: {exts}", file=sys.stderr)
        return 1

    print(f"\n  [search-draft]  reading {draft_path.name} …")
    try:
        from corpussmith.premium.search_draft import extract_seed
        seed = extract_seed(draft_path)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not seed.as_query_string():
        print("error: could not extract readable text from the document.", file=sys.stderr)
        print("  Install pypdf (PDF) or python-docx (DOCX) for best results.", file=sys.stderr)
        return 1

    print()
    print(f"  Title   : {seed.title[:100]}" if seed.title else "  (no title line detected)")
    if seed.salient_phrases:
        print(f"  Phrases : {' · '.join(seed.salient_phrases[:6])}")
    print()

    from corpussmith.search.query_expansion import expand
    from corpussmith.search.query_plan import Query

    plan = expand(
        seed.as_query_string(),
        include_review=not no_review,
        include_recency=include_recency,
        include_multilingual=include_multilingual,
    )

    for phrase in seed.extra_phrases(n=3):
        plan.queries.append(
            Query(f'"{phrase}"', "draft-phrase", "salient phrase from draft body")
        )

    print(plan.pretty())
    project.record_search(seed.as_query_string(), f"search-draft:{plan.classification}", len(plan.queries))

    if dry_run:
        print("\n--dry-run: not executing harvest")
        return 0

    from corpussmith._legacy import run_harvest, _print_harvest_final
    subjects = plan.as_subject_strings()
    print(f"\nrunning harvest with {len(subjects)} subject(s): {subjects}")
    result = run_harvest(
        subjects=subjects,
        output_dir=project.root,
        max_results=max_results,
        min_score=min_score,
        max_downloads=100,
        skip_download=skip_download,
        verbose=False,
    )
    _print_harvest_final(result)
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# import
# ─────────────────────────────────────────────────────────────────────────────

def _cmd_import(argv: List[str]) -> int:
    import shutil
    project = _resolve_project(argv)
    if not argv:
        print("error: specify a source directory to import", file=sys.stderr)
        return 1
    src = Path(argv[0]).expanduser().resolve()
    if not src.exists():
        print(f"error: {src} does not exist", file=sys.stderr)
        return 1

    dst = project.corpus_dir
    dst.mkdir(exist_ok=True)
    copied = 0
    if src.is_file():
        shutil.copy2(src, dst / src.name)
        copied = 1
    else:
        for f in src.rglob("*"):
            if f.is_file():
                rel = f.relative_to(src)
                target = dst / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, target)
                copied += 1

    project.config.imports_run += 1
    project.save()
    print(f"imported {copied} file(s) into {dst}")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# build
# ─────────────────────────────────────────────────────────────────────────────

def _cmd_build(argv: List[str]) -> int:
    from corpussmith._legacy import run_forge, _print_forge_final, CHUNK_SIZE_DEFAULT, CHUNK_OVERLAP_DEFAULT
    project = _resolve_project(argv)
    chunk_size = int(_pop_option(argv, "--chunk-size", default=str(CHUNK_SIZE_DEFAULT)))
    overlap = int(_pop_option(argv, "--overlap", default=str(CHUNK_OVERLAP_DEFAULT)))

    # Build runs over corpus/ and downloads/ combined — we pass corpus_dir;
    # users can re-run with --source downloads if they want that subset only.
    source = _pop_option(argv, "--source", default="all")
    if source == "corpus":
        src = project.corpus_dir
    elif source == "downloads":
        src = project.downloads_dir
    else:
        src = project.root  # scans both plus exports/, filtered by iter_files

    out = project.exports_dir / "knowledge_export"
    summary = run_forge(
        source_dir=src,
        output_dir=out,
        chunk_size=chunk_size,
        overlap=overlap,
        include_extensions=None,
        include_hidden=False,
        verbose=False,
    )
    project.config.builds_run += 1
    project.save()
    _print_forge_final(summary, out)
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# review-project
# ─────────────────────────────────────────────────────────────────────────────

def _cmd_review(argv: List[str]) -> int:
    from corpussmith.projects.report import build_report
    project = _resolve_project(argv)
    print(build_report(project))
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# export  (Stage 6 — provenance-aware exports)
# ─────────────────────────────────────────────────────────────────────────────

def _cmd_export(argv: List[str]) -> int:
    """corpussmith export --format bibtex|csljson|markdown [--input PATH] [-o OUT]

    With `--project` (default cwd), reads the project's harvested records and
    writes the export under `exports/`. With `--input`, reads any JSONL file.
    """
    from corpussmith.exports import find_project_records, load_records

    fmt = (_pop_option(argv, "--format", "-f", default="bibtex") or "bibtex").lower()
    output = _pop_option(argv, "--output", "-o")
    input_path = _pop_option(argv, "--input", "-i")
    title = _pop_option(argv, "--title", default="Bibliography")

    if fmt not in {"bibtex", "csljson", "markdown"}:
        print(f"error: unknown format '{fmt}' (choose bibtex / csljson / markdown)",
              file=sys.stderr)
        return 2

    if input_path:
        records_path = Path(input_path).expanduser().resolve()
        if not records_path.exists():
            print(f"error: {records_path} does not exist", file=sys.stderr)
            return 1
        project = None
        default_out_dir = Path.cwd()
    else:
        project = _resolve_project(argv)
        records_path = find_project_records(project.root)
        if records_path is None:
            print("error: no harvest records found. Run `corpussmith search` first.",
                  file=sys.stderr)
            return 1
        default_out_dir = project.exports_dir

    records = load_records(records_path)
    if not records:
        print(f"error: no records in {records_path}", file=sys.stderr)
        return 1

    ext = {"bibtex": "bib", "csljson": "json", "markdown": "md"}[fmt]
    out_path = Path(output).expanduser().resolve() if output else default_out_dir / f"bibliography.{ext}"

    if fmt == "bibtex":
        from corpussmith.exports import bibtex
        count = bibtex.write(records, out_path)
    elif fmt == "csljson":
        from corpussmith.exports import csljson
        count = csljson.write(records, out_path)
    else:
        from corpussmith.exports import markdown as md_export
        count = md_export.write(records, out_path, title=title)

    print(f"wrote {count} record(s) to {out_path}")
    if project is not None:
        project.config.exports_run = getattr(project.config, "exports_run", 0) + 1
        project.save()
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# config  (global API key inspection + template creation)
# ─────────────────────────────────────────────────────────────────────────────

def _cmd_config(argv: List[str]) -> int:
    """corpussmith config [--init]

    Without flags: show which API keys are currently loaded and where they
    came from (env var / ~/.corpussmith.toml / .env).

    With --init: create a commented ~/.corpussmith.toml template if one
    does not already exist.
    """
    from corpussmith.config.global_config import (
        get_api_keys, global_config_path, write_global_config_template,
        _ENV_MAP,
    )

    init = _pop_flag(argv, "--init")

    if init:
        path = write_global_config_template()
        if path.exists():
            print(f"config file ready at: {path}")
            print("Open it in a text editor and fill in your API keys.")
        return 0

    keys = get_api_keys()
    cfg_path = global_config_path()

    print("Corpus Smith — API key configuration")
    print(f"  global config : {cfg_path} {'(exists)' if cfg_path.exists() else '(not found)'}")
    print()

    _LABELS = {
        "core_api_key":         ("CORE",             "https://core.ac.uk/services/api"),
        "semantic_scholar_key": ("Semantic Scholar",  "https://www.semanticscholar.org/product/api"),
        "elsevier_api_key":     ("Elsevier TDM",      "https://dev.elsevier.com/"),
        "wiley_api_key":        ("Wiley TDM",         "https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining"),
    }

    import os
    from corpussmith.config.global_config import _ENV_ALIASES, _load_global_toml, _find_dotenv, _load_dotenv
    toml_vals = _load_global_toml()
    dotenv_path = _find_dotenv()
    dotenv_vals = _load_dotenv(dotenv_path) if dotenv_path else {}

    any_key = False
    for field_name, (label, signup_url) in _LABELS.items():
        value = getattr(keys, field_name)
        env_name = _ENV_MAP.get(field_name, "")
        if value:
            any_key = True
            # Determine source
            if os.environ.get(env_name) or any(os.environ.get(a) for a in _ENV_ALIASES.get(field_name, [])):
                source = "environment variable"
            elif field_name in toml_vals:
                source = f"~/.corpussmith.toml"
            else:
                source = f".env ({dotenv_path})"
            masked = value[:4] + "..." + value[-4:] if len(value) > 8 else "****"
            print(f"  {label:<20} {masked}  (from {source})")
        else:
            print(f"  {label:<20} not set   (sign up: {signup_url})")

    print()
    if not any_key:
        print("No API keys configured. Corpus Smith works without them,")
        print("but keys improve rate limits and result quality.")
        print()
        print("To add keys, run:")
        print("  corpussmith config --init")
        print("Then edit ~/.corpussmith.toml")
    else:
        print("Keys marked 'not set' are optional — Corpus Smith works without them.")

    return 0


# ─────────────────────────────────────────────────────────────────────────────
# premium  (Stage 8 — activation status + seam listing)
# ─────────────────────────────────────────────────────────────────────────────

_PREMIUM_FEATURES = [
    ("search-draft",   "Seed a literature search from a draft PDF, DOCX, or TXT"),
    ("atlas",          "Citation / co-citation graph over your corpus"),
    ("clusters",       "Topic clustering across harvested records"),
    ("contradictions", "Claim-conflict detection between sources"),
    ("thesis-pack",    "Thesis scaffold export (chapters + literature matrix)"),
    ("book-pack",      "Book scaffold export (front matter + chapters + bib)"),
    ("memory-graph",   "Persistent cross-project research graph"),
]


def _cmd_premium(argv: List[str]) -> int:
    """corpussmith premium [--status | --features]

    Show activation status and the list of premium seams. All entry points
    raise PremiumNotAvailableError when called without activation.
    """
    from corpussmith import premium as _premium

    status = _premium.get_status()
    show_features = _pop_flag(argv, "--features", "-l") or not argv

    print("Corpus Smith — Premium")
    if status.active:
        src = {"env": "environment variable",
               "config": "~/.corpussmith.toml",
               "unlock": "test unlock flag"}.get(status.source, status.source)
        print(f"  status : ACTIVE ({status.key_preview}, from {src})")
    else:
        print("  status : inactive")
        print("  activate by setting CORPUSSMITH_PREMIUM_KEY, or by adding")
        print("  a [premium] license_key = \"...\" block to ~/.corpussmith.toml")

    if show_features:
        print()
        print("Seams:")
        for name, desc in _PREMIUM_FEATURES:
            mark = "✓" if status.active else "·"
            print(f"  {mark} {name:<16} {desc}")

    return 0


# ─────────────────────────────────────────────────────────────────────────────
# cache  (Stage 13)
# ─────────────────────────────────────────────────────────────────────────────

def _cmd_cache(argv: List[str]) -> int:
    """corpussmith cache [stats|clear|show|export] [args...]

    Subcommands
    -----------
    stats          (default) Show cache statistics.
    clear [--yes]  Delete the cache file.
    show QUERY     Show nearest cached titles for QUERY.
    export PATH    Dump cache to a JSONL or CSV file.
    """
    sub = argv[0] if argv else "stats"
    rest = argv[1:] if argv else []

    if sub == "stats":
        return _cache_stats()
    if sub == "clear":
        return _cache_clear(rest)
    if sub == "show":
        return _cache_show(rest)
    if sub == "export":
        return _cache_export(rest)
    print(f"unknown subcommand: {sub!r}", file=sys.stderr)
    print("usage: corpussmith cache [stats|clear|show|export]", file=sys.stderr)
    return 1


def _cache_stats() -> int:
    from corpussmith.search.concept_cache import stats, cache_path
    s = stats()
    if not s["exists"] or s["records"] == 0:
        print("concept cache: not yet created")
        return 0
    n = s["records"]
    warm = s.get("warming_up", n < 8)
    status = "warming up" if warm else "active"
    print(f"concept cache:")
    print(f"  records  : {n}  ({status})")
    if not warm and s.get("top_domains"):
        print("  top domains:")
        for name, count in s["top_domains"][:5]:
            print(f"    {count:>4}×  {name}")
    print(f"  path     : {cache_path()}")
    return 0


def _cache_clear(argv: List[str]) -> int:
    from corpussmith.search.concept_cache import cache_path
    yes = _pop_flag(argv, "--yes", "-y")
    path = cache_path()
    if not path.exists():
        print("nothing to clear — cache does not exist yet")
        return 0
    if not yes:
        try:
            answer = input(f"Delete {path}? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("Aborted.", file=sys.stderr)
            return 1
    path.unlink()
    print(f"removed: {path}")
    return 0


def _cache_show(argv: List[str]) -> int:
    if not argv:
        print("error: provide a probe title after 'cache show'", file=sys.stderr)
        return 1
    query = " ".join(argv)
    from corpussmith.search.concept_cache import lookup, load_all
    records = load_all()
    n = len(records)
    result = lookup(query, min_cache_records=1, min_similarity=0.15)
    if result is None or not result.sample_titles:
        print(f"no neighbour above similarity threshold (cache has {n} record(s))")
        return 0
    print(f"nearest cached titles for: {query!r}")
    for entry in result.sample_titles:
        print(f"  {entry}")
    return 0


def _cache_export(argv: List[str]) -> int:
    import csv
    from corpussmith.search.concept_cache import load_all
    if not argv:
        print("error: specify output path", file=sys.stderr)
        return 1
    out_path = Path(argv[0]).expanduser().resolve()
    records = load_all()
    ext = out_path.suffix.lower()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if ext == ".csv":
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["title", "ts", "concept_name", "cross_paper_count",
                             "avg_score", "openalex_id", "level"])
            for r in records:
                for c in r.concepts:
                    writer.writerow([
                        r.title, r.ts,
                        c.get("name", ""), c.get("cross_paper_count", ""),
                        c.get("avg_score", ""), c.get("openalex_id", ""),
                        c.get("level", ""),
                    ])
    else:
        import json
        with out_path.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps({"title": r.title, "ts": r.ts,
                                    "concepts": r.concepts},
                                   ensure_ascii=False) + "\n")

    print(f"exported {len(records)} record(s) to {out_path}")
    return 0


__all__ = ["main"]
