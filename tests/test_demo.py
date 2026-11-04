import json
import tempfile
import unittest

from eds.install import REPO_ROOT
from eds.study import StudyStore
from scripts.demo_offline import run_demo


class OfflineDemoTests(unittest.TestCase):
    def test_three_paths_preserve_evidence_and_keep_live_acceptance_pending(self):
        temporary_root = REPO_ROOT / ".test-tmp"
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as root:
            report = run_demo(root)
            self.assertEqual(report["real_mcp_calls"], 0)
            self.assertEqual(report["engineering_acceptance"], "not_executed")
            from pathlib import Path
            for mode in ("cad", "cae", "coupled"):
                study = StudyStore(Path(root) / mode)
                self.assertEqual(study.read()["runs"][0]["input_snapshot"]["thickness_mm"], 10)
                self.assertEqual(study.read()["runs"][0]["status"], "completed")
                impact = json.loads((Path(root) / mode / "impact.json").read_text(encoding="utf-8"))
                self.assertIn(report["paths"][mode]["assessment"], impact["affected"])
                delivery = study.render_report()
                self.assertTrue(delivery["artifacts"])
                self.assertEqual(delivery["conditions"], ["Synthetic records only"])
                self.assertIn("Actual backend capabilities and model readback", delivery["open_questions"])
            self.assertEqual(StudyStore(Path(root) / "cae").get(kind="design"), [])
            self.assertGreater(report["knowledge"]["english_matches"], 0)
            self.assertGreater(report["knowledge"]["chinese_matches"], 0)
