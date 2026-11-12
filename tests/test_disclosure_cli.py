"""Local CLI paths for scoped knowledge and progressive detail; no backend calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from eds.cli import dispatch, parser
from eds.install import REPO_ROOT
from eds.knowledge import KnowledgeBase


class DisclosureCLITests(unittest.TestCase):
    def setUp(self):
        temporary_root = REPO_ROOT / "output" / "repository-tests" / "tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temporary_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.kb = KnowledgeBase(self.root)

    def cli(self, *args):
        result = subprocess.run(
            [sys.executable, "-m", "eds", *map(str, args)], cwd=REPO_ROOT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def add(self, uid, kind, body="散热 thermal", **metadata):
        unit = {"id": uid, "version": "1", "type": kind, "title": uid,
                "conditions": {}, "sources": [], "sources_missing": True,
                "relations": [], **metadata}
        path = self.root / f"{uid}.md"
        path.write_text("<!-- eds-knowledge: " + json.dumps(unit, ensure_ascii=False)
                        + " -->\n# " + uid + "\n" + body, encoding="utf-8")
        self.kb.register(path.name)

    def test_route_is_read_only_and_explicit_question_beats_stage(self):
        absent = self.root / "not-created"
        route = self.cli("kb", absent, "route", "--question", "method-selection",
                         "--stage", "execution")
        self.assertIn("method", route["selected_types"])
        self.assertNotIn("preference", route["selected_types"])
        self.assertFalse(absent.exists())
        for kind in ("method", "feedback", "design", "experiment"):
            self.add(kind, kind)
        result = self.cli("kb", self.root, "search", "thermal", "--question",
                          "method-selection", "--stage", "execution")
        self.assertEqual(result["route"], route)
        self.assertIn("method", {item["type"] for item in result["matches"]})
        self.assertTrue(all(item["type"] in route["selected_types"]
                            for item in result["matches"]))

    def test_preference_scope_and_confirmation_survive_cli(self):
        for uid, owner, status, origin in (("mine", "alice", "confirmed", "explicit"),
                                           ("other", "bob", "confirmed", "explicit"),
                                           ("guess", "alice", "candidate", "inferred")):
            self.add(uid, "preference", "drawing 标注",
                     preference_key="drawing.dimension_style", value=uid,
                     scope="user", scope_id=owner, preference_status=status,
                     origin=origin)
        result = self.cli("kb", self.root, "search", "drawing", "--question", "drawing",
                          "--user", "alice")
        self.assertEqual([item["id"] for item in result["matches"]], ["mine"])
        unscoped = self.cli("kb", self.root, "search", "drawing", "--question", "drawing")
        self.assertEqual(unscoped["matches"], [])
        candidates = self.cli("kb", self.root, "search", "drawing", "--type", "preference",
                              "--user", "alice", "--preference-status", "candidate")
        self.assertEqual([item["id"] for item in candidates["matches"]], ["guess"])

    def test_read_expands_only_selected_relation_on_request(self):
        self.add("result", "feedback", "RESULT_BODY_WITH_CONDITIONS")
        self.add("other", "method", "UNRELATED_BODY")
        self.add("method", "method", "q = k A dT / L; k W/(m K)", relations=[
            {"type": "tested_by", "id": "result", "version": "1"},
            {"type": "uses", "id": "other", "version": "1"}])
        compact = self.cli("kb", self.root, "read", "method", "--version", "1")
        self.assertIn("k W/(m K)", compact["content"])
        self.assertNotIn("RESULT_BODY_WITH_CONDITIONS", json.dumps(compact))
        self.assertNotIn("UNRELATED_BODY", json.dumps(compact))
        expanded = self.cli("kb", self.root, "read", "method", "--version", "1",
                            "--depth", "1", "--relation", "tested_by", "--max-units", "3")
        self.assertIn("RESULT_BODY_WITH_CONDITIONS", json.dumps(expanded))
        self.assertNotIn("UNRELATED_BODY", json.dumps(expanded))
        self.assertEqual(expanded["relations_omitted"], 1)
        self.assertFalse(expanded["dependencies_complete"])

    def test_execution_detail_flag_is_explicit_and_does_not_call_backend(self):
        with patch("eds.cli.readiness", return_value={"ready": True}) as check:
            base = ["execution", "cad", "--backend", "binding.json", "--tools", "tools.json"]
            dispatch(parser().parse_args(base))
            self.assertFalse(check.call_args.kwargs["full"])
            dispatch(parser().parse_args([*base, "--full"]))
            self.assertTrue(check.call_args.kwargs["full"])

    def pref(self, uid, value, *, status="confirmed", origin="explicit", **metadata):
        self.add(uid, "preference", metadata.pop("body", "drawing"),
                 preference_key="drawing.style", value=value, scope="user", scope_id="alice",
                 preference_status=status, origin=origin, **metadata)

    def test_project_restrictions_apply_to_results_and_conflict_references(self):
        self.pref("global", "a")
        self.pref("restricted", "b", project="p1")
        unscoped = self.kb.search("drawing", question="drawing", user="alice")
        self.assertEqual([r["id"] for r in unscoped], ["global"])
        self.assertNotIn("restricted", json.dumps(unscoped))
        other = self.kb.search("drawing", question="drawing", user="alice", project="p2")
        self.assertEqual([r["id"] for r in other], ["global"])
        both = self.kb.search("drawing", question="drawing", user="alice", project="p1", limit=1)
        self.assertEqual(len(both), 1)
        self.assertIn("conflict", both[0])
        self.assertEqual({r["id"] for r in both[0]["conflict_refs"]}, {"global", "restricted"})

    def test_supersession_requires_explicit_effective_same_scope_record(self):
        self.pref("original", "a")
        relation = [{"type": "supersedes", "id": "original", "version": "1"}]
        self.pref("candidate", "b", status="candidate", origin="inferred", relations=relation)
        self.assertEqual([r["id"] for r in self.kb.search("drawing", user="alice")], ["original"])
        self.pref("replacement", "c", relations=relation)
        self.assertEqual([r["id"] for r in self.kb.search("drawing", user="alice")], ["replacement"])
        self.assertIn('"value": "a"', self.kb.read("original")["content"])
        self.pref("retirement", "c", status="retired", relations=[
            {"type": "supersedes", "id": "replacement", "version": "1"}])
        self.assertEqual(self.kb.search("drawing", user="alice"), [])

    def test_preference_conflicts_do_not_create_unrelated_search_hits(self):
        self.pref("first", "a", body="needle")
        self.pref("second", "b", body="unrelated word")
        result = self.kb.search("needle", user="alice", question="drawing", limit=1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "first")
        self.assertIn("second", json.dumps(result[0]["conflict_refs"]))
        self.assertEqual(self.kb.search("nonexistent", user="alice", question="method-selection"), [])

    def test_mixed_metadata_and_body_hit_keeps_summary_small(self):
        self.add("method", "method", "thermal body with units", title="thermal method",
                 conditions={"thermal": "HUGE_CONDITIONS" * 1000},
                 private_note="UNRELATED_METADATA" * 1000)
        result = self.kb.search("thermal", question="method-selection")[0]
        self.assertNotIn("HUGE_CONDITIONS", json.dumps(result))
        self.assertNotIn("UNRELATED_METADATA", json.dumps(result))
        self.assertTrue(result["conditions_available"])
        self.assertIn("thermal body with units", result["snippet"])
        self.assertIn("HUGE_CONDITIONS", self.kb.read("method")["content"])

    def test_route_primary_order_explicit_type_and_no_cross_collection_fallback(self):
        self.add("a-feedback", "feedback", "thermal")
        self.add("z-method", "method", "thermal lengthy method background")
        self.add("design", "design", "exclusive-design")
        results = self.kb.search("thermal", question="method-selection", stage="delivery")
        self.assertEqual(results[0]["type"], "method")
        self.assertEqual(self.kb.search("exclusive-design", question="method-selection"), [])
        result = self.cli("kb", self.root, "search", "exclusive-design", "--question", "method-selection",
                          "--type", "design")
        self.assertEqual(result["route"]["selected_types"], ["design"])
        self.assertEqual([item["id"] for item in result["matches"]], ["design"])

    def test_invalid_preferences_and_expansion_bounds_fail_before_use(self):
        from eds.knowledge import KnowledgeError
        with self.assertRaises(KnowledgeError):
            self.pref("unconfirmed", "a", origin="inferred")
        self.add("method", "method")
        for arguments in ({"depth": 4}, {"depth": -1}, {"max_units": 0}, {"max_units": 101}):
            with self.assertRaises(KnowledgeError):
                self.kb.read("method", **arguments)
        for filters in ({"question": "guess"}, {"stage": "guess"}, {"preference_status": "guess"}):
            with self.assertRaises(KnowledgeError):
                self.kb.search("thermal", **filters)

    def test_drawing_and_modeling_preferences_use_question_scope(self):
        self.pref("drawing", "a", question="drawing")
        self.pref("modeling", "b", question="cad-modeling")
        result = self.kb.search("drawing", question="drawing", stage="discussion", user="alice")
        self.assertEqual([item["id"] for item in result], ["drawing"])
        self.assertNotIn("conflict", result[0])
        result = self.kb.search("drawing", question="cad-modeling", user="alice")
        self.assertEqual([item["id"] for item in result], ["modeling"])


if __name__ == "__main__":
    unittest.main()
