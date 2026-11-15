import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eds import StudyStore
from eds.experience import build_iteration, publish_iteration
from eds.knowledge import KnowledgeBase


class StorageMigrationTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / "output/repository-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.study = StudyStore.create(self.root / "study", "Preserve friction evidence", mode="cae")
        self.kb = self.root / "knowledge"
        exp = self.study.add("experiment", {"question": "Does the response converge?", "observations": ["amplitude"],
                                             "decision_rule": "Compare amplitude under time refinement"}, ref="experiment")
        run = self.study.add_run(experiment_ref=exp["ref"], backend="fixture", capability="solve",
                                 input_refs=[], input_snapshot={"force_N": 0.05}, idempotency_key="fixture")
        self.study.transition_run(run["run_id"], "submitting")
        self.study.transition_run(run["run_id"], "completed", output={"amplitude_mm": 2.207})
        evidence = self.study.add("evidence", {"experiment_ref": exp["ref"], "run_id": run["run_id"],
                                              "source": "fixture:result", "observation": {"amplitude_mm": 2.207}}, ref="evidence")
        self.assessment = self.study.add("assessment", {"evidence_refs": [evidence["ref"]],
                                                        "interpretation": "Only one converged point", "next_action": "check stability"}, ref="assessment")
        state = self.study.read()
        state["runs"][0]["input_snapshot"]["arguments"] = {"code": "TRANSFER_PAYLOAD" * 30000}
        self.study._write(state)
        record = build_iteration(state, self.assessment["ref"])
        record["schema"] = "eds-experience/v1"
        record["actions"]["runs"] = state["runs"]
        self.publication = publish_iteration(self.kb, record)
        state = self.study.read()
        for target, ident in [(str(self.kb), "absolute"), (str(self.kb / "."), "alias")]:
            self.study._event(state, "experience_publication", publication_id=ident,
                              assessment_ref=self.assessment["ref"], knowledge_root=target,
                              status="pending", record=record)
            self.study._event(state, "experience_publication", publication_id=ident,
                              assessment_ref=self.assessment["ref"], knowledge_root=target,
                              status="published", result=self.publication)
        self.study._write(state)

    def test_dry_run_does_not_change_sources_or_create_backup(self):
        from eds.storage_migration import migrate_storage
        paths = [self.study.path, Path(self.publication["snapshot_path"]), Path(self.publication["path"])]
        before = {p: p.read_bytes() for p in paths}
        report = migrate_storage(self.study.root, self.kb)
        self.assertEqual(report["status"], "dry_run")
        self.assertEqual(report["knowledge_records_to_migrate"], 1)
        self.assertEqual(report["publication_record_copies_removed"], 2)
        self.assertEqual({p: p.read_bytes() for p in paths}, before)
        self.assertFalse(list(self.root.glob("*.tar.gz")))

    def test_apply_preserves_science_removes_snapshots_and_is_idempotent(self):
        from eds.storage_migration import migrate_storage, _run_digests
        original = self.study.read()
        original_bytes = self.study.path.stat().st_size
        report = migrate_storage(self.study.root, self.kb, apply=True)
        self.assertEqual(report["status"], "applied")
        current = self.study.read()
        self.assertEqual(current["entities"], original["entities"])
        self.assertEqual(_run_digests(current), _run_digests(original))
        self.assertTrue(all("record" not in e for e in current["events"] if e["type"] == "experience_publication"))
        source = Path(self.publication["snapshot_path"])
        compact = json.loads(source.read_text())
        self.assertEqual(compact["schema"], "eds-experience/v2")
        self.assertEqual(compact["analysis"]["interpretation"], "Only one converged point")
        self.assertNotIn("input_snapshot", compact["actions"]["runs"][0])
        self.assertLess(self.study.path.stat().st_size, original_bytes / 10)
        self.assertLess(source.stat().st_size, 20000)
        self.assertTrue(KnowledgeBase(self.kb).status()["consistent"])
        backup = Path(report["backup_path"])
        with tarfile.open(backup, "r:gz") as archive:
            self.assertIn("study/study.json", archive.getnames())
            self.assertIn("manifest.json", archive.getnames())
        again = migrate_storage(self.study.root, self.kb, apply=True)
        self.assertEqual(again["status"], "already_compact")

    def test_failure_rolls_back_source_bytes(self):
        from eds.storage_migration import migrate_storage
        paths = [self.study.path, Path(self.publication["snapshot_path"]), Path(self.publication["path"])]
        before = {p: p.read_bytes() for p in paths}
        with patch("eds.storage_migration._rebuild_index", side_effect=OSError("fixture index failure")):
            with self.assertRaisesRegex(OSError, "fixture index failure"):
                migrate_storage(self.study.root, self.kb, apply=True)
        self.assertEqual({p: p.read_bytes() for p in paths}, before)

    def test_explicit_rollback_restores_exact_legacy_representations(self):
        from eds.storage_migration import migrate_storage, rollback_storage_migration
        before = self.study.path.read_bytes()
        report = migrate_storage(self.study.root, self.kb, apply=True)
        rollback = rollback_storage_migration(report["backup_path"])
        self.assertEqual(rollback["status"], "rolled_back")
        self.assertEqual(self.study.path.read_bytes(), before)
        self.assertEqual(json.loads(Path(self.publication["snapshot_path"]).read_text())["schema"], "eds-experience/v1")

    def test_run_only_payload_migration_and_rollback(self):
        from eds.storage_migration import migrate_storage, rollback_storage_migration
        migrate_storage(self.study.root, self.kb, apply=True)
        # A legacy writer can introduce inline data even after the storage marker.
        raw = json.loads(self.study.path.read_text())
        arguments = {"code": "solver script" * 3000}
        output = {"amplitudes": [1.2345] * 5000}
        raw["runs"][0]["input_snapshot"]["arguments"] = arguments
        raw["runs"][0]["history"][-1]["output"] = output
        self.study.path.write_text(json.dumps(raw))
        before = self.study.path.read_bytes()
        report = migrate_storage(self.study.root, self.kb, apply=True)
        self.assertEqual(report["status"], "applied")
        run = self.study.read()["runs"][0]
        self.assertEqual(self.study.read_artifact(run["input_snapshot"]["arguments"]), arguments)
        self.assertEqual(self.study.read_artifact(run["output"]), output)
        self.assertEqual(migrate_storage(self.study.root, self.kb, apply=True)["status"], "already_compact")
        rollback_storage_migration(report["backup_path"])
        self.assertEqual(self.study.path.read_bytes(), before)

    def test_different_content_rejected_alias_retains_compact_intent(self):
        from eds.storage_migration import migrate_storage
        state = self.study.read()
        pending = next(e for e in state["events"] if e.get("publication_id") == "alias" and e["status"] == "pending")
        pending["record"]["analysis"]["interpretation"] = "Conflicting rejected attempt"
        final = next(e for e in state["events"] if e.get("publication_id") == "alias" and e["status"] == "published")
        final["status"] = "failed"
        final.pop("result")
        final["error"] = "same-version content differs"
        self.study._write(state)
        report = migrate_storage(self.study.root, self.kb, apply=True)
        self.assertEqual(report["publication_record_copies_removed"], 1)
        current = self.study.read()
        retained = next(e for e in current["events"] if e["event_id"] == pending["event_id"])
        self.assertEqual(retained["record"]["schema"], "eds-experience/v2")
        self.assertEqual(retained["record"]["analysis"]["interpretation"], "Conflicting rejected attempt")
        self.assertEqual(next(e for e in current["events"] if e["event_id"] == final["event_id"])["status"], "failed")
        self.assertEqual(migrate_storage(self.study.root, self.kb, apply=True)["status"], "already_compact")

    def test_rollback_refuses_later_user_edits(self):
        from eds.storage_migration import migrate_storage, rollback_storage_migration, StorageMigrationError
        report = migrate_storage(self.study.root, self.kb, apply=True)
        changed = self.study.path.read_bytes() + b"\n"
        self.study.path.write_bytes(changed)
        with self.assertRaisesRegex(StorageMigrationError, "source changed"):
            rollback_storage_migration(report["backup_path"])
        self.assertEqual(self.study.path.read_bytes(), changed)

    def test_invalid_backup_prevents_all_mutation(self):
        from eds.storage_migration import migrate_storage, StorageMigrationError
        before = self.study.path.read_bytes()
        with patch("eds.storage_migration._verify_backup", side_effect=StorageMigrationError("fixture checksum mismatch")):
            with self.assertRaisesRegex(StorageMigrationError, "checksum mismatch"):
                migrate_storage(self.study.root, self.kb, apply=True)
        self.assertEqual(self.study.path.read_bytes(), before)

    def test_central_only_run_payload_refuses_migration(self):
        from eds.storage_migration import migrate_storage, StorageMigrationError
        source = Path(self.publication["snapshot_path"])
        record = json.loads(source.read_text())
        record["actions"]["runs"][0]["input_snapshot"]["arguments"] = {"code": "UNIQUE_SCIENTIFIC_INPUT"}
        source.write_text(json.dumps(record))
        before = {p: p.read_bytes() for p in (source, self.study.path)}
        with self.assertRaisesRegex(StorageMigrationError, "input_snapshot.arguments.*not retained"):
            migrate_storage(self.study.root, self.kb, apply=True)
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        self.assertFalse(list(self.root.glob("*.tar.gz")))

    def test_outbox_only_output_refuses_migration(self):
        from eds.storage_migration import migrate_storage, StorageMigrationError
        state = self.study.read()
        event = next(e for e in state["events"] if "record" in e)
        event["record"]["actions"]["runs"][0]["output"] = {"unique": "not in Study history"}
        self.study._write(state)
        with self.assertRaisesRegex(StorageMigrationError, "output.*not retained"):
            migrate_storage(self.study.root, self.kb)

    def test_historical_run_prefix_survives_latest_state_difference(self):
        from eds.storage_migration import migrate_storage
        source = Path(self.publication["snapshot_path"])
        record = json.loads(source.read_text())
        run = record["actions"]["runs"][0]
        run["history"] = run["history"][:-1]
        for observation in run["history"]:
            observation.pop("recorded_at", None)
        run.update(status="submitting", output=None, updated_at=run["history"][-1]["at"], temporal_status="unknown")
        record["actions"]["run_statuses"] = ["submitting"]
        source.write_text(json.dumps(record))
        self.assertEqual(migrate_storage(self.study.root, self.kb, apply=True)["status"], "applied")

    def test_nonprefix_history_locator_uses_retained_study_index(self):
        from eds.storage_migration import migrate_storage
        source = Path(self.publication["snapshot_path"])
        record = json.loads(source.read_text())
        run = record["actions"]["runs"][0]
        actual_index = len(run["history"]) - 1
        run["history"] = [run["history"][0], run["history"][-1]]
        source.write_text(json.dumps(record))
        self.assertEqual(migrate_storage(self.study.root, self.kb, apply=True)["status"], "applied")
        ledger = json.loads(source.read_text())["actions"]["runs"][0]
        self.assertEqual(ledger["source"]["observation_index"], actual_index)
        self.assertNotEqual(ledger["source"]["observation_index"], len(run["history"]) - 1)

    def test_failed_migration_does_not_undo_concurrent_registration(self):
        from eds.storage_migration import migrate_storage
        from tests.test_knowledge import unit
        kb = KnowledgeBase(self.kb)
        added = self.kb / "new-method.md"
        unit(added, "concurrent-method")
        def register_then_fail(_root):
            kb.register(added)
            raise OSError("index interrupted after registration")
        before = self.study.path.read_bytes()
        with patch("eds.storage_migration._rebuild_index", side_effect=register_then_fail):
            with self.assertRaisesRegex(OSError, "index interrupted"):
                migrate_storage(self.study.root, self.kb, apply=True)
        self.assertEqual(self.study.path.read_bytes(), before)
        self.assertIn("new-method.md", json.loads(kb.registry_path.read_text())["documents"])
        kb.rebuild()
        self.assertEqual(kb.read("concurrent-method", "1")["metadata"]["id"], "concurrent-method")


if __name__ == "__main__":
    unittest.main()
