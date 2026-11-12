"""Exercise the public runtime/maintenance split without backend execution."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from eds.cli import dispatch, parser
from eds.install import REPO_ROOT


class ExecutionModesCLITests(unittest.TestCase):
    def setUp(self):
        (REPO_ROOT / "output" / "repository-tests" / "tmp").mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=REPO_ROOT / "output" / "repository-tests" / "tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binding = self.root / "binding.json"
        self.inventory = self.root / "tools.json"
        self.binding.write_text(json.dumps({
            "schema": "eds-backend/v1", "id": "selected-cad", "domain": "cad",
            "codex_server": "local-test-only", "capabilities": {
                "inspect": {"tool": "read_model", "description": "Read model state only",
                            "inputs": {}, "read_only": True}}}), encoding="utf-8")
        self.inventory.write_text('["read_model"]', encoding="utf-8")
        self.args = ["execution", "cad", "--backend", str(self.binding), "--tools", str(self.inventory)]

    def test_one_target_tool_does_not_require_edit_measure_export_or_git(self):
        with patch("eds.execution._git_head", side_effect=AssertionError("unexpected maintenance")), \
                patch("eds.install.patch_status", side_effect=AssertionError("unexpected patch check")):
            result = dispatch(parser().parse_args([*self.args, "--capability", "inspect"]))
        self.assertTrue(result["ready"], result)
        self.assertEqual(result["capability_tools"], {"inspect": "read_model"})
        self.assertEqual(result["live_mcp"], "not_verified")

    def test_full_output_does_not_implicitly_request_maintenance(self):
        with patch("eds.execution._git_head", side_effect=AssertionError("unexpected maintenance")), \
                patch("eds.install.patch_status", side_effect=AssertionError("unexpected patch check")):
            result = dispatch(parser().parse_args([*self.args, "--full", "--capability", "inspect"]))
        self.assertTrue(result["ready"], result)

    def test_default_checks_declared_capabilities_without_requiring_whole_domain(self):
        result = dispatch(parser().parse_args(self.args))
        self.assertTrue(result["ready"], result)
        self.assertEqual(result["backend"]["missing_capabilities"], [])

    def test_targeted_inventory_rejects_non_name_entries(self):
        self.inventory.write_text('[{"name":"read_model"}]', encoding="utf-8")
        result = dispatch(parser().parse_args([*self.args, "--capability", "inspect"]))
        self.assertFalse(result["ready"])
        self.assertIn("tool inventory", str(result["reasons"]))

    def test_explicit_maintenance_reaches_maintenance_checker(self):
        with patch("eds.cli.readiness", return_value={"ready": False}) as checker:
            dispatch(parser().parse_args([*self.args, "--maintenance", "--capability", "inspect"]))
        self.assertTrue(checker.call_args.kwargs["maintenance"])
        self.assertEqual(checker.call_args.kwargs["capability"], "inspect")

    def test_missing_selected_tool_is_not_marked_ready(self):
        self.inventory.write_text("[]", encoding="utf-8")
        result = dispatch(parser().parse_args([*self.args, "--capability", "inspect"]))
        self.assertFalse(result["ready"])
        self.assertIn("read_model", str(result["reasons"]))


if __name__ == "__main__":
    unittest.main()
