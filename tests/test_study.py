"""Behavioral regressions for resumable, immutable engineering records."""
import concurrent.futures
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eds.study import StudyError, StudyStore


class StudyStoreTests(unittest.TestCase):
    def setUp(self):
        self.test_root = Path(__file__).resolve().parents[1] / ".test-tmp"
        self.test_root.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=self.test_root)
        self.root = Path(self.tmp.name)
        self.store = StudyStore.create(self.root, "Compare bracket expressions", mode="cad")

    def tearDown(self):
        self.assertTrue(self.root.resolve().is_relative_to(self.test_root.resolve()))
        self.tmp.cleanup()

    def experiment(self, ref="experiment", refs=None, budget=None):
        payload = {
            "question": "Does the changed feature retain its reference?",
            "observations": ["attachment state", "measured thickness"],
            "decision_rule": "Retain only expressions with the intended interface",
            "refs": refs or [],
        }
        if budget is not None:
            payload["budget"] = budget
        return self.store.add("experiment", payload, ref=ref)

    def run_record(self, **overrides):
        if self.store.get(ref="experiment") is None:
            self.experiment()
        values = {"experiment_ref": "experiment", "input_refs": [], "backend": "cad-test",
                  "capability": "inspect", "input_snapshot": {"thickness_mm": 10},
                  "idempotency_key": "inspection-1"}
        values.update(overrides)
        return self.store.add_run(**values)

    def test_cad_and_cae_can_start_without_other_domain(self):
        self.assertEqual(self.store.read()["mode"], "cad")
        other = StudyStore.create(self.root / "cae", "Analyze existing model", mode="cae")
        self.assertEqual(other.read()["entities"], [])
        with self.assertRaises(StudyError):
            StudyStore.create(self.root / "bad", "Goal", mode="unrecognized")
        with self.assertRaises(StudyError):
            StudyStore.create(self.root / "empty", " ", mode="cad")

    def test_entity_revisions_and_references_stay_frozen(self):
        first = self.store.add("design", {"thickness_mm": 10}, ref="beam")
        experiment = self.experiment(refs=["beam"])
        self.store.add("design", {"thickness_mm": 12}, ref="beam")
        self.assertEqual(first["ref"], "beam@1")
        self.assertEqual(experiment["payload"]["refs"], ["beam@1"])
        self.assertEqual(self.store.get(ref="beam@1")["payload"]["thickness_mm"], 10)
        self.assertEqual(self.store.get(ref="beam")["payload"]["thickness_mm"], 12)
        with self.assertRaises(StudyError):
            self.store.add("decision", {"reason": "different object"}, ref="beam")

    def test_unknown_and_wrong_kind_relationships_are_rejected(self):
        design = self.store.add("design", {"thickness_mm": 10}, ref="beam")
        with self.assertRaises(StudyError):
            self.experiment(refs=["missing"])
        with self.assertRaises(StudyError):
            self.store.add("realization", {"proposal_ref": design["ref"], "observation": {}, "differences": []})
        with self.assertRaises(StudyError):
            self.store.add("assessment", {"evidence_refs": [design["ref"]], "interpretation": "ok", "next_action": "inspect"})
        with self.assertRaises(StudyError):
            self.store.add("evidence", {"source": "tool observation", "observation": {}, "run_id": "missing"})

    def test_external_source_and_asset_refs_are_not_internal_entity_refs(self):
        evidence = self.store.add("evidence", {
            "source": {"uri": "paper.pdf", "page": 4}, "source_ref": "paper.pdf#eq-2",
            "asset_ref": "remote:model-1", "observation": {"formula": "F = ma"},
        })
        self.assertEqual(evidence["payload"]["source_ref"], "paper.pdf#eq-2")

    def test_payload_minimum_shape_and_finite_values(self):
        for kind, payload in (("not-a-kind", {}), ("experiment", {"question": "q", "observations": [], "decision_rule": "r"}),
                              ("proposal", {"purpose": "", "assumptions": []}),
                              ("assessment", {"evidence_refs": [], "interpretation": "x", "next_action": "y"}),
                              ("design", {"length": float("nan")})):
            with self.subTest(kind=kind), self.assertRaises(StudyError):
                self.store.add(kind, payload)

    def test_run_request_validates_experiment_and_pins_input_versions(self):
        self.store.add("design", {"thickness_mm": 10}, ref="beam")
        with self.assertRaises(StudyError):
            self.run_record(experiment_ref="beam")
        first = self.run_record(input_refs=["beam"])
        self.store.add("design", {"thickness_mm": 12}, ref="beam")
        self.assertEqual(first["input_refs"], ["beam@1"])
        self.assertEqual(first["experiment_ref"], "experiment@1")

    def test_idempotency_compares_backend_capability_inputs_and_initial_task(self):
        first = self.run_record()
        self.assertEqual(self.run_record()["run_id"], first["run_id"])
        for change in ({"backend": "different"}, {"capability": "solve"}, {"input_snapshot": {"thickness_mm": 12}}, {"task_id": "new-task"}):
            with self.subTest(change=change), self.assertRaises(StudyError):
                self.run_record(**change)
        self.store.transition_run(first["run_id"], "submitting")
        self.store.transition_run(first["run_id"], "submitted", task_id="actual-task")
        self.assertEqual(self.run_record()["run_id"], first["run_id"])

    def test_submission_and_query_history_is_append_only(self):
        run = self.run_record()
        self.store.transition_run(run["run_id"], "submitting")
        self.store.transition_run(run["run_id"], "submitted", task_id="task-1", output={"accepted": True})
        self.store.transition_run(run["run_id"], "running", output={"iteration": 1})
        last = self.store.transition_run(run["run_id"], "running", output={"iteration": 2})
        self.assertEqual(last["history"][-2]["output"], {"iteration": 1})
        self.assertEqual(last["history"][-1]["task_id"], "task-1")
        with self.assertRaises(StudyError):
            self.store.transition_run(run["run_id"], "running", task_id="other-task")

    def test_completion_needs_actual_output_and_terminal_status_never_reopens(self):
        run = self.run_record()
        self.store.transition_run(run["run_id"], "submitting")
        with self.assertRaises(StudyError):
            self.store.transition_run(run["run_id"], "completed")
        self.store.transition_run(run["run_id"], "completed", output={"artifact": "result-v1"})
        with self.assertRaises(StudyError):
            self.store.transition_run(run["run_id"], "running")

    def test_resume_separates_unsubmitted_intent_from_uncertain_execution(self):
        first = self.run_record()
        self.assertEqual(self.store.resume()["query_before_resubmit"], [])
        self.assertEqual(self.store.resume()["ready_to_submit"], [first["run_id"]])
        self.store.transition_run(first["run_id"], "submitting")
        self.assertEqual(self.store.resume()["query_before_resubmit"], [first["run_id"]])
        self.store.transition_run(first["run_id"], "unknown", output={"reason": "connection lost"})
        self.store.transition_run(first["run_id"], "unknown", output={"query": "still unavailable"})
        with self.assertRaises(StudyError):
            self.store.transition_run(first["run_id"], "submitting")

    def test_compact_resume_excludes_nested_vendor_payloads_and_preserves_run_index(self):
        self.experiment()
        evidence = self.store.add("evidence", {
            "source": "VENDOR_LOG", "observation": {"nested": ["VENDOR_LOG"]},
        }, ref="vendor-evidence")
        self.store.add("assessment", {
            "evidence_refs": [evidence["ref"]], "interpretation": "VENDOR_LOG", "next_action": "inspect",
        }, ref="assessment")
        run = self.run_record(input_snapshot={"deep": {"marker": "VENDOR_LOG"}})
        self.store.transition_run(run["run_id"], "submitting", output={"history": "VENDOR_LOG"})
        self.store.set_summary(current_question="question", vendor_context={"raw": "VENDOR_LOG"})
        before = self.store.path.read_bytes()
        compact = self.store.resume()
        self.assertNotIn("VENDOR_LOG", json.dumps(compact))
        self.assertEqual(set(compact["current"]["vendor-evidence"]) - {"ref", "logical_ref", "version", "kind", "created_at"}, set())
        self.assertEqual(compact["pending_runs"][0]["run_id"], run["run_id"])
        self.assertIn("vendor_context", compact["omitted_context_keys"])
        self.assertEqual(before, self.store.path.read_bytes())

    def test_compact_resume_keeps_unknown_submitting_and_failed_run_metadata(self):
        old_input = self.store.add("design", {"thickness_mm": 10}, ref="beam")
        unknown = self.run_record(idempotency_key="unknown", task_id="existing-task", input_refs=[old_input["ref"]])
        self.store.add("design", {"thickness_mm": 12}, ref="beam")
        submitting = self.run_record(idempotency_key="submitting")
        self.store.transition_run(submitting["run_id"], "submitting")
        failed = self.run_record(idempotency_key="failed")
        self.store.transition_run(failed["run_id"], "submitting")
        self.store.transition_run(failed["run_id"], "failed", output={"error": "backend failure"})
        compact = self.store.resume()
        pending = {item["run_id"]: item for item in compact["pending_runs"]}
        self.assertEqual(pending[unknown["run_id"]]["status"], "unknown")
        self.assertEqual(pending[unknown["run_id"]]["task_id"], "existing-task")
        self.assertEqual(pending[unknown["run_id"]]["input_refs"], [old_input["ref"]])
        self.assertEqual(compact["current"]["beam"]["ref"], "beam@2")
        self.assertEqual(set(compact["query_before_submit"]), {unknown["run_id"], submitting["run_id"]})
        self.assertEqual(compact["ready_to_submit"], [])
        self.assertEqual(pending[submitting["run_id"]]["status"], "submitting")
        self.assertIsNone(pending[submitting["run_id"]]["task_id"])
        self.assertEqual(compact["failed_runs"][0]["run_id"], failed["run_id"])
        self.assertNotIn("history", compact["failed_runs"][0])

    def test_full_resume_and_get_run_retain_exact_details_without_mutation(self):
        run = self.run_record(input_snapshot={"secret": "raw"})
        self.store.transition_run(run["run_id"], "submitting")
        self.store.transition_run(run["run_id"], "failed", output={"raw": "failure"})
        before = self.store.path.read_bytes()
        full = self.store.resume(full=True)
        selected = self.store.get_run(run["run_id"])
        self.assertEqual(full["pending_runs"], [])
        self.assertEqual(selected["input_snapshot"], {"secret": "raw"})
        self.assertEqual(selected["history"][-1]["output"], {"raw": "failure"})
        self.assertEqual(full["current"]["experiment"], self.store.get(ref="experiment@1"))
        selected["input_snapshot"]["secret"] = "changed local copy"
        self.assertEqual(self.store.get_run(run["run_id"])["input_snapshot"], {"secret": "raw"})
        self.assertIsNone(self.store.get_run("run_missing"))
        self.assertEqual(before, self.store.path.read_bytes())

    def test_adopting_existing_task_requires_query_and_never_resubmits(self):
        run = self.run_record(task_id="already-submitted-job")
        self.assertEqual(run["status"], "unknown")
        self.assertEqual(run["history"][0]["status"], "unknown")
        self.assertEqual(self.store.resume()["query_before_resubmit"], [run["run_id"]])
        self.assertEqual(self.store.resume()["ready_to_submit"], [])
        self.assertEqual(self.run_record(task_id="already-submitted-job")["run_id"], run["run_id"])
        with self.assertRaises(StudyError):
            self.store.transition_run(run["run_id"], "submitting")
        self.store.transition_run(run["run_id"], "running", output={"queried_progress": 0.5})
        finished = self.store.transition_run(run["run_id"], "completed", output={"artifact": "actual-result"})
        self.assertEqual(finished["task_id"], "already-submitted-job")
        self.assertEqual(self.run_record(task_id="already-submitted-job")["status"], "completed")
        self.assertEqual(self.store.read()["runs"][0]["history"][0]["status"], "unknown")

    def test_existing_task_can_reconcile_directly_to_completed(self):
        run = self.run_record(task_id="old-job")
        finished = self.store.transition_run(run["run_id"], "completed", output={"artifact": "observed-on-backend"})
        self.assertEqual(finished["status"], "completed")

    def test_read_rejects_existing_task_disguised_as_unsubmitted(self):
        self.run_record(task_id="old-job")
        state = self.store.read()
        state["runs"][0]["status"] = "planned"
        state["runs"][0]["history"][0]["status"] = "planned"
        self.store.path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(StudyError):
            self.store.resume()

    def test_same_backend_task_cannot_attach_to_two_runs(self):
        first = self.run_record()
        second = self.run_record(idempotency_key="second")
        for item in (first, second):
            self.store.transition_run(item["run_id"], "submitting")
        self.store.transition_run(first["run_id"], "submitted", task_id="task-1")
        with self.assertRaises(StudyError):
            self.store.transition_run(second["run_id"], "submitted", task_id="task-1")

    def test_change_impact_traverses_run_evidence_and_assessment(self):
        self.store.add("design", {"thickness_mm": 10}, ref="beam")
        self.experiment(refs=["beam"])
        run = self.run_record(input_refs=["beam"])
        self.store.transition_run(run["run_id"], "submitting")
        self.store.transition_run(run["run_id"], "completed", output={"length_mm": 20})
        self.store.add("evidence", {"source": "backend result", "run_id": run["run_id"], "observation": {"length_mm": 20}}, ref="measurement")
        self.store.add("assessment", {"evidence_refs": ["measurement"], "interpretation": "dimension matches", "next_action": "review"}, ref="judgment")
        self.store.add("design", {"thickness_mm": 12}, ref="beam")
        impact = self.store.impact("beam@1")
        self.assertIn("measurement@1", impact["affected"])
        self.assertIn("judgment@1", impact["affected"])
        self.assertEqual(impact["old_results_require_review"], [run["run_id"]])
        self.assertEqual(self.store.impact("beam@2")["affected"], [])

    def test_context_summary_metrics_and_report_preserve_unknowns(self):
        self.store.update_context(facts=["Native file inspected"], assumptions=["isotropic"], assets=[{"uri": "beam.step", "version": "1"}], gaps=["material calibration"])
        self.store.set_summary(next_step="inspect support", conditions=["small deflection"], stop_reason="await independent reference")
        self.store.set_metrics(elapsed_seconds=12.5, human_inputs=2)
        resume = self.store.resume()
        self.assertEqual(resume["assets"][0]["version"], "1")
        self.assertEqual(resume["assumptions"], ["isotropic"])
        self.assertEqual(resume["next_step"], "inspect support")
        report = self.store.render_report()
        self.assertIsNone(report["metrics"]["model_cost"])
        self.assertEqual(report["metrics"]["elapsed_seconds"], 12.5)
        self.assertEqual(report["stop_reason"], "await independent reference")
        self.assertGreaterEqual(len(self.store.read()["events"]), 3)

    def test_auto_extraction_can_record_multiple_events_idempotently(self):
        self.store.set_preferences("auto")
        first = self.store.record_extraction(["method@1"], event_key="round-1")
        same = self.store.record_extraction(["method@1"], event_key="round-1")
        second = self.store.record_extraction(["feedback@1"], event_key="round-2")
        self.assertEqual(first["event_id"], same["event_id"])
        self.assertNotEqual(first["event_id"], second["event_id"])
        with self.assertRaises(StudyError):
            self.store.record_extraction(["method@2"], event_key="round-1")

    def test_once_is_consumed_but_later_and_skip_allow_explicit_backfill(self):
        self.store.set_preferences("once")
        self.store.record_extraction(["method@1"])
        self.assertEqual(self.store.read()["preferences"]["extraction"], "later")
        self.store.record_extraction(["method@1"])
        for preference in ("later", "skip"):
            self.store.set_preferences(preference)
            with self.assertRaises(StudyError):
                self.store.record_extraction([f"{preference}@1"])
            self.store.record_extraction([f"{preference}@1"], explicit=True)
        self.assertEqual(self.store.read()["preferences"]["extraction"], "skip")

    def test_concurrent_mutations_do_not_lose_entities(self):
        def add(index):
            return StudyStore(self.root).add("design", {"index": index}, ref=f"d-{index}")
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(add, range(24)))
        self.assertEqual(len(results), 24)
        self.assertEqual(len(self.store.read()["entities"]), 24)

    def test_concurrent_create_has_one_winner(self):
        path = self.root / "new"
        def create(_):
            try:
                StudyStore.create(path, "one study", mode="cae")
                return True
            except StudyError:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(create, range(8)))
        self.assertEqual(sum(results), 1)

    def test_mcp_attempt_budget_is_atomic_and_cancel_before_submit_releases(self):
        self.experiment(budget={"mcp_call_limits": {"solve": 2}})

        def add(index):
            return self.store.add_run(
                experiment_ref="experiment@1", input_refs=[], backend="mcp", capability="solve",
                input_snapshot={"tool": "solve", "arguments": {"x": index}, "server_url": "srv"},
                idempotency_key=f"budget-{index}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(add, index) for index in range(4)]
            results = []
            for future in futures:
                try:
                    results.append(future.result())
                except StudyError as exc:
                    results.append(exc)
        runs = [item for item in results if isinstance(item, dict)]
        self.assertEqual(len(runs), 2)
        self.store.transition_run(runs[0]["run_id"], "cancelled")
        replacement = add(10)
        self.assertEqual(replacement["status"], "planned")
        self.store.transition_run(runs[1]["run_id"], "submitting")
        self.store.transition_run(runs[1]["run_id"], "failed", output={"error": "backend"})
        with self.assertRaises(StudyError):
            add(11)

    def test_repeated_action_requires_new_evidence_or_realization(self):
        self.experiment()
        first = self.store.add_run(
            experiment_ref="experiment@1", input_refs=[], backend="mcp", capability="solve",
            input_snapshot={"tool": "solve", "arguments": {"x": 1}, "server_url": "srv"},
            idempotency_key="action-1")
        self.store.transition_run(first["run_id"], "submitting")
        self.store.transition_run(first["run_id"], "failed", output={"error": "business"})
        with self.assertRaises(StudyError):
            self.store.add_run(experiment_ref="experiment@1", input_refs=[], backend="mcp", capability="solve",
                               input_snapshot={"tool": "solve", "arguments": {"x": 1}, "server_url": "srv"},
                               idempotency_key="action-2")
        evidence = self.store.add("evidence", {"source": "new observation", "observation": {"x": 1}}, ref="new-state")
        second = self.store.add_run(
            experiment_ref="experiment@1", input_refs=[evidence["ref"]], backend="mcp", capability="solve",
            input_snapshot={"tool": "solve", "arguments": {"x": 1}, "server_url": "srv"},
            idempotency_key="action-3")
        self.assertEqual(second["status"], "planned")

    def test_completed_read_only_observation_allows_same_action_as_new_run(self):
        self.experiment()
        snapshot = {"tool": "inspect", "arguments": {"x": 1}, "server_url": "srv",
                    "read_only": True}
        first = self.store.add_run(experiment_ref="experiment@1", input_refs=[], backend="mcp",
                                   capability="inspect", input_snapshot=snapshot,
                                   idempotency_key="observation-1")
        self.store.transition_run(first["run_id"], "submitting")
        self.store.transition_run(first["run_id"], "completed", output={"ok": True})
        second = self.store.add_run(experiment_ref="experiment@1", input_refs=[], backend="mcp",
                                    capability="inspect", input_snapshot=snapshot,
                                    idempotency_key="observation-2")
        self.assertEqual(second["status"], "planned")

    def test_pending_same_action_blocks_changed_refs_and_preflight_failure_releases_budget(self):
        self.experiment(budget={"mcp_call_limits": {"solve": 1}})
        first = self.store.add_run(
            experiment_ref="experiment@1", input_refs=[], backend="mcp", capability="solve",
            input_snapshot={"tool": "solve", "arguments": {"x": 1}, "server_url": "srv"},
            idempotency_key="pending-1")
        self.store.transition_run(first["run_id"], "submitting")
        evidence = self.store.add("evidence", {"source": "new", "observation": {}}, ref="new-evidence")
        with self.assertRaises(StudyError):
            self.store.add_run(experiment_ref="experiment@1", input_refs=[evidence["ref"]], backend="mcp",
                               capability="solve", input_snapshot={"tool": "solve", "arguments": {"x": 1}, "server_url": "srv"},
                               idempotency_key="pending-2")
        self.store.transition_run(first["run_id"], "failed", output={
            "preflight_rejected": True, "tool_sent": False,
        })
        retry = self.store.add_run(experiment_ref="experiment@1", input_refs=[evidence["ref"]], backend="mcp",
                                   capability="solve", input_snapshot={"tool": "solve", "arguments": {"x": 1}, "server_url": "srv"},
                                   idempotency_key="pending-3")
        self.assertEqual(retry["status"], "planned")

    def test_adopted_unknown_cancelled_does_not_release_attempt_budget(self):
        self.experiment(budget={"mcp_call_limits": {"solve": 1}})
        adopted = self.store.add_run(
            experiment_ref="experiment@1", input_refs=[], backend="mcp", capability="solve",
            input_snapshot={"tool": "solve", "arguments": {"x": 1}, "server_url": "srv"},
            idempotency_key="adopted", task_id="remote-task")
        self.store.transition_run(adopted["run_id"], "cancelled")
        with self.assertRaises(StudyError):
            self.store.add_run(experiment_ref="experiment@1", input_refs=[], backend="mcp", capability="solve",
                               input_snapshot={"tool": "solve", "arguments": {"x": 2}, "server_url": "srv"},
                               idempotency_key="after-adopted")

    def test_multiple_processes_share_the_same_write_lock(self):
        code = (
            "import sys; from eds.study import StudyStore; s=StudyStore(sys.argv[1]); "
            "[s.add('design', {'worker': sys.argv[2], 'index': i}, ref=sys.argv[2]+'-'+str(i)) for i in range(4)]"
        )
        processes = [subprocess.Popen(
            [sys.executable, "-c", code, str(self.root), str(index)],
            cwd=Path(__file__).resolve().parents[1], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ) for index in range(4)]
        for process in processes:
            _, errors = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, errors.decode(errors="replace"))
        self.assertEqual(len(self.store.read()["entities"]), 16)

    def test_os_releases_lock_when_holder_process_crashes(self):
        code = "import os,sys; from eds.study import StudyStore; s=StudyStore(sys.argv[1]);\nwith s._lock(): os._exit(0)"
        result = subprocess.run([sys.executable, "-c", code, str(self.root)], cwd=Path(__file__).resolve().parents[1], timeout=10, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.store.add("design", {"after": "crash"})
        self.assertEqual(len(self.store.read()["entities"]), 1)

    def test_failed_replace_preserves_previous_file_and_releases_lock(self):
        before = self.store.path.read_bytes()
        with patch("eds.study.os.replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                self.store.add("design", {"thickness_mm": 10})
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(list(self.root.glob("study.*.tmp")), [])
        self.store.add("design", {"thickness_mm": 12})

    def test_read_rejects_corruption_not_just_invalid_json(self):
        baseline = self.store.read()
        invalid = [[], {**baseline, "entities": "wrong type"}, {**baseline, "runs": [{}]}, {**baseline, "preferences": {"extraction": "bad"}}]
        for data in invalid:
            with self.subTest(data=data):
                self.store.path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(StudyError):
                    self.store.read()
        self.store.path.write_text('{"schema":"eds-study/v1","value":NaN}', encoding="utf-8")
        with self.assertRaises(StudyError):
            self.store.read()

    def test_read_rejects_tampered_version_references_and_history(self):
        self.store.add("design", {"thickness_mm": 10}, ref="beam")
        self.experiment(refs=["beam"])
        original = self.store.read()
        original["entities"][1]["payload"]["refs"] = ["beam@99"]
        self.store.path.write_text(json.dumps(original), encoding="utf-8")
        with self.assertRaises(StudyError):
            self.store.resume()

    def test_read_rejects_tampered_run_output(self):
        run = self.run_record()
        self.store.transition_run(run["run_id"], "submitting")
        self.store.transition_run(run["run_id"], "completed", output={"result": 1})
        state = self.store.read()
        state["runs"][0]["output"] = {"result": 2}
        self.store.path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(StudyError):
            self.store.read()

    def test_read_rejects_duplicate_json_keys(self):
        original = self.store.path.read_text(encoding="utf-8")
        self.store.path.write_text(original.replace('"mode": "cad"', '"mode": "cad", "mode": "cae"'), encoding="utf-8")
        with self.assertRaises(StudyError):
            self.store.read()

    def test_invalid_context_and_metrics_leave_previous_records_intact(self):
        before = self.store.path.read_bytes()
        for operation in (
            lambda: self.store.update_context(facts="not a list"),
            lambda: self.store.set_metrics(human_inputs=True),
            lambda: self.store.set_metrics(elapsed_seconds=-1),
            lambda: self.store.set_metrics(model_cost=2),
            lambda: self.store.set_metrics(run_count=100),
        ):
            with self.assertRaises(StudyError):
                operation()
            self.assertEqual(self.store.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
