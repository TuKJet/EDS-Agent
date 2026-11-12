import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eds.execution import _git_dirty, readiness
from eds.install import REPO_ROOT, execution_skill_status, install_skills

PIN = "8a572ce6fa4d78e6ee75f03cc14547cf94830d8a"
CAE_PIN = "56705e07ce6e99f0d5a0d0c7b5e28b6b2c0bc973"


def binding(domain="cad", fixture=False):
    caps = {name: {"tool": f"{name}_tool", "description": name, "inputs": {}}
            for name in ("inspect", "edit", "measure", "export")}
    return {"schema": "eds-backend/v1", "id": "real", "domain": domain,
            "codex_server": "server", "fixture": fixture, "capabilities": caps}


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parent.parent / "output" / "repository-tests" / "tmp"
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def setup_root(self, skill_name="solidworks-automation", commit=PIN):
        root = self.root
        skill = root / "execution-skills" / "solidworks-automation-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"name: {skill_name}\n", encoding="utf-8")
        (skill / ".git").write_text("gitdir: ../.git/modules/solidworks-automation-skill\n", encoding="utf-8")
        backend = root / "backend.json"; backend.write_text(json.dumps(binding()), encoding="utf-8")
        tools = root / "tools.json"; tools.write_text(json.dumps([f"{x}_tool" for x in ("inspect", "edit", "measure", "export")]), encoding="utf-8")
        return root, backend, tools, skill, commit

    def setup_cae_root(self, commit=CAE_PIN):
        root = self.root
        implementation = root / "execution-skills" / "cae-agent-hub"
        (implementation / "MCP" / "COMSOL").mkdir(parents=True)
        (implementation / "MCP" / "COMSOL" / "README.md").write_text("docs", encoding="utf-8")
        (implementation / "MCP" / "COMSOL" / "mcp_server.py").write_text("# tools", encoding="utf-8")
        (implementation / ".git").write_text("gitdir: ../.git/modules/cae-agent-hub\n", encoding="utf-8")
        cae_binding = binding("cae")
        cae_binding["capabilities"].update({name: {"tool": f"{name}_tool", "description": name, "inputs": {}}
                                            for name in ("configure", "results", "solve")})
        backend = root / "backend.json"; backend.write_text(json.dumps(cae_binding), encoding="utf-8")
        tools = root / "tools.json"; tools.write_text(json.dumps([f"{x}_tool" for x in cae_binding["capabilities"]]), encoding="utf-8")
        return root, backend, tools, implementation, commit

    def test_cad_ready(self):
        root, backend, tools, *_ = self.setup_root()
        result = readiness("cad", backend, tools, repo_root=root)
        self.assertTrue(result["ready"]); self.assertEqual(result["status"], "ready_for_skill_load_and_binding_review")
        self.assertEqual(result["codex_server"], "server")
        self.assertEqual(result["diagnostic_detail"], "compact")
        self.assertNotIn("patch_status", result["skill"])

    @patch("eds.install.patch_status")
    def test_normal_readiness_skips_maintenance_patch_scan(self, patch):
        root, backend, tools, *_ = self.setup_root()
        result = readiness("cad", backend, tools, repo_root=root, capability="inspect")
        self.assertTrue(result["ready"])
        patch.assert_not_called()
        self.assertEqual(result["capability"], "inspect")
        self.assertEqual(result["capability_tools"], {"inspect": "inspect_tool"})
        self.assertEqual(result["skill"]["pin_status"], "not_verified")

    def test_cae_runtime_does_not_read_cad_skill(self):
        root, backend, tools, *_ = self.setup_cae_root()
        cad = root / "execution-skills" / "solidworks-automation-skill"
        cad.mkdir()
        (cad / "SKILL.md").write_text("name: solidworks-automation\n", encoding="utf-8")
        with patch.object(Path, "read_text", side_effect=AssertionError("unrelated CAD read")) as reader:
            execution_skill_status(root, domains={"cae"}, check_patches=False)
        reader.assert_not_called()

    @patch("eds.install.patch_status", return_value={"status": "not_required", "ready": True})
    def test_maintenance_checks_only_selected_source(self, patch_checker):
        self.setup_root()
        result = execution_skill_status(self.root, domains={"cad"})
        self.assertEqual(result["implementations"], [])
        patch_checker.assert_called_once()
        self.assertEqual(patch_checker.call_args.args[1]["domain"], "cad")

    def test_capability_mode_does_not_require_unrelated_capabilities(self):
        root, backend, tools, *_ = self.setup_root()
        data = json.loads(backend.read_text(encoding="utf-8"))
        data["capabilities"] = {"inspect": data["capabilities"]["inspect"]}
        backend.write_text(json.dumps(data), encoding="utf-8")
        tools.write_text(json.dumps(["inspect_tool"]), encoding="utf-8")
        result = readiness("cad", backend, tools, repo_root=root, capability="inspect")
        self.assertTrue(result["ready"])
        self.assertEqual(result["backend"]["missing_capabilities"], [])

    @patch("eds.install.patch_status", side_effect=AssertionError("execution=none must not scan patches"))
    def test_install_none_skips_optional_patch_scan(self, patch):
        result = install_skills(self.root, check=True, source_root=REPO_ROOT / "skills", execution="none")
        self.assertEqual(result["execution_patches"], [])
        self.assertEqual(result["execution_skills"]["status"], "not_checked")
        self.assertEqual(result["execution_skills"]["skills"], [])
        self.assertEqual(result["execution_skills"]["implementations"], [])
        patch.assert_not_called()

    @patch("eds.execution._git_dirty", return_value=(False, None))
    @patch("eds.execution._git_head")
    @patch("eds.install.patch_status", return_value={"status": "not_required", "ready": True,
                                                       "expected_dirty": False, "reasons": []})
    def test_full_readiness_is_explicit_diagnostic_mode(self, _, git, __):
        root, backend, tools, _, commit = self.setup_root(); git.return_value = (commit, None)
        result = readiness("cad", backend, tools, repo_root=root, full=True)
        self.assertEqual(result["diagnostic_detail"], "full")
        self.assertIn("patch_status", result["skill"])

    def test_missing_skill_and_inventory_are_blocked(self):
        root = self.root; backend = root / "b.json"; backend.write_text(json.dumps(binding()), encoding="utf-8")
        tools = root / "t.json"; tools.write_text("[]", encoding="utf-8")
        result = readiness("cad", backend, tools, repo_root=root, maintenance=True)
        self.assertFalse(result["ready"]); self.assertIn("not_initialized", " ".join(result["reasons"]))

    @patch("eds.execution._git_dirty", return_value=(False, None))
    @patch("eds.execution._git_head", return_value=("bad", None))
    def test_pin_mismatch_and_wrong_domain_and_fixture(self, _, __):
        root, backend, tools, _, _ = self.setup_root(); data = binding("cae", True); backend.write_text(json.dumps(data), encoding="utf-8")
        result = readiness("cad", backend, tools, repo_root=root, maintenance=True)
        self.assertFalse(result["ready"]); self.assertTrue(any("mismatch" in x for x in result["reasons"]))
        self.assertTrue(any("fixture" in x for x in result["reasons"]))
        self.assertTrue(any("backend domain" in x for x in result["reasons"]))

    @patch("eds.execution._git_dirty", return_value=(False, None))
    @patch("eds.execution._git_head", return_value=(PIN, None))
    def test_null_inventory_cannot_be_treated_as_a_verified_empty_check(self, _, __):
        root, backend, tools, *_ = self.setup_root()
        tools.write_text("null", encoding="utf-8")
        result = readiness("cad", backend, tools, repo_root=root, maintenance=True)
        self.assertFalse(result["ready"])
        self.assertIn("tool inventory", " ".join(result["reasons"]))

    @patch("eds.execution._git_dirty", return_value=(True, None))
    @patch("eds.execution._git_head", return_value=(PIN, None))
    def test_dirty_submodule_is_blocked(self, _, __):
        root, backend, tools, *_ = self.setup_root()
        result = readiness("cad", backend, tools, repo_root=root, maintenance=True)
        self.assertFalse(result["ready"])
        self.assertTrue(any("working tree dirty" in x for x in result["reasons"]))

    @patch("eds.execution._git_dirty", return_value=(True, None))
    @patch("eds.execution._git_head", return_value=(PIN, None))
    @patch("eds.install.patch_status", return_value={"status": "applied", "ready": True,
                                                       "expected_dirty": True, "reasons": []})
    def test_applied_patch_dirty_state_is_controlled(self, _, git, dirty):
        root, backend, tools, *_ = self.setup_root()
        result = readiness("cad", backend, tools, repo_root=root, maintenance=True)
        self.assertTrue(result["ready"])
        self.assertEqual(result["skill"]["clean_status"], "controlled_patch_changes")

    @patch("eds.execution._git_dirty", return_value=(True, None))
    @patch("eds.execution._git_head", return_value=(PIN, None))
    @patch("eds.install.patch_status", return_value={"status": "conflict", "ready": False,
                                                       "expected_dirty": False, "reasons": ["local edit"]})
    def test_extra_dirty_patch_state_is_blocked(self, _, git, dirty):
        root, backend, tools, *_ = self.setup_root()
        result = readiness("cad", backend, tools, repo_root=root, maintenance=True)
        self.assertFalse(result["ready"])
        self.assertTrue(any("local edit" in reason for reason in result["reasons"]))

    @patch("eds.execution._git_dirty", return_value=(False, None))
    @patch("eds.execution._git_head", return_value=(PIN, None))
    @patch("eds.install.patch_status", return_value={"status": "ready_to_apply", "ready": False,
                                                       "expected_dirty": False, "reasons": []})
    def test_pending_patch_state_is_blocked_even_without_reason_text(self, _, git, dirty):
        root, backend, tools, *_ = self.setup_root()
        result = readiness("cad", backend, tools, repo_root=root, maintenance=True)
        self.assertFalse(result["ready"])
        self.assertTrue(any("ready_to_apply" in reason for reason in result["reasons"]))

    @patch("eds.execution._git_dirty", return_value=(False, None))
    @patch("eds.execution._git_head")
    def test_cae_ready_with_docs_without_general_skill(self, git, _):
        root, backend, tools, *_ = self.setup_cae_root(); git.return_value = (CAE_PIN, None)
        result = readiness("cae", backend, tools, repo_root=root, maintenance=True)
        self.assertTrue(result["ready"]); self.assertEqual(result["status"], "ready_for_mcp_docs_and_binding_review")
        self.assertIsNone(result["skill_path"])
        self.assertEqual(Path(result["documentation_path"]).parts[-3:], ("MCP", "COMSOL", "README.md"))
        self.assertIsNone(result["capabilities_path"])
        self.assertEqual(result["live_mcp"], "not_verified")
        self.assertEqual(result["host_discovery"], "not_verified")
        self.assertEqual(result["engineering_validity"], "not_verified")

    @patch("eds.execution._git_dirty", return_value=(False, None))
    @patch("eds.execution._git_head", return_value=(CAE_PIN, None))
    def test_cae_missing_docs_is_blocked(self, _, __):
        root, backend, tools, implementation, _ = self.setup_cae_root()
        (implementation / "MCP" / "COMSOL" / "README.md").unlink()
        result = readiness("cae", backend, tools, repo_root=root, maintenance=True)
        self.assertFalse(result["ready"]); self.assertTrue(any("documentation" in x for x in result["reasons"]))

    def test_cae_missing_entrypoint_or_submodule_is_blocked(self):
        root, backend, tools, implementation, _ = self.setup_cae_root()
        (implementation / "MCP" / "COMSOL" / "mcp_server.py").unlink()
        result = readiness("cae", backend, tools, repo_root=root, maintenance=True)
        self.assertFalse(result["ready"])
        with tempfile.TemporaryDirectory(dir=self.root) as empty:
            result = readiness("cae", backend, tools, repo_root=empty)
            self.assertFalse(result["ready"])
            self.assertTrue(any("not_initialized" in reason for reason in result["reasons"]))

    @patch("eds.execution._git_dirty", return_value=(False, None))
    @patch("eds.execution._git_head", return_value=("wrong", None))
    def test_cae_wrong_pin_is_blocked(self, _, __):
        root, backend, tools, *_ = self.setup_cae_root()
        result = readiness("cae", backend, tools, repo_root=root, maintenance=True)
        self.assertFalse(result["ready"])
        self.assertTrue(any("mismatch" in reason for reason in result["reasons"]))

    @patch("eds.execution._git_dirty", return_value=(True, None))
    @patch("eds.execution._git_head", return_value=(CAE_PIN, None))
    def test_cae_dirty_fixture_wrong_domain_and_inventory_fail(self, _, __):
        root, backend, tools, *_ = self.setup_cae_root()
        data = binding("cad", True)
        backend.write_text(json.dumps(data), encoding="utf-8")
        result = readiness("cae", backend, tools, repo_root=root, maintenance=True)
        self.assertFalse(result["ready"])
        self.assertTrue(any("dirty" in reason for reason in result["reasons"]))
        self.assertTrue(any("fixture" in reason for reason in result["reasons"]))
        self.assertTrue(any("backend domain" in reason for reason in result["reasons"]))
        tools.write_text("null", encoding="utf-8")
        result = readiness("cae", backend, tools, repo_root=root)
        self.assertFalse(result["ready"])
        self.assertTrue(any("tool inventory" in reason for reason in result["reasons"]))

    @patch("eds.execution._git_dirty", return_value=(False, None))
    @patch("eds.execution._git_head", return_value=(CAE_PIN, None))
    def test_cae_missing_tools_is_blocked(self, _, __):
        root, backend, tools, *_ = self.setup_cae_root()
        tools.write_text(json.dumps(["inspect_tool"]), encoding="utf-8")
        result = readiness("cae", backend, tools, repo_root=root)
        self.assertFalse(result["ready"])
        self.assertTrue(any("missing concrete MCP tools" in reason for reason in result["reasons"]))

    def test_git_dirty_detects_untracked_nonignored_source(self):
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
            (repo / "tracked.py").write_text("x = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.py"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                            "commit", "-qm", "init"], cwd=repo, check=True, capture_output=True)
            (repo / "shadow.py").write_text("x = 2\n", encoding="utf-8")
            dirty, error = _git_dirty(repo)
            self.assertTrue(dirty)
            self.assertIsNone(error)
            (repo / "shadow.py").unlink()
            (repo / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
            subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                            "commit", "-qm", "ignore-cache"], cwd=repo, check=True, capture_output=True)
            (repo / "ignored.pyc").write_bytes(b"cache")
            dirty, error = _git_dirty(repo)
            self.assertFalse(dirty)
            self.assertIsNone(error)
