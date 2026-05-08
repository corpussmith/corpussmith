"""Stage 8 — premium seams.

Verifies:
  * every premium entry point raises PremiumNotAvailableError when inactive
  * activation via SCHOLARFORGE_PREMIUM_UNLOCK flips the gate on
  * SCHOLARFORGE_PREMIUM_KEY is honoured
  * ~/.corpussmith.toml [premium] license_key is honoured
  * freemium code does not import premium internals
  * `corpussmith premium` CLI shows status without crashing
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SF = [sys.executable, str(ROOT / "corpussmith.py"), "--no-banner"]


def _clear_premium_env(env: dict) -> dict:
    for k in ("SCHOLARFORGE_PREMIUM_KEY", "SCHOLARFORGE_PREMIUM_UNLOCK"):
        env.pop(k, None)
    return env


class PremiumGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = os.environ.copy()
        _clear_premium_env(os.environ)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._orig)

    def test_inactive_by_default(self) -> None:
        from corpussmith import premium
        self.assertFalse(premium.is_active())
        self.assertEqual(premium.get_status().source, "none")

    def test_unlock_flag_activates(self) -> None:
        os.environ["SCHOLARFORGE_PREMIUM_UNLOCK"] = "1"
        from corpussmith import premium
        self.assertTrue(premium.is_active())
        self.assertEqual(premium.get_status().source, "unlock")

    def test_env_key_activates(self) -> None:
        os.environ["SCHOLARFORGE_PREMIUM_KEY"] = "abcd-efgh-ijkl-mnop"
        from corpussmith import premium
        status = premium.get_status()
        self.assertTrue(status.active)
        self.assertEqual(status.source, "env")
        self.assertIn("...", status.key_preview)

    def test_toml_license_activates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / ".corpussmith.toml"
            cfg.write_text(textwrap.dedent("""
                [premium]
                license_key = "tomlkey-0000-ffff"
            """).strip(), encoding="utf-8")
            with mock.patch(
                "corpussmith.config.global_config.global_config_path",
                return_value=cfg,
            ):
                from corpussmith import premium
                status = premium.get_status()
                self.assertTrue(status.active)
                self.assertEqual(status.source, "config")

    def test_atlas_gated(self) -> None:
        from corpussmith.premium import atlas, PremiumNotAvailableError
        with self.assertRaises(PremiumNotAvailableError):
            atlas.build([])

    def test_clusters_gated(self) -> None:
        from corpussmith.premium import clusters, PremiumNotAvailableError
        with self.assertRaises(PremiumNotAvailableError):
            clusters.cluster([])

    def test_contradictions_gated(self) -> None:
        from corpussmith.premium import contradictions, PremiumNotAvailableError
        with self.assertRaises(PremiumNotAvailableError):
            contradictions.scan([])

    def test_thesis_pack_gated(self) -> None:
        from corpussmith.premium import thesis_pack, PremiumNotAvailableError
        with self.assertRaises(PremiumNotAvailableError):
            thesis_pack.export([], title="X", output_dir=Path("."))

    def test_book_pack_gated(self) -> None:
        from corpussmith.premium import book_pack, PremiumNotAvailableError
        with self.assertRaises(PremiumNotAvailableError):
            book_pack.export([], title="X", author="Y", output_dir=Path("."))

    def test_memory_graph_gated(self) -> None:
        from corpussmith.premium import memory_graph, PremiumNotAvailableError
        with self.assertRaises(PremiumNotAvailableError):
            memory_graph.ingest([], project_id="x")
        with self.assertRaises(PremiumNotAvailableError):
            memory_graph.query("x")

    def test_activated_atlas_passes_gate(self) -> None:
        """With unlock, premium entry points pass the gate and reach the
        NotImplementedError placeholder — proving activation flow works."""
        os.environ["SCHOLARFORGE_PREMIUM_UNLOCK"] = "1"
        from corpussmith.premium import atlas
        with self.assertRaises(NotImplementedError):
            atlas.build([])


class FreemiumPurityTests(unittest.TestCase):
    """Freemium packages must never import corpussmith.premium internals."""

    FREEMIUM = [
        "app", "search", "sources", "projects", "exports",
        "harvest", "forge", "provenance", "net", "config",
        "utils", "tui",
    ]

    def test_no_freemium_file_imports_premium_submodule(self) -> None:
        pkg_root = ROOT / "corpussmith"
        bad: list[str] = []
        for sub in self.FREEMIUM:
            d = pkg_root / sub
            if not d.is_dir():
                continue
            for py in d.rglob("*.py"):
                text = py.read_text(encoding="utf-8", errors="ignore")
                # Freemium may reference `corpussmith.premium` loosely for
                # activation checks via the top-level module only — but must
                # never pull submodules (atlas/clusters/etc.) directly.
                for bad_import in (
                    "from corpussmith.premium.atlas",
                    "from corpussmith.premium.clusters",
                    "from corpussmith.premium.contradictions",
                    "from corpussmith.premium.thesis_pack",
                    "from corpussmith.premium.book_pack",
                    "from corpussmith.premium.memory_graph",
                    "import corpussmith.premium.atlas",
                    "import corpussmith.premium.clusters",
                ):
                    if bad_import in text:
                        bad.append(f"{py.relative_to(ROOT)}: {bad_import}")
        self.assertEqual(bad, [], f"freemium leaks into premium: {bad}")


class PremiumCLITests(unittest.TestCase):
    def _run(self, *args: str, env_extra: dict | None = None):
        env = os.environ.copy()
        _clear_premium_env(env)
        env["PYTHONPATH"] = str(ROOT)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            SF + list(args),
            capture_output=True, text=True, env=env, timeout=30,
        )

    def test_premium_cli_inactive(self) -> None:
        r = self._run("premium")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("inactive", r.stdout.lower())
        self.assertIn("atlas", r.stdout)

    def test_premium_cli_active_via_unlock(self) -> None:
        r = self._run("premium", env_extra={"SCHOLARFORGE_PREMIUM_UNLOCK": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("active", r.stdout.lower())


if __name__ == "__main__":
    unittest.main()
