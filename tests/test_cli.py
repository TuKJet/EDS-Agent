import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eds.install import REPO_ROOT, execution_skill_status, install_skills


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temporary_root = REPO_ROOT / ".test-tmp"
        self.temporary_root.mkdir(exist_ok=True)

    def run_cli(self, *args, stdin=None):
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        return subprocess.run([sys.executable, "-m", "eds", *args], input=stdin, text=True,
                              encoding="utf-8", capture_output=True, cwd=REPO_ROOT, env=env)

    def test_cae_init_and_resume_in_fresh_process_with_unicode_path(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory:
            root = str(Path(directory) / "工程记录")
            result = self.run_cli("study", root, "init", "--goal", "验证梁", "--mode", "cae")
            self.assertEqual(result.returncode, 0, result.stderr)
            first = json.loads(result.stdout)
            resumed = self.run_cli("study", root, "resume")
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertEqual(json.loads(resumed.stdout)["study_id"], first["study_id"])

    def test_resume_full_and_show_run_in_fresh_process_and_conflicts_fail(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory:
            root = str(Path(directory) / "study")
            self.assertEqual(self.run_cli("study", root, "init", "--goal", "g", "--mode", "cad").returncode, 0)
            payload = Path(directory) / "experiment.json"
            payload.write_text(json.dumps({"question": "q", "observations": ["o"], "decision_rule": "r"}), encoding="utf-8")
            added = self.run_cli("study", root, "add", "experiment", "--ref", "exp", "--data", str(payload))
            self.assertEqual(added.returncode, 0, added.stderr)
            run_payload = Path(directory) / "run.json"
            run_payload.write_text(json.dumps({"experiment_ref": "exp", "input_refs": [], "backend": "b",
                                               "capability": "c", "input_snapshot": {"raw": "VENDOR_LOG"},
                                               "idempotency_key": "k"}), encoding="utf-8")
            created = self.run_cli("study", root, "run", "--data", str(run_payload))
            self.assertEqual(created.returncode, 0, created.stderr)
            run_id = json.loads(created.stdout)["run_id"]
            compact = self.run_cli("study", root, "resume")
            detailed = self.run_cli("study", root, "resume", "--full")
            selected = self.run_cli("study", root, "show", "--run", run_id)
            for result in (compact, detailed, selected):
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(compact.stdout)["detail"], "summary")
            self.assertNotIn("VENDOR_LOG", compact.stdout)
            self.assertIn("input_snapshot", json.loads(detailed.stdout)["pending_runs"][0])
            self.assertEqual(json.loads(selected.stdout)["run_id"], run_id)
            self.assertEqual(json.loads(selected.stdout)["input_snapshot"], {"raw": "VENDOR_LOG"})
            self.assertNotEqual(self.run_cli("study", root, "show", "--run", run_id, "--kind", "experiment").returncode, 0)
            self.assertNotEqual(self.run_cli("study", root, "show", "--run", run_id, "--ref", "exp").returncode, 0)
            empty = self.run_cli("study", root, "show", "--run", "")
            self.assertEqual(empty.returncode, 2, empty.stderr)
            self.assertEqual(empty.stdout, "")
            missing = self.run_cli("study", root, "show", "--run", "run_missing")
            self.assertEqual(missing.returncode, 0, missing.stderr)
            self.assertIsNone(json.loads(missing.stdout))
            self.assertEqual(self.run_cli("study", root, "show", "--ref", "exp", "--kind", "experiment").returncode, 0)

    def test_invalid_record_returns_json_error_and_nonzero_status(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory:
            self.run_cli("study", directory, "init", "--goal", "test", "--mode", "cad")
            result = self.run_cli("study", directory, "add", "realization", "--data", "-", stdin="{}")
            self.assertEqual(result.returncode, 2)
            self.assertIn("error", json.loads(result.stderr))

    def test_stdin_payload_and_no_model_dependency(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("backend", result.stdout)
        self.assertIn("asset", result.stdout)

    def test_execution_blocked_returns_nonzero(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory:
            tools = Path(directory) / "tools.json"
            tools.write_text("[]", encoding="utf-8")
            result = self.run_cli("execution", "cae", "--backend", "examples/backend.fixture.json", "--tools", str(tools))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "blocked")

    def test_install_and_detect_modified_copy_without_overwriting(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory:
            source = REPO_ROOT / "skills"
            result = install_skills(directory, source_root=source)
            self.assertTrue(result["in_sync"])
            self.assertTrue(install_skills(directory, check=True, source_root=source)["in_sync"])
            path = Path(directory) / ".agents/skills/eds-study/SKILL.md"
            path.write_text("local changes", encoding="utf-8")
            with self.assertRaises(ValueError):
                install_skills(directory, source_root=source)
            self.assertEqual(path.read_text(), "local changes")
            install_skills(directory, update=True, source_root=source)
            self.assertTrue(install_skills(directory, check=True, source_root=source)["in_sync"])

    def test_patch_check_does_not_apply_and_reports_pending(self):
        pending = {"status": "ready_to_apply", "ready": False,
                   "expected_dirty": False, "reasons": []}
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory, \
                patch("eds.install.patch_status", return_value=pending) as status:
            result = install_skills(directory, check=True, source_root=REPO_ROOT / "skills", execution="cad")
            self.assertFalse(result["in_sync"])
            self.assertTrue(all(call.kwargs.get("apply", False) is False for call in status.call_args_list))

    def test_default_install_applies_ready_execution_patch(self):
        def fake_status(root, known, *, apply=False):
            if known["domain"] == "cad":
                return {"status": "applied" if apply else "ready_to_apply",
                        "ready": bool(apply), "expected_dirty": bool(apply), "reasons": []}
            return {"status": "not_required", "ready": True, "expected_dirty": False, "reasons": []}
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory, \
                patch("eds.install.patch_status", side_effect=fake_status) as status:
            result = install_skills(directory, source_root=REPO_ROOT / "skills")
            self.assertTrue(result["in_sync"])
            self.assertTrue(any(call.kwargs.get("apply") is True for call in status.call_args_list))

    def test_explicit_missing_cae_submodule_is_blocked(self):
        report = {"status": "not_required", "ready": True,
                  "expected_dirty": False, "reasons": []}
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory, \
                patch("eds.install.patch_status", return_value=report):
            with self.assertRaises(ValueError):
                install_skills(directory, source_root=REPO_ROOT / "skills", execution="cae")

    def test_skill_copy_conflict_preflights_before_patch(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory, \
                patch("eds.install.patch_status") as status:
            target = Path(directory) / ".agents/skills/eds-study/SKILL.md"
            target.parent.mkdir(parents=True)
            target.write_text("unrelated local edit", encoding="utf-8")
            with self.assertRaises(ValueError):
                install_skills(directory, source_root=REPO_ROOT / "skills")
            status.assert_not_called()

    def test_optional_execution_skill_status_is_missing_without_submodule(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory:
            status = execution_skill_status(directory)
            self.assertEqual(status["status"], "not_initialized")
            self.assertEqual(status["skills"][0]["id"], "solidworks-automation-skill")
            self.assertEqual(status["skills"][0]["domain"], "cad")
            self.assertEqual(status["implementations"][0]["id"], "cae-agent-hub")
            self.assertEqual(status["implementations"][0]["task_skill_path"], None)
            self.assertEqual(status["status"], "not_initialized")
            self.assertIn("git submodule update", status["install_hint"])

    def test_optional_execution_skill_status_reads_only_skill_metadata(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory:
            root = Path(directory) / "execution-skills" / "solidworks-automation-skill"
            root.mkdir(parents=True)
            (root / "SKILL.md").write_text("name: solidworks-automation\ndescription: test\n", encoding="utf-8")
            (root / "large-unrelated-file.bin").write_bytes(b"ignored")
            status = execution_skill_status(directory)
            self.assertEqual(status["status"], "not_initialized")
            self.assertEqual(status["skills"][0]["status"], "available")
            self.assertEqual(status["skills"][0]["name"], "solidworks-automation")
            self.assertEqual(status["skills"][0]["recommendation"], "optional")

    def test_cae_files_without_submodule_marker_are_not_available(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory:
            root = Path(directory) / "execution-skills" / "cae-agent-hub" / "MCP" / "COMSOL"
            root.mkdir(parents=True)
            (root / "README.md").write_text("docs", encoding="utf-8")
            (root / "mcp_server.py").write_text("# tools", encoding="utf-8")
            status = execution_skill_status(directory)
            implementation = status["implementations"][0]
            self.assertEqual(implementation["status"], "submodule_not_initialized")
            self.assertIsNotNone(status["install_hint"])

    def test_optional_execution_skill_metadata_mismatch_is_explicit(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory:
            root = Path(directory) / "execution-skills" / "solidworks-automation-skill"
            root.mkdir(parents=True)
            (root / "SKILL.md").write_text("name: unrelated\n", encoding="utf-8")
            status = execution_skill_status(directory)
            self.assertEqual(status["skills"][0]["status"], "metadata_mismatch")
