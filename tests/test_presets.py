import concurrent.futures
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eds.knowledge import KnowledgeBase, KnowledgeError
from eds.presets import PresetStore, TASK_FORMAT, validate_snapshot


def write_pref(root, uid, value="A3", *, scope="user", scope_id="u1", status="confirmed", version="1", key="drawing.layout", project=None, relations=None, conditions=None):
    meta = {
        "id": uid, "version": version, "type": "preference", "title": uid,
        "sources": [{"uri": "fixture", "locator": uid}], "conditions": conditions or {},
        "relations": relations or [], "preference_key": key, "value": value,
        "scope": scope, "scope_id": scope_id, "preference_status": status,
        "origin": "explicit", "domain": "cad", "question": "drawing",
    }
    if project:
        meta["project"] = project
    path = root / (uid + "-" + version + ".md")
    path.write_text("<!-- eds-knowledge: " + json.dumps(meta, ensure_ascii=False) + " -->\n\n" + value + "\n", encoding="utf-8")
    return path


class PresetTests(unittest.TestCase):
    def setUp(self):
        temporary_root = Path(__file__).resolve().parent.parent / "output" / "repository-tests" / "tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=temporary_root, prefix="preset-")
        self.root = Path(self.tmp.name)
        self.kb = KnowledgeBase(self.root)
        self.ctx = {"domain": "cad", "question": "drawing", "user": "u1", "project": "p1"}

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, uid="p", **kwargs):
        path = write_pref(self.root, uid, **kwargs)
        self.kb.register(path)
        return path

    def store(self):
        return PresetStore(self.root, self.kb)

    def activate(self, refs=None, name="mine", context=None):
        return self.store().activate(name, context=context or self.ctx, refs=refs or [{"id": "p", "version": "1"}])

    def test_hash_tampering_is_rejected(self):
        self.add()
        snap = self.activate()
        snap["values"]["drawing.layout"] = "A4"
        with self.assertRaises(KnowledgeError):
            validate_snapshot(snap)

    def test_task_values_are_effective_and_base_is_unchanged(self):
        self.add()
        s = self.store(); s.activate("mine", context=self.ctx, refs=[{"id": "p", "version": "1"}])
        task = s.for_task(context=self.ctx, overrides={"drawing.layout": "A4"})
        self.assertEqual(task["values"]["drawing.layout"], "A4")
        self.assertEqual(task["base"]["values"]["drawing.layout"], "A3")
        self.assertEqual(s.current(context=self.ctx)["values"]["drawing.layout"], "A3")

    def test_named_preset_contexts_do_not_cross(self):
        self.add()
        s = self.store(); other = {"domain": "cad", "question": "drawing", "user": "u2"}
        s.activate("mine", context=self.ctx, refs=[{"id": "p", "version": "1"}])
        self.assertIsNone(s.current(context=other))

    def test_conflicting_refs_are_rejected(self):
        self.add("p1", value="A3")
        self.add("p2", value="A4", key="drawing.layout")
        with self.assertRaises(KnowledgeError):
            self.store().activate("mine", context=self.ctx, refs=[{"id": "p1", "version": "1"}, {"id": "p2", "version": "1"}])

    def test_empty_refs_make_empty_preset(self):
        snap = self.store().activate("empty", context=self.ctx, refs=[])
        self.assertEqual(snap["values"], {})

    def test_invalid_overrides_and_unknown_context_are_rejected(self):
        self.add(); s = self.store(); s.activate("mine", context=self.ctx, refs=[{"id": "p", "version": "1"}])
        with self.assertRaises(KnowledgeError): s.for_task(context=self.ctx, overrides=[])
        with self.assertRaises(KnowledgeError): s.for_task(context={**self.ctx, "other": "x"})

    def test_project_scope_isolation(self):
        path = write_pref(self.root, "project-pref", scope="project", scope_id="p2")
        self.kb.register(path)
        with self.assertRaises(KnowledgeError):
            self.store().activate("mine", context=self.ctx, refs=[{"id": "project-pref", "version": "1"}])

    def test_candidate_retired_and_superseded_refs_are_rejected(self):
        for status in ("candidate", "retired"):
            self.add("bad-" + status, status=status)
            with self.assertRaises(KnowledgeError):
                self.store().activate("mine-" + status, context=self.ctx, refs=[{"id": "bad-" + status, "version": "1"}])
        self.add("revised")
        self.add("revised", version="2", relations=[{"type": "supersedes", "id": "revised", "version": "1"}])
        with self.assertRaisesRegex(KnowledgeError, "superseded"):
            self.activate(refs=[{"id": "revised", "version": "1"}])

    def test_current_and_task_do_not_query_knowledge(self):
        self.add(); s = self.store(); s.activate("mine", context=self.ctx, refs=[{"id": "p", "version": "1"}])
        with patch.object(s.kb, "read", side_effect=AssertionError("read")), \
             patch.object(s.kb, "search", side_effect=AssertionError("search")), \
             patch.object(s.kb, "preference_catalog", side_effect=AssertionError("catalog")), \
             patch.object(s.kb, "register_many", side_effect=AssertionError("register")):
            self.assertEqual(s.current(context=self.ctx)["name"], "mine")
            self.assertEqual(s.for_task(context=self.ctx)["name"], "mine")

    def test_real_content_hash_and_noop_save_keeps_preference_bytes(self):
        self.add(); s = self.store(); s.activate("mine", context=self.ctx, refs=[{"id": "p", "version": "1"}])
        first = s.save_default(context=self.ctx, overrides={"drawing.layout": "A4"}, source="user")
        self.assertTrue(first["sources"][0]["content_hash"])
        files = {p: p.read_bytes() for p in (self.root / ".eds-presets" / "preferences").glob("*.md")}
        s.save_default(context=self.ctx, overrides={"drawing.layout": "A4"}, source="user")
        self.assertEqual(files, {p: p.read_bytes() for p in files})

    def test_unicode_identity_does_not_collide(self):
        self.add(); s = self.store(); c2 = {"domain": "cad", "question": "drawing", "user": "用户二"}
        s.activate("mine", context=self.ctx, refs=[{"id": "p", "version": "1"}])
        self.assertIsNone(s.current(context=c2))

    def test_same_name_in_multiple_contexts_and_distinct_presets_survive(self):
        s = self.store()
        expected = []
        for user, name, value in (("用户一", "图样", "A3"), ("用户二", "图样", "A4"),
                                  ("用户二", "客户图样", "A2")):
            context = {**self.ctx, "user": user}
            s.activate(name, context=context, refs=[])
            snapshot = s.save_default(context=context, overrides={"drawing.layout": value}, source="explicit")
            expected.append((context, name, snapshot))
        self.assertEqual(len(list(self.root.rglob("*.md"))), 3)
        for context, name, snapshot in expected:
            self.assertEqual(s.activate(name, context=context), snapshot)
            self.assertEqual(s.current(context=context), snapshot)

    def test_personal_project_restriction_is_enforced(self):
        self.add("restricted", project="another-project")
        with self.assertRaises(KnowledgeError):
            self.activate(refs=[{"id": "restricted", "version": "1"}])

    def test_saving_personal_override_preserves_team_source(self):
        self.ctx["team"] = "team1"
        path = self.add("team", scope="team", scope_id="team1")
        original = path.read_bytes()
        s = self.store()
        s.activate("mine", context=self.ctx, refs=[{"id": "team", "version": "1"}])
        first = s.save_default(context=self.ctx, overrides={"drawing.layout": "A4"}, source="explicit")
        second = s.save_default(context=self.ctx, overrides={"drawing.layout": "A2"}, source="explicit again")
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(second["sources"][0]["scope"], "user")
        units = {unit["id"] + "@" + unit["version"]: unit for unit in self.kb.preference_catalog()}
        self.assertFalse(units["team@1"]["superseded"])
        ref = first["sources"][0]
        self.assertTrue(units[ref["id"] + "@" + ref["version"]]["superseded"])

    def test_concurrent_saves_preserve_independent_changes(self):
        self.store().activate("mine", context=self.ctx, refs=[])
        def save(i):
            return self.store().save_default(context=self.ctx, overrides={f"style.field{i}": str(i)}, source="explicit")
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(save, range(4)))
        self.assertEqual(len(results), 4)
        self.assertEqual(self.store().current(context=self.ctx)["values"],
                         {f"style.field{i}": str(i) for i in range(4)})
        self.assertEqual(len(list(self.root.rglob("*.md"))), 4)

    def test_failed_save_does_not_publish_partial_default_and_retry_recovers(self):
        s = self.store()
        before = s.activate("mine", context=self.ctx, refs=[])
        values = {"drawing.layout": "A3", "delivery.format": "png"}
        with patch.object(self.kb, "register_many", side_effect=OSError("injected index failure")):
            with self.assertRaisesRegex(KnowledgeError, "not activated"):
                s.save_default(context=self.ctx, overrides=values, source="explicit")
        self.assertEqual(s.current(context=self.ctx), before)
        self.assertFalse(self.kb.registry_path.exists())
        restored = s.save_default(context=self.ctx, overrides=values, source="explicit")
        self.assertEqual(restored["values"], values)
        self.assertEqual(len(list(self.root.rglob("*.md"))), 2)

    def test_active_publish_failure_can_reconcile_without_duplicate_versions(self):
        s = self.store()
        before = s.activate("mine", context=self.ctx, refs=[])
        values = {"drawing.layout": "A3"}
        with patch.object(s, "_write_state", side_effect=OSError("injected disk failure")):
            with self.assertRaisesRegex(KnowledgeError, "not activated"):
                s.save_default(context=self.ctx, overrides=values, source="explicit")
        self.assertEqual(s.current(context=self.ctx), before)
        self.assertEqual(s.save_default(context=self.ctx, overrides=values, source="explicit")["values"], values)
        self.assertEqual(len(list(self.root.rglob("*.md"))), 1)

    def test_noop_save_changes_no_file_bytes_or_mtime(self):
        s = self.store()
        s.activate("mine", context=self.ctx, refs=[])
        values = {"drawing.layout": "A3"}
        s.save_default(context=self.ctx, overrides=values, source="explicit")
        def capture():
            return {str(p): (p.read_bytes(), p.stat().st_mtime_ns)
                    for p in self.root.rglob("*") if p.is_file()}
        before = capture()
        with patch.object(self.kb, "preference_catalog", side_effect=AssertionError("no-op catalog")), \
             patch.object(self.kb, "register_many", side_effect=AssertionError("no-op register")):
            s.save_default(context=self.ctx, overrides=values, source="explicit")
        self.assertEqual(capture(), before)

    def test_known_applicability_checked_and_other_conditions_preserved(self):
        self.add("wrong-process", conditions={"process": "3d-modeling"})
        with self.assertRaisesRegex(KnowledgeError, "process"):
            self.activate(refs=[{"id": "wrong-process", "version": "1"}])
        self.add("wrong-preset", conditions={"execution_preset": "another"})
        with self.assertRaisesRegex(KnowledgeError, "named preset"):
            self.activate(refs=[{"id": "wrong-preset", "version": "1"}])
        conditions = {"process": "2d-drawing", "review_note": "Owner checks applicability"}
        self.add("reviewed", conditions=conditions)
        snapshot = self.activate(refs=[{"id": "reviewed", "version": "1"}])
        self.assertEqual(snapshot["sources"][0]["conditions"], conditions)

    def test_public_skill_directories_cannot_hold_user_presets(self):
        repository = Path(__file__).resolve().parent.parent
        for folder in ("skills", ".agents/skills", "execution-skills"):
            with self.assertRaisesRegex(KnowledgeError, "distributable"):
                PresetStore(repository / folder / "not-a-user-workspace")

    def test_batch_registration_validates_before_any_registry_change(self):
        self.add("existing")
        before = self.kb.registry_path.read_bytes()
        valid = write_pref(self.root, "valid-new")
        invalid = self.root / "invalid.md"
        invalid.write_text("not a knowledge unit", encoding="utf-8")
        with self.assertRaises(KnowledgeError):
            self.kb.register_many([valid, invalid])
        self.assertEqual(self.kb.registry_path.read_bytes(), before)
        self.assertEqual([unit["id"] for unit in self.kb.preference_catalog()], ["existing"])


if __name__ == "__main__":
    unittest.main()
