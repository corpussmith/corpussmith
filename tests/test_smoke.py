"""Smoke tests — Stage 1 must never regress these.

Works with either pytest or `python -m unittest discover tests`.
"""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SmokeTests(unittest.TestCase):
    def test_package_imports(self):
        import corpussmith
        self.assertTrue(corpussmith.__version__)
        from corpussmith.app.cli import main
        self.assertTrue(callable(main))

    def test_version_flag_matches_package(self):
        import corpussmith
        result = subprocess.run(
            [sys.executable, str(ROOT / "corpussmith.py"), "--no-banner", "--version"],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn(corpussmith.__version__, result.stdout)

    def test_deps_flag_exits_cleanly(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "corpussmith.py"), "--no-banner", "--deps"],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0)

    def test_python_m_corpussmith(self):
        result = subprocess.run(
            [sys.executable, "-m", "corpussmith", "--no-banner", "--version"],
            capture_output=True, text=True, timeout=15,
            cwd=str(ROOT),
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
