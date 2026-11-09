"""Execution presets survive fresh processes without per-run knowledge work."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from eds.cli import dispatch, parser
from eds.install import REPO_ROOT
from eds.knowledge import KnowledgeBase
from eds.presets import PresetStore
from eds.study import StudyError, StudyStore


class PresetCLITests(unittest.TestCase):
    def setUp(self):
        temporary_root = REPO_ROOT / ".test-tmp"
        temporary_root.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=temporary_root)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.kb = self.root / "private-knowledge"
        self.context = {"domain": "cad", "question": "drawing", "user": "example-user"}
        self.context_path = self.write("context.json", self.context)
        self.empty_refs = self.write("refs.json", [])

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def cli(self, *args, code=0):
        result = subprocess.run([sys.executable, "-m", "eds", *map(str, args)],
                                cwd=REPO_ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return json.loads(result.stdout if code == 0 else result.stderr)

    def activate(self):
        return self.cli("preset", self.kb, "activate", "example-drawings",
                        "--context", self.context_path, "--refs", self.empty_refs)

    def save(self, values):
        overrides = self.write("save.json", values)
        return self.cli("preset", self.kb, "save-default", "--context", self.context_path,
                        "--overrides", overrides, "--source", "test transcript: explicitly reusable")

    def test_current_absent_is_read_only_and_context_switch_does_not_leak(self):
        self.assertIsNone(self.cli("preset", self.kb, "current", "--context", self.context_path))
        self.assertFalse(self.kb.exists())
        self.activate()
        self.save({"drawing.paper_size": "A3"})
        other = self.write("other.json", {**self.context, "user": "other-user"})
        self.assertIsNone(self.cli("preset", self.kb, "current", "--context", other))

    def test_temporary_override_and_repeated_save_have_no_memory_churn(self):
        self.activate()
        baseline = self.save({"drawing.paper_size": "A3"})
        before = {str(p): p.read_bytes() for p in self.kb.rglob("*.md")}
        self.assertTrue(before)
        override_path = self.write("once.json", {"drawing.paper_size": "A4"})
        task_path = self.root / "batch-task.json"
        task = self.cli("preset", self.kb, "task", "--context", self.context_path,
                        "--overrides", override_path, "--output", task_path)
        self.assertEqual(task["values"]["drawing.paper_size"], "A4")
        current = self.cli("preset", self.kb, "current", "--context", self.context_path)
        self.assertEqual(current, baseline)
        self.assertEqual(self.save({"drawing.paper_size": "A3"}), baseline)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.kb.rglob("*.md")})
        original = task_path.read_bytes()
        self.save({"drawing.paper_size": "A2"})
        self.cli("preset", self.kb, "task", "--context", self.context_path,
                 "--output", task_path, code=2)
        self.assertEqual(task_path.read_bytes(), original)

    def test_active_and_task_operations_never_access_knowledge(self):
        self.activate()
        self.save({"drawing.paper_size": "A3"})
        before = {str(p): p.read_bytes() for p in self.kb.rglob("*") if p.is_file()}
        with patch.object(KnowledgeBase, "search", side_effect=AssertionError("unexpected search")), \
             patch.object(KnowledgeBase, "read", side_effect=AssertionError("unexpected knowledge read")), \
             patch.object(KnowledgeBase, "preference_catalog", side_effect=AssertionError("unexpected catalog")), \
             patch.object(KnowledgeBase, "register_many", side_effect=AssertionError("unexpected memory write")):
            for _ in range(14):
                current = dispatch(parser().parse_args(["preset", str(self.kb), "current",
                                                       "--context", str(self.context_path)]))
                task = dispatch(parser().parse_args(["preset", str(self.kb), "task",
                                                    "--context", str(self.context_path)]))
                self.assertEqual(current["values"], task["values"])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.kb.rglob("*") if p.is_file()})

    def test_run_pins_task_and_rejects_corruption_without_knowledge(self):
        self.activate()
        self.save({"drawing.paper_size": "A3"})
        presets = PresetStore(self.kb)
        task = presets.for_task(context=self.context)
        study = StudyStore.create(self.root / "study", "drawing batch", mode="cad")
        experiment = study.add("experiment", {"question": "Verify layout", "observations": ["readability"],
                                              "decision_rule": "Accept legible dimensions"})
        data = {"experiment_ref": experiment["ref"], "input_refs": [], "backend": "fixture",
                "capability": "drawing", "input_snapshot": {"part": "shaft"}, "idempotency_key": "part-1"}
        run_path = self.write("run.json", data)
        task_path = self.write("task.json", task)
        run = self.cli("study", study.root, "run", "--data", run_path, "--preset-task", task_path)
        self.assertEqual(run["input_snapshot"]["execution_preset"], task)
        self.assertEqual(self.cli("study", study.root, "run", "--data", run_path,
                                  "--preset-task", task_path)["run_id"], run["run_id"])
        self.save({"drawing.paper_size": "A4"})
        with patch.object(KnowledgeBase, "read", side_effect=AssertionError("unexpected read")), \
             patch.object(KnowledgeBase, "search", side_effect=AssertionError("unexpected search")):
            self.assertEqual(study.get_run(run["run_id"])["input_snapshot"]["execution_preset"], task)
            run2 = study.add_run(**{**data, "idempotency_key": "part-2"}, execution_preset=task)
            self.assertEqual(run2["input_snapshot"]["execution_preset"], task)
        damaged = copy.deepcopy(task)
        damaged["values"]["drawing.paper_size"] = "A0"
        with self.assertRaises(StudyError):
            study.add_run(**{**data, "idempotency_key": "part-3"}, execution_preset=damaged)
        with self.assertRaises(StudyError):
            study.add_run(**{**data, "idempotency_key": "part-3"},
                          execution_preset=presets.current(context=self.context))
        wrong_domain = StudyStore.create(self.root / "cae-study", "CAE task", mode="cae")
        exp2 = wrong_domain.add("experiment", experiment["payload"])
        with self.assertRaisesRegex(StudyError, "domain"):
            wrong_domain.add_run(**{**data, "experiment_ref": exp2["ref"]}, execution_preset=task)
        self.assertEqual(len(study.read()["runs"]), 2)


if __name__ == "__main__":
    unittest.main()
