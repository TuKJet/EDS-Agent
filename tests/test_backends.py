import copy
import tempfile
import unittest
from pathlib import Path

from eds.backends import BindingError, check_binding, load_binding, normalize_status, prepare_call


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.binding = {"schema": "eds-backend/v1", "id": "cad-test", "codex_server": "test",
                        "domain": "cad", "fixture": True, "capabilities": {
                            "edit": {"tool": "set_length", "description": "Set a verified feature length",
                                     "inputs": {"length": {"type": "number", "unit": "mm", "backend_unit": "m", "scale": 0.001,
                                                           "minimum": 0, "target": "length_m"}},
                                     "status_map": {"DONE": "completed"}}}}

    def test_unit_conversion_is_explicit_and_does_not_execute(self):
        result = prepare_call(self.binding, "edit", {"length": {"value": 25, "unit": "mm"}})
        self.assertEqual(result["arguments"], {"length_m": 0.025})
        self.assertEqual(result["status"], "prepared_not_executed")
        self.assertEqual(result["input_snapshot"]["length"]["value"], 25)

    def test_reject_wrong_units_boolean_nan_and_unmapped_input(self):
        for value in ({"value": 2, "unit": "m"}, {"value": True, "unit": "mm"}, {"value": float("nan"), "unit": "mm"}):
            with self.subTest(value=value), self.assertRaises(BindingError):
                prepare_call(self.binding, "edit", {"length": value})
        with self.assertRaises(BindingError):
            prepare_call(self.binding, "edit", {"ignored": 1})

    def test_unknown_status_stays_unknown(self):
        self.assertEqual(normalize_status(self.binding, "edit", "DONE")["status"], "completed")
        self.assertEqual(normalize_status(self.binding, "edit", "HTTP 200")["status"], "unknown")

    def test_missing_capability_and_tool_are_specific(self):
        result = check_binding(self.binding, [])
        self.assertIn("inspect", result["missing_capabilities"])
        self.assertEqual(result["missing_tools"], ["set_length"])
        self.assertEqual(result["live_execution"], "not_verified")

    def test_async_requires_reconciliation_tool(self):
        binding = copy.deepcopy(self.binding)
        binding["capabilities"]["edit"]["async"] = True
        with self.assertRaises(BindingError):
            check_binding(binding)

    def test_read_only_capability_is_explicit_boolean(self):
        binding = copy.deepcopy(self.binding)
        binding["capabilities"]["edit"]["read_only"] = True
        check_binding(binding)
        binding["capabilities"]["edit"]["read_only"] = "yes"
        with self.assertRaises(BindingError):
            check_binding(binding)

    def test_mismatched_units_require_conversion(self):
        del self.binding["capabilities"]["edit"]["inputs"]["length"]["scale"]
        with self.assertRaises(BindingError):
            prepare_call(self.binding, "edit", {"length": {"value": 2, "unit": "mm"}})

    def test_nonfinite_json_rejected_even_in_unknown_metadata(self):
        temporary_root = Path(__file__).resolve().parent.parent / "output" / "repository-tests" / "tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            path = Path(directory) / "binding.json"
            path.write_text('{"unused": NaN}', encoding="utf-8")
            with self.assertRaises(BindingError):
                load_binding(path)

    def test_invalid_ranges_and_inventory_fail_during_validation(self):
        self.binding["capabilities"]["edit"]["inputs"]["length"]["maximum"] = -1
        with self.assertRaises(BindingError):
            check_binding(self.binding)
        with self.assertRaises(BindingError):
            check_binding(self.binding, "set_length")
