"""Portable data roots preserve knowledge, presets and studies across locations."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from eds.cli import dispatch, parser
from eds.knowledge import KnowledgeBase
from eds.personal_data import init_data
from eds.presets import PresetStore
from eds.study import StudyStore

REPO = Path(__file__).resolve().parents[1]


class PersonalDataIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary_root = REPO / ".test-tmp"
        temporary_root.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=temporary_root)
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.data = self.workspace / "computer-a" / "EDS-Data"
        self.cache = self.workspace / "cache-a"
        environment = patch.dict(os.environ, {"EDS_DATA_HOME": str(self.data), "EDS_CACHE_HOME": str(self.cache)})
        environment.start()
        self.addCleanup(environment.stop)
        init_data(self.data, user_id="portable-person")
        self.context = {"domain": "cad", "question": "drawing", "user": "portable-person"}

    def invoke(self, *args):
        return dispatch(parser().parse_args(list(map(str, args))))

    def create_fixture(self):
        preset = PresetStore("@knowledge")
        preset.activate("fixture", context=self.context, refs=[])
        snapshot = preset.save_default(context=self.context, overrides={"drawing.layout": "readable"}, source="explicit test")
        study = StudyStore.create("@study/project-1", "Compare options", mode="cad")
        experiment = study.add("experiment", {"question": "Which layout?", "observations": ["readability"], "decision_rule": "No collisions"})
        task = preset.for_task(context=self.context)
        run = study.add_run(experiment_ref=experiment["ref"], input_refs=[], backend="fixture", capability="drawing",
                            input_snapshot={"spec": "fixture"}, execution_preset=task, idempotency_key="draw-1")
        return preset, snapshot, study, run

    def test_managed_runtime_writes_no_database_or_locks_into_data_root(self):
        preset, snapshot, study, run = self.create_fixture()
        kb = KnowledgeBase("@knowledge")
        self.assertTrue(kb.db_path.is_relative_to(self.cache))
        self.assertTrue(kb.lock_path.is_relative_to(self.cache))
        self.assertTrue(study.lock_path.is_relative_to(self.cache))
        self.assertTrue(kb.status()["consistent"])
        self.assertEqual(study.get_run(run["run_id"])["input_snapshot"]["execution_preset"]["base"], snapshot)
        self.assertFalse(list(self.data.rglob("*.sqlite3*")))
        self.assertFalse(list(self.data.rglob("*.lock")))
        self.assertFalse(list(self.data.rglob("*.tmp")))
        self.assertTrue(list(self.cache.rglob("*.lock")))

    def test_whole_root_copy_preserves_identity_preset_history_and_rebuilds_index(self):
        preset, snapshot, study, run = self.create_fixture()
        original_study = study.read()
        target = self.workspace / "computer-b" / "synced-data"
        shutil.copytree(self.data, target)
        before = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
        with patch.dict(os.environ, {"EDS_DATA_HOME": str(target), "EDS_CACHE_HOME": str(self.workspace / "cache-b")}):
            kb = KnowledgeBase("@knowledge")
            self.assertFalse(kb.db_path.exists())
            # Normal drawing reuse requires neither an existing index nor a history search.
            with patch.object(KnowledgeBase, "search", side_effect=AssertionError("search")), \
                 patch.object(KnowledgeBase, "read", side_effect=AssertionError("read")):
                self.assertEqual(PresetStore("@knowledge").current(context=self.context), snapshot)
                self.assertEqual(StudyStore("@study/project-1").read(), original_study)
            result = self.invoke("kb", "@knowledge", "sync")
            self.assertTrue(result["consistent"])
            self.assertEqual(result["indexed"], 1)
            self.assertEqual(self.invoke("preset", "@knowledge", "current", "--question", "drawing"), snapshot)
            self.assertEqual(self.invoke("data", "status")["user_id"], "portable-person")
        self.assertEqual(before, {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()})

    def test_plain_legacy_workspaces_keep_old_paths(self):
        legacy = self.workspace / "legacy"
        kb = KnowledgeBase(legacy)
        self.assertEqual(kb.db_path, legacy / "index.sqlite3")
        study = StudyStore.create(legacy / "study", "legacy", mode="cad")
        self.assertEqual(study.lock_path, legacy / "study" / ".study.lock")
        self.assertFalse(kb.db_path.exists())

    def test_cli_context_shortcut_rejects_ambiguous_or_unbound_identity(self):
        self.create_fixture()
        path = self.workspace / "context.json"
        path.write_text(json.dumps(self.context), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.invoke("preset", "@knowledge", "current", "--question", "drawing", "--context", path)
        with self.assertRaises(ValueError):
            self.invoke("preset", self.data / "knowledge", "current", "--question", "drawing")
        self.assertEqual(self.invoke("preset", "@knowledge", "task", "--question", "drawing")["context"], self.context)

    def test_fresh_process_alias_resolution_uses_stable_identity(self):
        self.create_fixture()
        result = subprocess.run([sys.executable, "-m", "eds", "preset", "@knowledge", "current", "--question", "drawing"],
                                cwd=REPO, capture_output=True, text=True, encoding="utf-8", env={**os.environ, "USERNAME": "different-os-login"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["context"]["user"], "portable-person")


if __name__ == "__main__":
    unittest.main()
