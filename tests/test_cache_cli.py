"""Tests for Stage 13 — `corpussmith cache` CLI verb."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import unittest
from pathlib import Path

from corpussmith.search import concept_cache
from corpussmith.search.enrich import EnrichedConcept, EnrichmentResult


ROOT = Path(__file__).resolve().parents[1]
SF = [sys.executable, str(ROOT / "corpussmith.py"), "--no-banner"]


def _seed(n=10):
    """Pre-seed the cache with N records to clear the warm-up floor."""
    for i in range(n):
        result = EnrichmentResult(
            concepts=[
                EnrichedConcept(
                    name="Attention deficit hyperactivity disorder",
                    cross_paper_count=5, avg_score=0.7,
                    openalex_id="C2779394", level=2),
                EnrichedConcept(
                    name="Cognitive behavioral therapy",
                    cross_paper_count=4, avg_score=0.6,
                    openalex_id="C2780665704", level=3),
            ],
            keywords=[],
        )
        concept_cache.append(f"Test ADHD title number {i}", result)


class CacheStatsTests(unittest.TestCase):
    def test_stats_on_empty_cache(self):
        r = subprocess.run(SF + ["cache", "stats"], capture_output=True,
                           text=True, env=_env(), check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("not yet created", r.stdout)

    def test_stats_default_subcommand(self):
        # No subcommand should default to `stats`.
        _seed(3)
        r = subprocess.run(SF + ["cache"], capture_output=True,
                           text=True, env=_env(), check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("records  :", r.stdout)
        self.assertIn("warming up", r.stdout)  # 3 < 8 → still warming

    def test_stats_active_after_floor(self):
        _seed(10)
        r = subprocess.run(SF + ["cache", "stats"], capture_output=True,
                           text=True, env=_env(), check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("active", r.stdout)
        self.assertIn("Attention deficit hyperactivity disorder", r.stdout)


class CacheClearTests(unittest.TestCase):
    def test_clear_empty_cache_is_noop(self):
        r = subprocess.run(SF + ["cache", "clear", "--yes"],
                           capture_output=True, text=True, env=_env(), check=False)
        self.assertEqual(r.returncode, 0)
        self.assertIn("nothing to clear", r.stdout)

    def test_clear_with_yes_removes_file(self):
        _seed(3)
        self.assertTrue(concept_cache.cache_path().exists())
        r = subprocess.run(SF + ["cache", "clear", "--yes"],
                           capture_output=True, text=True, env=_env(), check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("removed", r.stdout)
        self.assertFalse(concept_cache.cache_path().exists())

    def test_clear_without_yes_requires_confirmation(self):
        _seed(3)
        r = subprocess.run(SF + ["cache", "clear"],
                           input="no\n", capture_output=True, text=True,
                           env=_env(), check=False)
        # Without "yes" confirmation we exit non-zero and leave the file.
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(concept_cache.cache_path().exists())


class CacheShowTests(unittest.TestCase):
    def test_show_returns_neighbours(self):
        _seed(8)
        r = subprocess.run(SF + ["cache", "show",
                                 "ADHD non-pharmacological intervention"],
                           capture_output=True, text=True, env=_env(), check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("nearest cached titles", r.stdout)
        self.assertIn("Test ADHD title number", r.stdout)

    def test_show_unrelated_query_reports_no_neighbour(self):
        _seed(8)
        r = subprocess.run(SF + ["cache", "show",
                                 "quantum chromodynamics lattice gauge"],
                           capture_output=True, text=True, env=_env(), check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no neighbour above similarity", r.stdout)

    def test_show_without_argument_errors(self):
        r = subprocess.run(SF + ["cache", "show"],
                           capture_output=True, text=True, env=_env(), check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("provide a probe title", r.stderr)


class CacheExportTests(unittest.TestCase):
    def test_export_jsonl_default(self):
        import tempfile
        _seed(3)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dump.jsonl"
            r = subprocess.run(SF + ["cache", "export", str(out)],
                               capture_output=True, text=True, env=_env(),
                               check=False)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(out.exists())
            with out.open() as f:
                lines = [json.loads(l) for l in f if l.strip()]
            self.assertEqual(len(lines), 3)
            self.assertIn("title", lines[0])

    def test_export_csv_format(self):
        import tempfile
        _seed(2)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dump.csv"
            r = subprocess.run(SF + ["cache", "export", str(out)],
                               capture_output=True, text=True, env=_env(),
                               check=False)
            self.assertEqual(r.returncode, 0, r.stderr)
            with out.open() as f:
                rows = list(csv.reader(f))
            self.assertEqual(rows[0][:3], ["title", "ts", "concept_name"])
            # 2 records × 2 concepts each = 4 data rows + 1 header.
            self.assertEqual(len(rows), 5)


class UnknownSubcommandTests(unittest.TestCase):
    def test_unknown_subcommand_exits_with_usage(self):
        r = subprocess.run(SF + ["cache", "wat"], capture_output=True,
                           text=True, env=_env(), check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unknown subcommand", r.stderr)


def _env():
    """Inherit env + force the cache dir to the per-test tmp the autouse
    fixture set up. Subprocess cli runs need this env passed through."""
    import os
    return {
        **os.environ,
        # autouse conftest set CORPUSSMITH_CACHE_DIR to a tmp path; pass it
        # through to the subprocess so it sees the same isolation.
    }


if __name__ == "__main__":
    unittest.main()
