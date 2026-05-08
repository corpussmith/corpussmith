"""Tests for research-brief extraction (search.brief) and the
`corpussmith search --from <file>` / wizard hook flows.

Plain-text + Markdown fixtures run everywhere. The .docx and .pdf paths are
guarded by importorskip so the suite stays green on machines without the
optional pypdf / python-docx libraries.
"""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

from corpussmith.search.brief import (
    Brief,
    BriefExtractionError,
    extract,
    SUPPORTED_EXTS,
)
from corpussmith.search.query_expansion import expand
from corpussmith.app.onboarding import WizardAnswers, run_wizard


ROOT = Path(__file__).resolve().parents[1]
SF = [sys.executable, str(ROOT / "corpussmith.py"), "--no-banner"]


# ─────────────────────────────────────────────────────────────────────────────
# Sample brief — modelled on the researcher's PhD concept document
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_TITLE = (
    "Neurobiological and Relational Determinants of the Capacity to Love"
)

SAMPLE_BRIEF_MD = f"""# {SAMPLE_TITLE}

## Core Concept

The capacity to love is conceptualized as an emergent neuropsychiatric
function arising from the interaction between biological integrity, neural
processing (Theory of Mind), developmental modulation (trauma), and
personality organization, with breakdowns manifesting across distinct
psychopathological spectra such as psychosis and eating disorders.

## Key Mechanistic Axes

- Neurovascular–Metabolic Axis: brain circulation and blood markers
  influence functional connectivity, particularly emotional regulation.
- Social Cognition Axis: fMRI patterns correlate with Theory of Mind
  performance; neuropsychiatric nuances act as intermediate phenotypes.
- Trauma as a System-Wide Modifier: affects vascular reactivity,
  inflammation, neural connectivity, and personality development.

## Why this works as a PhD concept

It integrates biological data (fMRI, biomarkers), cognitive constructs
(Theory of Mind), personality structures, and clinical outcomes under a
unified transdiagnostic framework centered on the capacity to love.
"""


SAMPLE_BRIEF_PLAIN = f"""{SAMPLE_TITLE}

CORE CONCEPT
The capacity to love is conceptualized as an emergent neuropsychiatric
function arising from the interaction between biological integrity, neural
processing (Theory of Mind), developmental modulation (trauma), and
personality organization.

KEY MECHANISTIC AXES
Neurovascular-Metabolic, Social Cognition, Trauma as a System-Wide Modifier,
Personality as Structural Mediator, Capacity to Love as an Integrative
Endpoint.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Pure extractor tests
# ─────────────────────────────────────────────────────────────────────────────

class ExtractorTests(unittest.TestCase):
    def test_supported_exts(self):
        for ext in (".txt", ".md", ".markdown", ".rst", ".docx", ".pdf"):
            self.assertIn(ext, SUPPORTED_EXTS)

    def test_unsupported_extension_raises(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "brief.html"
            p.write_text("<p>nope</p>", encoding="utf-8")
            with self.assertRaises(BriefExtractionError):
                extract(p)

    def test_missing_file_raises(self):
        with self.assertRaises(BriefExtractionError):
            extract(Path("/nonexistent/path/brief.txt"))

    def test_empty_file_raises(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "empty.txt"
            p.write_text("", encoding="utf-8")
            with self.assertRaises(BriefExtractionError):
                extract(p)

    def test_markdown_brief_distillation(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "brief.md"
            p.write_text(SAMPLE_BRIEF_MD, encoding="utf-8")
            brief = extract(p)

        self.assertEqual(brief.title, SAMPLE_TITLE)
        # We expect the markdown anchor headings to be picked up.
        names = {n for n, _ in brief.anchor_sections}
        self.assertIn("core concept", names)
        # The seed combines title with anchor body and stays under the cap.
        seed = brief.seed_text
        self.assertTrue(seed.startswith(SAMPLE_TITLE))
        self.assertIn("capacity to love", seed.lower())
        self.assertLessEqual(len(seed), 600)

    def test_plain_text_brief_falls_back_to_caps_headings_or_opening(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "brief.txt"
            p.write_text(SAMPLE_BRIEF_PLAIN, encoding="utf-8")
            brief = extract(p)
        self.assertEqual(brief.title, SAMPLE_TITLE)
        self.assertIn("capacity to love", brief.seed_text.lower())


# ─────────────────────────────────────────────────────────────────────────────
# End-to-end: brief → query_expansion → plan with anchor terms
# ─────────────────────────────────────────────────────────────────────────────

class BriefDrivesQueryExpansionTests(unittest.TestCase):
    def test_brief_seed_produces_useful_query_plan(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "brief.md"
            p.write_text(SAMPLE_BRIEF_MD, encoding="utf-8")
            brief = extract(p)
        plan = expand(brief.seed_text)
        self.assertGreaterEqual(len(plan.queries), 1)
        all_query_text = " ".join(q.text for q in plan.queries).lower()
        # An anchor concept from the brief should survive into the plan.
        self.assertTrue(
            "capacity to love" in all_query_text
            or "neurobiological" in all_query_text
            or "neuropsychiatric" in all_query_text,
            f"expected an anchor concept in queries, got: {all_query_text}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# CLI integration: `corpussmith search --from <file>`
# ─────────────────────────────────────────────────────────────────────────────

class CliFromFlagTests(unittest.TestCase):
    def test_search_from_dry_run_with_markdown_brief(self):
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "proj"
            brief_path = Path(td) / "brief.md"
            brief_path.write_text(SAMPLE_BRIEF_MD, encoding="utf-8")

            # Create the project non-interactively first.
            r = subprocess.run(
                SF + ["new", "--skip-wizard", "--name", "love-study", str(project_dir)],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(r.returncode, 0, r.stderr)

            # Now run search --from --dry-run.
            r = subprocess.run(
                SF + ["search", "--project", str(project_dir),
                      "--from", str(brief_path), "--dry-run"],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Loaded research brief", r.stdout)
            self.assertIn(SAMPLE_TITLE.split(":")[0], r.stdout)
            self.assertIn("--dry-run", r.stdout)
            # Brief was persisted into corpus/.
            corpus_files = list((project_dir / "corpus").glob("*"))
            names = {f.name for f in corpus_files}
            self.assertIn("brief.md", names)
            self.assertIn("brief.extracted.txt", names)


# ─────────────────────────────────────────────────────────────────────────────
# Wizard hook
# ─────────────────────────────────────────────────────────────────────────────

class WizardBriefHookTests(unittest.TestCase):
    def test_wizard_captures_brief_path(self):
        # Drive the wizard with stdin lines accepting all defaults until the
        # brief question, then say "y" + a path, then "y" to confirm.
        # Wizard order: name, goal, field, kind, recency, trust, languages,
        # brief?, brief path, confirm.
        # Nine required prompts before confirmation when we say yes to brief.
        stdin = io.StringIO(
            "love-study\n"     # name
            "capacity to love\n"  # goal
            "\n"               # field — accept default
            "\n"               # kind  — accept default
            "\n"               # recency — accept default
            "\n"               # trust — accept default
            "\n"               # languages — accept default
            "y\n"              # yes, I have a brief
            "/tmp/my-brief.md\n"  # path (just captured, not extracted yet)
            "y\n"              # confirm
        )
        stdout = io.StringIO()
        answers = run_wizard(stdin, stdout, default_name="love-study")
        self.assertIsNotNone(answers)
        self.assertEqual(answers.brief_path, "/tmp/my-brief.md")
        # to_project_kwargs must NOT include brief_path (Project.create
        # would reject the kwarg).
        self.assertNotIn("brief_path", answers.to_project_kwargs())

    def test_wizard_skips_brief_when_user_declines(self):
        stdin = io.StringIO(
            "love-study\n" "\n" "\n" "\n" "\n" "\n" "\n"
            "n\n"  # no brief
            "y\n"  # confirm
        )
        stdout = io.StringIO()
        answers = run_wizard(stdin, stdout, default_name="love-study")
        self.assertIsNotNone(answers)
        self.assertEqual(answers.brief_path, "")


# ─────────────────────────────────────────────────────────────────────────────
# Optional-dependency paths (.docx + .pdf)
# ─────────────────────────────────────────────────────────────────────────────

class DocxBriefTests(unittest.TestCase):
    def test_docx_extraction_roundtrip(self):
        docx = pytest.importorskip("docx")
        with tempfile.TemporaryDirectory() as td:
            doc = docx.Document()
            doc.add_heading(SAMPLE_TITLE, level=1)
            doc.add_heading("Core Concept", level=2)
            doc.add_paragraph(
                "The capacity to love is conceptualized as an emergent "
                "neuropsychiatric function."
            )
            p = Path(td) / "brief.docx"
            doc.save(str(p))
            brief = extract(p)
        self.assertIn(SAMPLE_TITLE, brief.title)
        self.assertIn("capacity to love", brief.seed_text.lower())


class PdfBriefTests(unittest.TestCase):
    def test_pdf_extraction_roundtrip(self):
        pytest.importorskip("pypdf")
        rl = pytest.importorskip("reportlab.pdfgen.canvas")
        from reportlab.pdfgen import canvas
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "brief.pdf"
            c = canvas.Canvas(str(p))
            c.drawString(72, 720, SAMPLE_TITLE)
            c.drawString(72, 700, "CORE CONCEPT")
            c.drawString(72, 680,
                         "The capacity to love is conceptualized as emergent.")
            c.save()
            brief = extract(p)
        self.assertIn("capacity to love", brief.seed_text.lower())


if __name__ == "__main__":
    unittest.main()
