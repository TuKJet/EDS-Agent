import json
import tempfile
import unittest
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from eds.experience import (ExperienceError, build_iteration, compact_iteration,
                            existing_publication, publish_iteration, validate_iteration)
from eds.knowledge import KnowledgeBase, KnowledgeError
from eds.personal_data import init_data


def state(status="completed"):
    return {"schema": "eds-study/v1", "study_id": "study_demo", "goal": "CAD route",
            "mode": "cad", "constraints": ["keep interface"], "facts": [], "assumptions": [], "gaps": [], "assets": [],
            "entities": [
                {"ref": "experiment@1", "logical_ref": "experiment", "version": 1, "kind": "experiment",
                 "payload": {"question": "which endpoint", "observations": ["rebuild"], "decision_rule": "valid"}},
                {"ref": "evidence@1", "logical_ref": "evidence", "version": 1, "kind": "evidence",
                 "payload": {"source": "receipt.json", "observation": "native readback", "run_id": "run-1"}},
                {"ref": "assessment@1", "logical_ref": "assessment", "version": 1, "kind": "assessment",
                 "payload": {"evidence_refs": ["evidence@1"], "experiment_ref": "experiment@1",
                             "interpretation": "endpoint works under this condition", "next_action": "reuse after readback",
                             "experience": {"status": "unverified", "recommendation": "read back native state", "applicability": ["same capability"]}}},
            ], "runs": [{"run_id": "run-1", "experiment_ref": "experiment@1", "status": status,
                          "input_snapshot": {"tool": "inspect"}, "history": [{"status": status}]}], "events": [],
            "preferences": {"extraction": "later"}, "context": {}, "metrics": {"elapsed_seconds": None, "human_inputs": None, "model_cost": None}}


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / "output" / "repository-tests" / "tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.root = Path(self.temp.name) / "data"
        self.environment = patch.dict(os.environ, {"EDS_DATA_HOME": str(self.root), "EDS_CACHE_HOME": str(Path(self.temp.name) / "cache")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        init_data(self.root, user_id="test")
        (self.root / "knowledge").mkdir(exist_ok=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_build_is_bounded_and_retains_failed_run(self):
        original = state("failed")
        record = build_iteration(original, "assessment@1")
        self.assertEqual(record["actions"]["run_ids"], ["run-1"])
        self.assertEqual(record["actions"]["run_statuses"], ["failed"])
        self.assertEqual(record["observations"]["entities"][-1]["ref"], "experiment@1")
        self.assertEqual(record["guidance"]["status"], "unverified")
        self.assertNotIn("assessment", record["analysis"])
        self.assertEqual(next(item for item in record["observations"]["entities"] if item["ref"] == "assessment@1"), original["entities"][2])

    def test_verified_rejects_unknown_run(self):
        record = build_iteration(state("unknown"), "assessment@1")
        record["guidance"] = {"status": "verified", "validation_refs": ["evidence@1"]}
        with self.assertRaises(ExperienceError):
            validate_iteration(record)

    def test_legacy_record_without_method_evaluations_remains_valid(self):
        record = build_iteration(state(), "assessment@1")
        record["schema"] = "eds-experience/v1"
        record.pop("method_evaluations")
        self.assertEqual(validate_iteration(record)["id"], record["id"])

    def test_method_evaluation_keeps_literature_separate_from_runtime_effect(self):
        study = state()
        study["entities"][2]["payload"]["experience"]["method_evaluations"] = [{
            "knowledge_ref": "method-paper@2", "product_features": ["thin fin"],
            "conditions": {"load": "low"}, "parameter_changes": {"h": "15"},
            "comparison": {"baseline": "flat", "candidate": "fin"},
            "effect": "inconclusive", "evidence_origin": "literature",
            "evidence_refs": [], "limitations": ["not reproduced locally"],
        }]
        record = build_iteration(study, "assessment@1")
        self.assertEqual(record["method_evaluations"][0]["knowledge_ref"], "method-paper@2")
        self.assertIn("method-paper@2", record["reuse"]["knowledge_refs"])

    def test_run_links_close_entities_and_cutoff_excludes_future_feedback(self):
        study = state()
        study["entities"].append({"ref": "realization@1", "logical_ref": "realization", "version": 1,
                                   "kind": "realization", "payload": {"proposal_ref": "experiment@1",
                                                                        "observation": "native", "differences": ["mesh"]}})
        study["entities"][1]["payload"]["run_id"] = "run-1"
        study["entities"][2]["created_at"] = "2026-11-09T10:00:00+00:00"
        study["runs"][0]["created_at"] = "2026-11-09T09:00:00+00:00"
        study["runs"][0]["input_refs"] = ["realization@1"]
        study["runs"][0]["history"] = [{"status": "completed", "at": "2026-11-09T09:30:00+00:00"},
                                         {"status": "completed", "at": "2026-11-09T11:00:00+00:00"}]
        study["runs"].append({"run_id": "future", "experiment_ref": "experiment@1",
                               "created_at": "2026-11-09T12:00:00+00:00", "status": "completed", "history": []})
        record = build_iteration(study, "assessment@1")
        self.assertIn("realization@1", record["actions"]["entity_refs"])
        self.assertEqual(record["actions"]["run_ids"], ["run-1"])
        self.assertEqual(record["actions"]["runs"][0]["source"]["observation_index"], 0)
        self.assertNotIn("history", record["actions"]["runs"][0])

    def test_context_reuse_and_entity_observation_are_indexed(self):
        study = state()
        study["context"] = {"conditions": {"load": "thin-wall"}, "environment": "VM-SW",
                             "product_features": ["thin-wall", "fine-mesh"]}
        study["entities"][1]["payload"]["observation"] = "薄壁网格改善 native readback"
        study["entities"][2]["payload"]["knowledge_use"] = {"decision": "adopted", "result": "reduced retry"}
        record = build_iteration(study, "assessment@1")
        self.assertEqual(record["context"]["environment"], "VM-SW")
        self.assertEqual(record["reuse"]["decision"]["decision"], "adopted")
        result = publish_iteration("@knowledge", record)
        matches = KnowledgeBase("@knowledge").search("薄壁网格", type="feedback")
        self.assertTrue(any(item["id"] == result["id"] for item in matches))

    def test_publish_is_idempotent_and_rebuildable(self):
        record = build_iteration(state(), "assessment@1")
        result = publish_iteration("@knowledge", record)
        repeat = publish_iteration("@knowledge", record)
        self.assertEqual(result["snapshot_path"], repeat["snapshot_path"])
        self.assertTrue(result["indexed"])
        self.assertEqual(KnowledgeBase("@knowledge").search("native readback", type="feedback")[0]["id"], result["id"])
        Path(result["snapshot_path"]).unlink()
        # The Markdown publication remains independently searchable.
        self.assertTrue(KnowledgeBase("@knowledge").status()["consistent"])

    def test_same_version_different_content_rejected(self):
        record = build_iteration(state(), "assessment@1")
        publish_iteration("@knowledge", record)
        changed = build_iteration(state(), "assessment@1")
        changed["guidance"]["recommendation"] = "different"
        with self.assertRaises(ExperienceError):
            publish_iteration("@knowledge", changed)

    def test_cutoff_restores_summary_output_context_and_timezone(self):
        study = state()
        assessment = study["entities"][2]
        assessment["created_at"] = "2026-11-09T10:00:00+00:00"
        study["goal"] = "future goal"
        study["context"] = {"environment": {"solver": "future"}}
        study["events"] = [{"type": "context", "at": "2026-11-09T11:00:00+00:00",
                            "previous": {"goal": "original goal", "environment": {"solver": "original"}}}]
        run = study["runs"][0]
        run.update(created_at="2026-11-09T08:00:00+00:00", status="completed", output="FUTURE_OUTPUT",
                   history=[{"at": "2026-11-09T17:00:00+08:00", "status": "running", "output": "before"},
                            {"at": "2026-11-09T11:00:00+00:00", "status": "completed", "output": "FUTURE_OUTPUT"}])
        record = build_iteration(study, "assessment@1")
        self.assertEqual(record["actions"]["run_statuses"], ["running"])
        self.assertEqual(record["actions"]["runs"][0]["source"]["observation_index"], 0)
        self.assertNotIn("output", record["actions"]["runs"][0])
        self.assertNotIn("FUTURE_OUTPUT", json.dumps(record))
        self.assertEqual(record["context"]["environment"]["solver"], "original")
        self.assertEqual(record["context"]["goal"], "original goal")

    def test_large_technical_payloads_do_not_enter_scientific_ledger(self):
        study = state()
        before = build_iteration(study, "assessment@1")
        run = study["runs"][0]
        run["output"] = "LONG_RECEIPT" * 20000
        run["input_snapshot"] = {"arguments": {"code": "TRANSPORT_SCRIPT" * 20000}}
        run["history"][0]["output"] = run["output"]
        study["entities"][1]["payload"]["observation"] = {"tip_mm": 21.4817, "units": "mm", "gate": "inconclusive"}
        record = build_iteration(study, "assessment@1")
        encoded = json.dumps(record)
        self.assertNotIn("LONG_RECEIPT", encoded)
        self.assertNotIn("TRANSPORT_SCRIPT", encoded)
        self.assertNotIn("input_snapshot", encoded)
        self.assertEqual(record["actions"]["runs"], before["actions"]["runs"])
        self.assertIn('21.4817', encoded)
        result = publish_iteration("@knowledge", record)
        self.assertLess(Path(result["snapshot_path"]).stat().st_size, 10000)
        self.assertLess(Path(result["path"]).stat().st_size, 30000)
        self.assertFalse((self.root / "knowledge/.experience-publication").exists())

    def test_backdated_observation_recorded_after_assessment_cannot_change_it(self):
        study = state()
        study["entities"][2]["created_at"] = "2026-11-09T10:00:00+00:00"
        run = study["runs"][0]
        run.update(created_at="2026-11-09T08:00:00+00:00", status="running",
                   history=[{"status": "running", "at": "2026-11-09T09:00:00+00:00",
                             "recorded_at": "2026-11-09T09:05:00+00:00"}])
        before = build_iteration(study, "assessment@1")
        run["history"].append({"status": "completed", "at": "2026-11-09T09:30:00+00:00",
                               "recorded_at": "2026-11-09T11:00:00+00:00", "output": "late result"})
        run["status"] = "completed"
        self.assertEqual(build_iteration(study, "assessment@1"), before)

    def test_v1_representation_conversion_preserves_science_and_identity(self):
        record = build_iteration(state(), "assessment@1")
        record["schema"] = "eds-experience/v1"
        record["analysis"]["assessment"] = next(item["payload"] for item in record["observations"]["entities"] if item["ref"] == "assessment@1")
        record["actions"]["runs"][0].update(input_snapshot={"code": "large" * 10000},
                                             output={"log": "large" * 10000}, history=[{"output": "raw"}])
        old = json.loads(json.dumps(record))
        converted = compact_iteration(record)
        self.assertEqual(record, old)
        self.assertEqual(converted["schema"], "eds-experience/v2")
        for key in ("id", "version", "assessment_ref", "context", "observations", "guidance", "method_evaluations"):
            self.assertEqual(converted[key], record[key])
        self.assertEqual(converted["analysis"], {key: value for key, value in record["analysis"].items() if key != "assessment"})
        self.assertNotIn("input_snapshot", json.dumps(converted))
        self.assertNotIn("history", converted["actions"]["runs"][0])
        self.assertEqual(compact_iteration(converted), converted)
        record["analysis"]["assessment"] = {"interpretation": "a different scientific conclusion"}
        with self.assertRaisesRegex(ExperienceError, "not a duplicate"):
            compact_iteration(record)

    def test_v2_rejects_full_run_payload_even_if_small(self):
        record = build_iteration(state(), "assessment@1")
        record["actions"]["runs"][0]["output"] = "unnecessary duplicate"
        with self.assertRaisesRegex(ExperienceError, "Run ledger"):
            validate_iteration(record)

    def test_existing_publication_reuses_fixed_record_and_checks_source_hash(self):
        record = build_iteration(state(), "assessment@1")
        self.assertIsNone(existing_publication("@knowledge", record["study_id"], record["assessment_ref"]))
        result = publish_iteration("@knowledge", record)
        self.assertEqual(existing_publication("@knowledge", record["study_id"], record["assessment_ref"]), result)
        source = Path(result["snapshot_path"])
        source.write_text(source.read_text().replace('endpoint works', 'endpoint fails'), encoding="utf-8")
        with self.assertRaisesRegex(ExperienceError, "hash mismatch"):
            existing_publication("@knowledge", record["study_id"], record["assessment_ref"])

    def test_existing_legacy_publication_is_acknowledged_without_rewriting(self):
        record = build_iteration(state(), "assessment@1")
        record["schema"] = "eds-experience/v1"
        record["actions"]["runs"][0]["output"] = {"legacy_response": "preserved until explicit migration"}
        result = publish_iteration("@knowledge", record)
        paths = [Path(result["path"]), Path(result["snapshot_path"])]
        paths[0].write_text(paths[0].read_text() + "\nLegacy rendering remains fixed.\n", encoding="utf-8")
        before = [path.read_bytes() for path in paths]
        self.assertEqual(existing_publication("@knowledge", record["study_id"], record["assessment_ref"]), result)
        self.assertEqual([path.read_bytes() for path in paths], before)

    def test_json_only_publication_retry_restores_markdown_from_fixed_json(self):
        record = build_iteration(state(), "assessment@1")
        result = publish_iteration("@knowledge", record)
        source = Path(result["snapshot_path"])
        fixed_json = source.read_bytes()
        markdown = Path(result["path"])
        original_markdown = markdown.read_bytes()
        markdown.unlink()
        self.assertEqual(existing_publication("@knowledge", record["study_id"], record["assessment_ref"]), result)
        self.assertEqual(source.read_bytes(), fixed_json)
        self.assertEqual(markdown.read_bytes(), original_markdown)

    def test_existing_markdown_conflict_is_not_overwritten_on_retry(self):
        record = build_iteration(state(), "assessment@1")
        result = publish_iteration("@knowledge", record)
        markdown = Path(result["path"])
        conflicting = markdown.read_text().replace('"data_schema":"eds-experience/v2"', '"data_schema":"eds-experience/v1"')
        markdown.write_text(conflicting, encoding="utf-8")
        with self.assertRaisesRegex(ExperienceError, "identity/source mismatch"):
            existing_publication("@knowledge", record["study_id"], record["assessment_ref"])
        self.assertEqual(markdown.read_text(), conflicting)

    def test_public_skill_destination_rejected_before_writing(self):
        repo = Path(__file__).resolve().parents[1]
        target = repo / "skills" / "must-not-be-created-experience-fixture"
        self.assertFalse(target.exists())
        with self.assertRaises(ExperienceError):
            publish_iteration(target, build_iteration(state(), "assessment@1"))
        self.assertFalse(target.exists())

    def test_knowledge_reference_does_not_claim_method_adoption(self):
        study = state()
        study["entities"][2]["payload"]["knowledge_refs"] = ["paper@draft-A"]
        record = build_iteration(study, "assessment@1")
        self.assertEqual(record["relations"], [{"id": "paper", "version": "draft-A", "type": "related_to"}])

    def test_repeat_publication_is_stable_in_a_fresh_process(self):
        record = build_iteration(state(), "assessment@1")
        first = publish_iteration("@knowledge", record)
        source = Path(self.temp.name) / "record.json"
        source.write_text(json.dumps(record), encoding="utf-8")
        code = "import json,sys; from pathlib import Path; from eds.experience import publish_iteration; print(json.dumps(publish_iteration('@knowledge',json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))))"
        result = subprocess.run([sys.executable, "-c", code, str(source)], capture_output=True,
                                text=True, encoding="utf-8", env={**os.environ, "PYTHONHASHSEED": "7"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["hash"], first["hash"])

    def test_index_failure_is_visible_and_retryable(self):
        record = build_iteration(state(), "assessment@1")
        with patch.object(KnowledgeBase, "register_many", side_effect=KnowledgeError("offline")):
            with self.assertRaises(ExperienceError) as error:
                publish_iteration("@knowledge", record)
        self.assertIn("indexing is pending", str(error.exception))
        self.assertTrue(list((self.root / "knowledge").rglob("*.json")))
        self.assertTrue(publish_iteration("@knowledge", record)["indexed"])


if __name__ == "__main__":
    unittest.main()
