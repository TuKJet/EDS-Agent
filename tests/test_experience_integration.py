"""Central iteration capture works across projects and publication failures."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from eds.cli import dispatch, parser
from eds.knowledge import KnowledgeBase, knowledge_route
from eds.personal_data import init_data
from eds.study import StudyStore


class CentralExperienceTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / ".test-tmp"
        base.mkdir(exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name)
        self.data = self.workspace / "data"
        env = patch.dict(os.environ, {"EDS_DATA_HOME": str(self.data),
                                     "EDS_CACHE_HOME": str(self.workspace / "cache")})
        env.start()
        self.addCleanup(env.stop)
        init_data(self.data, user_id="fixture-owner")

    def create_assessment(self, study, *, status="completed", ref=None):
        experiment = study.add("experiment", {"question": "Thin wall mesh sensitivity",
                                             "observations": ["stress and convergence"],
                                             "decision_rule": "compare independent references"})
        run = study.add_run(experiment_ref=experiment["ref"], input_refs=[], backend="fixture",
                            capability="solve", input_snapshot={"parameters": {"mesh_size": 1.0}},
                            idempotency_key=experiment["ref"])
        study.transition_run(run["run_id"], "submitting")
        study.transition_run(run["run_id"], status, output={"observation": "mesh sensitivity unresolved"})
        evidence = study.add("evidence", {"source": "fixture:result", "observation": "薄壁 网格 sensitive",
                                          "run_id": run["run_id"]})
        assessment = study.add("assessment", {"evidence_refs": [evidence["ref"]],
                                              "experiment_ref": experiment["ref"],
                                              "interpretation": "Thin wall mesh remains sensitive; root cause unknown",
                                              "next_action": "compare refined mesh"}, ref=ref)
        return assessment, run

    def test_managed_assessment_is_searchable_across_projects_without_source(self):
        study = StudyStore.create("@study/first", "Compare thin wall models", mode="cae")
        study.set_preferences("skip")  # Extra curation does not disable basic iteration preservation.
        assessment, run = self.create_assessment(study)
        self.assertEqual(study.experience_status()["published_count"], 1)
        self.assertEqual(study.get_run(run["run_id"])["status"], "completed")
        kb = KnowledgeBase("@knowledge")
        hits = kb.search("薄壁 网格", question="method-selection", domain="cae")
        self.assertTrue(hits)
        self.assertTrue(all(item["type"] == "feedback" for item in hits))
        before = {path.relative_to(kb.root): path.read_bytes() for path in kb.root.rglob("*") if path.is_file()}
        self.assertEqual(study.publish_experiences()["published_count"], 1)
        self.assertEqual(before, {path.relative_to(kb.root): path.read_bytes() for path in kb.root.rglob("*") if path.is_file()})
        # Discard only this fixture project: the central record must remain sufficient.
        self.assertTrue(study.root.is_relative_to(self.workspace))
        shutil.rmtree(study.root)
        central = kb.read(hits[0]["id"], version=hits[0]["version"])
        self.assertIn("mesh", central["content"])
        snapshots = list((kb.root / "iterations").rglob("*.json"))
        self.assertTrue(snapshots)
        saved = "\n".join(path.read_text(encoding="utf-8") for path in snapshots)
        self.assertIn(assessment["ref"], saved)
        self.assertIn(run["run_id"], saved)

    def test_publish_failure_is_pending_and_retry_uses_frozen_iteration(self):
        study = StudyStore.create("@study/failed-publish", "Preserve attempts", mode="cae")
        with patch("eds.experience.publish_iteration", side_effect=OSError("fixture disk unavailable")):
            with self.assertWarnsRegex(RuntimeWarning, "Assessment saved"):
                assessment, run = self.create_assessment(study, status="failed")
        status = study.resume()["experience_publication"]
        self.assertEqual(status["pending_count"], 1)
        self.assertIn("fixture disk", status["pending"][0]["error"])
        self.assertEqual(study.get_run(run["run_id"])["status"], "failed")
        queued = next(item["record"] for item in study.read()["events"]
                      if item["type"] == "experience_publication" and item["status"] == "pending")
        study.update_context(goal="Later unrelated goal")
        from eds.experience import publish_iteration
        with patch("eds.experience.publish_iteration", wraps=publish_iteration) as publish:
            result = study.publish_experiences(assessment_ref=assessment["ref"])
            self.assertEqual(publish.call_args.args[1], queued)
        self.assertEqual(result["pending_count"], 0)
        self.assertEqual(study.get_run(run["run_id"])["status"], "failed")

    def test_legacy_project_requires_binding_or_explicit_backfill(self):
        study = StudyStore.create(self.workspace / "legacy", "Legacy research", mode="cae")
        assessment, _ = self.create_assessment(study)
        self.assertEqual(study.experience_status()["published_count"], 0)
        result = dispatch(parser().parse_args(["study", str(study.root), "experience-publish",
                                               "--knowledge-root", "@knowledge", "--assessment", assessment["ref"]]))
        self.assertEqual(result["published_count"], 1)
        dispatch(parser().parse_args(["study", str(study.root), "experience-bind"]))
        self.create_assessment(study)
        self.assertEqual(study.experience_status()["published_count"], 2)

    def test_read_only_backfill_cli_preserves_source_and_retries_idempotently(self):
        study = StudyStore.create(self.workspace / "legacy-backfill", "Historical mesh study", mode="cae")
        assessment, _ = self.create_assessment(study)
        source = study.root / "study.json"
        original = source.read_bytes()
        args = parser().parse_args(["study", str(study.root), "experience-backfill",
                                    "--knowledge-root", "@knowledge", "--assessment", assessment["ref"]])
        with patch("eds.experience.publish_iteration", side_effect=OSError("fixture central disk unavailable")):
            result = dispatch(args)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(source.read_bytes(), original)
        for _ in range(2):
            result = dispatch(args)
            self.assertEqual(result["published_count"], 1)
            self.assertEqual(result["failed_count"], 0)
            self.assertEqual(source.read_bytes(), original)
        self.assertEqual(KnowledgeBase("@knowledge").status()["indexed"], 1)
        self.assertEqual(study.experience_status()["published_count"], 0)

    def test_repeated_publication_failure_does_not_duplicate_failure_events(self):
        study = StudyStore.create("@study/retry-failure", "Retry central publication", mode="cae")
        with patch("eds.experience.publish_iteration", side_effect=OSError("fixture unchanged failure")):
            with self.assertWarnsRegex(RuntimeWarning, "Assessment saved"):
                self.create_assessment(study)
            original = (study.root / "study.json").read_bytes()
            self.assertEqual(study.publish_experiences()["pending_count"], 1)
            self.assertEqual((study.root / "study.json").read_bytes(), original)
        self.assertEqual(study.publish_experiences()["pending_count"], 0)

    def test_failed_acknowledgement_preserves_assessment_and_retries_without_duplicates(self):
        study = StudyStore.create("@study/ack-failure", "Disk failure after publish", mode="cae")
        original_write = study._write

        def fail_ack(state):
            if state["events"] and state["events"][-1].get("status") == "published":
                raise OSError("fixture acknowledgement disk failure")
            return original_write(state)

        with patch.object(study, "_write", side_effect=fail_ack):
            with self.assertWarnsRegex(RuntimeWarning, "Assessment saved"):
                assessment, _ = self.create_assessment(study)
        self.assertEqual(study.get(ref=assessment["ref"]), assessment)
        self.assertEqual(study.experience_status()["pending_count"], 1)
        self.assertEqual(KnowledgeBase("@knowledge").status()["indexed"], 1)
        self.assertEqual(study.publish_experiences()["pending_count"], 0)
        self.assertEqual(KnowledgeBase("@knowledge").status()["indexed"], 1)

    def test_invalid_optional_guidance_does_not_discard_assessment(self):
        study = StudyStore.create("@study/invalid-guidance", "Preserve observed research", mode="cae")
        evidence = study.add("evidence", {"source": "fixture:paper", "observation": "author reported a result"})
        with self.assertWarnsRegex(RuntimeWarning, "Assessment saved"):
            assessment = study.add("assessment", {"evidence_refs": [evidence["ref"]],
                                                   "interpretation": "Not yet reproduced", "next_action": "compare conditions",
                                                   "experience": {"status": "misspelled"}})
        self.assertEqual(study.get(ref=assessment["ref"]), assessment)
        self.assertEqual(study.experience_status()["pending_count"], 1)
        count = len(study.read()["events"])
        result = study.publish_experiences()
        self.assertEqual(result["pending_count"], 1)
        self.assertEqual(len(study.read()["events"]), count)

    def test_relocated_managed_study_publishes_to_its_own_root(self):
        study = StudyStore.create("@study/movable", "Portable research", mode="cae")
        self.create_assessment(study)
        copied = self.workspace / "copied"
        shutil.copytree(self.data, copied)
        moved = StudyStore(copied / "studies/movable")
        self.create_assessment(moved)
        self.assertEqual(KnowledgeBase(copied / "knowledge").status()["indexed"], 2)
        self.assertEqual(KnowledgeBase("@knowledge").status()["indexed"], 1)

    def test_routes_include_empirical_feedback_for_execution_and_experiment_design(self):
        for question in ("execution-guidance", "failure-recovery", "experiment-design", "method-selection"):
            self.assertIn("feedback", knowledge_route(question=question)["selected_types"])
        self.assertEqual(knowledge_route(stage="execution")["primary_types"], ["feedback"])

    def test_literature_parameter_comparison_is_central_without_claiming_runtime_validation(self):
        study = StudyStore.create("@study/paper-discussion", "Thin fin parameter comparison", mode="cae")
        evidence = study.add("evidence", {"source": {"uri": "fixture:paper", "locator": "Table 3"},
                                          "observation": "Author reports lower temperature for a longer fin"})
        assessment = study.add("assessment", {
            "evidence_refs": [evidence["ref"]], "knowledge_refs": ["fin-method@1"],
            "interpretation": "Reported benefit may not transfer to our thin housing",
            "next_action": "Test matched boundary conditions",
            "experience": {"method_evaluations": [{
                "knowledge_ref": "fin-method@1", "product_features": {"geometry": "thin housing"},
                "conditions": {"source": "paper convection boundary"}, "parameter_changes": {"fin_length": "increased"},
                "comparison": {"baseline": "short fin", "candidate": "long fin", "metric": "maximum temperature"},
                "effect": "improved", "evidence_origin": "literature", "evidence_refs": [evidence["ref"]],
                "limitations": ["No local product experiment"]}]}})
        self.assertEqual(study.experience_status()["published_count"], 1)
        kb = KnowledgeBase("@knowledge")
        hits = kb.search("fin temperature", question="experiment-design", domain="cae")
        self.assertTrue(hits)
        result = kb.read(hits[0]["id"], version=hits[0]["version"])
        self.assertEqual(result["metadata"]["experience_status"], "unverified")
        source = kb.root / result["metadata"]["sources"][0]["uri"]
        record = json.loads(source.read_text(encoding="utf-8"))
        self.assertEqual(record["assessment_ref"], assessment["ref"])
        self.assertEqual(record["method_evaluations"][0]["evidence_origin"], "literature")
        self.assertEqual(record["actions"]["runs"], [])


if __name__ == "__main__":
    unittest.main()
