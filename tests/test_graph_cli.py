"""Public CLI checks, including an environment where the optional backend is absent."""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eds.cli import main
from eds.install import REPO_ROOT
from eds.knowledge import KnowledgeBase


class GraphCLITests(unittest.TestCase):
    def setUp(self):
        scratch = REPO_ROOT / "output" / "repository-tests" / "tmp"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=scratch, prefix="graph-cli-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "知识库"
        self.root.mkdir()
        for uid, body, relations in (
            ("seed", "uniquealpha", [{"type": "contradicts", "id": "result", "version": "1"}]),
            ("result", "uniquebeta", []),
        ):
            metadata = {"id": uid, "version": "1", "type": "method", "title": uid,
                        "conditions": {}, "sources_missing": True, "sources": [],
                        "relations": relations, "domain": "cae"}
            path = self.root / f"{uid}.md"
            path.write_text("<!-- eds-knowledge: " + json.dumps(metadata) + " -->\n" + body,
                            encoding="utf-8")
            KnowledgeBase(self.root).register(path)

    def cli(self, *args):
        return subprocess.run([sys.executable, "-m", "eds", *args], cwd=REPO_ROOT,
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                              text=True, encoding="utf-8", capture_output=True)

    def test_optional_backend_failure_leaves_ordinary_search_available(self):
        # The base interpreter can run this check even when GraphQLite is not installed.
        with patch("eds.graph.graphqlite", None), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertNotEqual(main(["kb", str(self.root), "graph-sync"]), 0)
        self.assertFalse((self.root / "graph.sqlite3").exists())
        result = self.cli("kb", str(self.root), "search", "uniquealpha")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([item["id"] for item in json.loads(result.stdout)["matches"]], ["seed"])

    def test_graph_runtime_check_reports_failure_without_breaking_default_doctor(self):
        with patch("eds.cli.install_skills", return_value={"in_sync": True}), \
                patch("eds.graph.graphqlite", None), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["doctor", "--graph"]), 1)
            self.assertFalse(json.loads(output.getvalue())["graph"]["available"])
        with patch("eds.cli.install_skills", return_value={"in_sync": True}), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["doctor"]), 0)
            self.assertTrue(json.loads(output.getvalue())["fts5"])

    @unittest.skipUnless(importlib.util.find_spec("graphqlite"), "optional GraphQLite is not installed")
    def test_fresh_process_graph_query_and_source_freshness(self):
        built = self.cli("kb", str(self.root), "sync", "--graph")
        self.assertEqual(built.returncode, 0, built.stderr)
        query = self.cli("kb", str(self.root), "graph-search", "uniquealpha", "--domain", "cae",
                         "--depth", "1", "--relation", "contradicts")
        self.assertEqual(query.returncode, 0, query.stderr)
        self.assertIn('"result"', query.stdout)
        self.assertIn('"contradicts"', query.stdout)
        self.assertNotIn('"uniquebeta"', query.stdout)  # references, not full document expansion
        path = self.root / "seed.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nnew evidence", encoding="utf-8")
        stale = self.cli("kb", str(self.root), "graph-search", "uniquealpha")
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("message", json.loads(stale.stderr))
        rebuilt = self.cli("kb", str(self.root), "rebuild", "--graph")
        self.assertEqual(rebuilt.returncode, 0, rebuilt.stderr)
        self.assertEqual(self.cli("kb", str(self.root), "graph-search", "uniquealpha").returncode, 0)

    def test_graph_status_missing_path_is_read_only(self):
        missing = self.root / "absent"
        result = self.cli("kb", str(missing), "graph-status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(missing.exists())
