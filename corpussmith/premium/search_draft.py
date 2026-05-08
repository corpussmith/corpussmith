"""Premium: search-draft — seed a literature search from a draft document.

Reads a PDF, DOCX, or plain-text draft and extracts a rich, multi-phrase
query seed from its title and body content, then feeds that seed into the
standard 20-source harvest pipeline.

Supported input formats: .pdf  .docx  .txt  .md  .tex  .rtf
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".tex", ".rtf"}
MAX_BODY_CHARS = 4000   # characters of body text fed to phrase extractor
MAX_PHRASES   = 10      # salient phrases extracted from the draft


@dataclass
class DraftSeed:
    """Structured search seed extracted from a draft document."""
    path: Path
    title: str
    body_preview: str              # first 500 chars of body (for display)
    salient_phrases: List[str] = field(default_factory=list)  # from title
    body_phrases: List[str]    = field(default_factory=list)  # novel body phrases
    content_words: List[str]   = field(default_factory=list)

    def as_query_string(self) -> str:
        """Primary query anchor: title, or top phrase if title is missing."""
        return self.title or " ".join(self.salient_phrases[:3])

    def extra_phrases(self, n: int = 3) -> List[str]:
        """Body-specific phrases not dominated by title words, for extra queries."""
        return self.body_phrases[:n]


def _extract_raw_text(path: Path) -> str:
    """Return all text from PDF, DOCX, or plain-text file."""
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            from corpussmith._legacy import read_pdf_pages
            pages = read_pdf_pages(path)
            return "\n".join(pages)
        if ext == ".docx":
            from corpussmith._legacy import read_docx_text
            return read_docx_text(path)
        # .txt / .md / .tex / .rtf and anything else
        from corpussmith._legacy import read_plain_text
        return read_plain_text(path)
    except RuntimeError as exc:
        raise RuntimeError(str(exc)) from exc


def _first_title(lines: List[str]) -> str:
    """Return the first line that looks like a document title (>20 chars, not a heading marker)."""
    for line in lines:
        clean = line.lstrip("#").strip()
        if len(clean) > 20:
            return clean
    return ""


def _is_heading_line(line: str) -> bool:
    """Heuristic: a line is a structural heading if it is ALL-CAPS or very short."""
    stripped = line.strip()
    if not stripped:
        return False
    alpha = [c for c in stripped if c.isalpha()]
    if not alpha:
        return True
    # ALL-CAPS heading (e.g. "BIOLOGICAL SUBSTRATE", "NEUROCOGNITIVE PROCESSING")
    if len(alpha) > 3 and all(c.isupper() for c in alpha):
        return True
    # Very short label (single word or short phrase)
    return len(stripped) < 15


def _normalise_body(lines: List[str]) -> str:
    """Join body lines with sentence delimiters so the phrase extractor treats
    each line as a separate clause. ALL-CAPS headings are title-cased to avoid
    noisy uppercase phrases."""
    parts = []
    for line in lines:
        alpha = [c for c in line if c.isalpha()]
        if alpha and all(c.isupper() for c in alpha):
            line = line.title()
        # Strip bullet markers; ensure every line ends with a sentence boundary
        line = line.lstrip("-–•·* ")
        if line and not line[-1] in ".!?;":
            line = line + "."
        parts.append(line)
    return " ".join(parts)


def extract_seed(path: Path) -> DraftSeed:
    """Read a draft document and return its DraftSeed.

    Steps
    -----
    1. Extract raw text via the existing forge readers.
    2. Identify the document title from the first substantial line.
    3. Normalise ALL-CAPS headings to title-case to avoid noisy phrases.
    4. Run salient_phrases() over title + normalised body (capped at MAX_BODY_CHARS).
    5. Return a DraftSeed ready for query expansion.
    """
    from corpussmith.search.title_parser import salient_phrases, content_words

    raw = _extract_raw_text(path)
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]

    title = _first_title(lines)

    # Body: all lines after the title line, heading-normalised, capped
    body_lines = lines[1:] if title else lines
    body = _normalise_body(body_lines)[:MAX_BODY_CHARS]

    # Title phrases — used as primary query anchor
    title_phrases = salient_phrases(title, max_phrases=6) if title else []

    # Title word set for novelty filtering
    title_words = {w.lower() for w in content_words(title)} if title else set()

    # Body phrases — extract, then filter out any dominated by title words
    raw_body_phrases = salient_phrases(body, max_phrases=MAX_PHRASES * 2)
    body_phrases: List[str] = []
    for ph in raw_body_phrases:
        ph_words = {w.lower() for w in ph.split()}
        overlap = ph_words & title_words
        # Keep phrase only if the majority of its words are novel
        if not ph_words or len(overlap) / len(ph_words) < 0.6:
            body_phrases.append(ph)
        if len(body_phrases) >= MAX_PHRASES:
            break

    words = content_words(f"{title}. {body}")[:40]

    return DraftSeed(
        path=path,
        title=title,
        body_preview=body[:500],
        salient_phrases=title_phrases,
        body_phrases=body_phrases,
        content_words=words,
    )


__all__ = ["DraftSeed", "extract_seed", "SUPPORTED_EXTENSIONS"]
