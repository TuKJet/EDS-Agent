import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from eds.graph import KnowledgeGraph, GraphError, runtime_status
from eds.knowledge import KnowledgeBase


def make_unit(path, uid, body="gear housing thermal design", relations=None, kind="method", version="1", **extra):
    meta = {"id": uid, "version": str(version), "type": kind, "title": uid, "date": "2026-11-10",
            "attribution": "test", "sources": [{"uri": "fixture.md", "locator": "body"}],
            "conditions": {}, "relations": relations or [], **extra}
    path.write_text("<!-- eds-knowledge: " + json.dumps(meta, ensure_ascii=False) + " -->\n" + body, encoding="utf-8")


def make_experience(root, uid="iteration", evaluations=None):
    """Create a valid central experience snapshot plus its registered projection."""
    evidence = [{"ref": "evidence@1", "kind": "evidence", "details": {"observation": "measured"}}]
    record = {"schema": "eds-experience/v1", "id": uid, "version": 1, "study_id": "study",
              "assessment_ref": "assessment@1", "title": uid, "context": {},
              "actions": {"run_statuses": [], "runs": []}, "observations": {"entities": evidence},
              "analysis": {}, "guidance": {"status": "unverified"}, "method_evaluations": evaluations or [],
              "relations": [], "reuse": {}, "provenance": {"source": "test"}}
    snapshot = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    source = root / "iterations" / f"{uid}.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(snapshot.encode("utf-8"))
    digest = hashlib.sha256(snapshot.encode()).hexdigest()
    meta = {"id": uid, "version": "1", "type": "feedback", "title": uid, "date": "2026-11-10",
            "attribution": "test", "sources": [{"uri": source.relative_to(root).as_posix(), "locator": "$", "sha256": digest}],
            "conditions": {}, "relations": [], "data_schema": "eds-experience/v1"}
    md = root / f"{uid}.md"
    md.write_text("<!-- eds-knowledge: " + json.dumps(meta, ensure_ascii=False) + " -->\niteration", encoding="utf-8")
    return md, source


def require_graphqlite(test):
    try:
        import graphqlite  # noqa: F401
    except ImportError:
        test.skipTest("graphqlite not installed")


class GraphTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parent.parent / "output" / "repository-tests" / "tmp"
        scratch.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=scratch, prefix="graph-core-")
        self.root = Path(self.tmp.name)
        self.kb = KnowledgeBase(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_runtime_missing_is_read_only(self):
        absent = self.root / "absent"
        with patch("eds.graph.graphqlite", None):
            graph = KnowledgeGraph(absent)
            self.assertFalse(graph.status()["exists"])
            with self.assertRaises(GraphError):
                graph.sync()
            self.assertFalse(absent.exists())

    def test_graphqlite_projection_and_relation_recall(self):
        require_graphqlite(self)
        a = self.root / "a.md"; b = self.root / "b.md"
        make_unit(a, "a", body="root surface")
        make_unit(b, "b", body="hidden method", relations=[{"id": "a", "version": "1", "type": "supports"}])
        self.kb.register(a); self.kb.register(b); self.kb.sync()
        graph = KnowledgeGraph(self.kb); result = graph.sync()
        self.assertEqual(result["indexed"], 2)
        found = graph.search("root surface", depth=1)
        self.assertEqual({item["id"] for item in found["matches"]}, {"a", "b"})
        before = hashlib.sha256(graph.path.read_bytes()).hexdigest()
        self.assertFalse(graph.status()["stale"])
        graph.search("root")
        self.assertEqual(before, hashlib.sha256(graph.path.read_bytes()).hexdigest())

    def _build(self):
        require_graphqlite(self)
        self.kb.sync()
        graph = KnowledgeGraph(self.kb)
        graph.sync(force=True)
        return graph

    def test_project_and_domain_scope_cannot_cross_bridge(self):
        make_unit(self.root / "a.md", "a", body="rootuniquescope", relations=[{"id": "b", "version": "1", "type": "supports"}], project="p1", domain="cae")
        make_unit(self.root / "b.md", "b", body="bridgeonly", relations=[{"id": "c", "version": "1", "type": "supports"}], project="p2", domain="other")
        make_unit(self.root / "c.md", "c", body="hiddenresult", project="p1", domain="cae")
        for name in "abc": self.kb.register(self.root / f"{name}.md")
        result = self._build().search("rootuniquescope", project="p1", domain="cae", depth=2)
        ids = {item["id"] for item in result["matches"]}
        self.assertIn("a", ids)
        self.assertNotIn("c", ids)

    def test_question_route_uses_selected_types_not_exact_question_metadata(self):
        make_unit(self.root / "m.md", "m", body="uniquequestionfeedback", kind="feedback", question="design")
        self.kb.register(self.root / "m.md")
        result = self._build().search("uniquequestionfeedback", question="method-selection")
        self.assertIn("m", {item["id"] for item in result["matches"]})

    def test_parallel_supports_and_contradicts_edges_are_retained_with_direction(self):
        make_unit(self.root / "a.md", "a", body="parallel seed", relations=[
            {"id": "b", "version": "1", "type": "supports"},
            {"id": "b", "version": "1", "type": "contradicts"}])
        make_unit(self.root / "b.md", "b", body="parallel target")
        self.kb.register(self.root / "a.md"); self.kb.register(self.root / "b.md")
        result = self._build().search("parallel seed", depth=1)
        paths = [path for item in result["matches"] for path in item.get("paths", [])]
        relations = {step["relation"] for path in paths for step in path}
        self.assertEqual(relations, {"supports", "contradicts"})
        self.assertTrue(all(path[0]["from"] for path in paths))
        restricted = self._build().search("parallel seed", depth=1, relation_types={"supports"})
        restricted_relations = {step["relation"] for item in restricted["matches"] for path in item.get("paths", []) for step in path}
        self.assertEqual(restricted_relations, {"supports"})

    def test_unicode_quote_newline_identity_and_relation_are_parameterized(self):
        odd_id = '齿轮"\n甲'
        make_unit(self.root / "odd.md", odd_id, body="oddidentityseed", relations=[
            {"id": "目标\n\"乙", "version": "1", "type": "支持\"\n关系"}])
        make_unit(self.root / "target.md", "目标\n\"乙", body="oddtarget")
        self.kb.register(self.root / "odd.md"); self.kb.register(self.root / "target.md")
        result = self._build().search("oddidentityseed", depth=1)
        self.assertIn(odd_id, {item["id"] for item in result["matches"]})
        paths = [path for item in result["matches"] for path in item.get("paths", [])]
        self.assertIn("支持\"\n关系", {step["relation"] for path in paths for step in path})

    def test_node_budget_is_hard_and_reports_truncation(self):
        relations = [{"id": f"n{i}", "version": "1", "type": "supports"} for i in range(5)]
        make_unit(self.root / "seed.md", "seed", body="rootuniquebudget", relations=relations)
        for i in range(5): make_unit(self.root / f"n{i}.md", f"n{i}", body=f"neighbor{i}")
        self.kb.register(self.root / "seed.md")
        for i in range(5): self.kb.register(self.root / f"n{i}.md")
        result = self._build().search("rootuniquebudget", depth=1, max_nodes=2)
        self.assertLessEqual(len(result["matches"]), 2)
        self.assertTrue(result["truncated"])

    def test_shared_seeds_keep_paths_within_depth_and_without_cycles(self):
        for uid, target in (("a", "b"), ("b", "c"), ("c", "a")):
            path = self.root / f"{uid}.md"
            make_unit(path, uid, body="sharedseed", relations=[{"id": target, "version": "1", "type": "supports"}])
            self.kb.register(path)
        graph = self._build()
        for depth in (1, 2):
            result = graph.search("sharedseed", depth=depth)
            for match in result["matches"]:
                for path in match["paths"]:
                    self.assertLessEqual(len(path), depth)
                    self.assertEqual(len({step["via"] for step in path}), len(path))

    def test_missing_runtime_or_graph_fails_before_zero_hit_fallback(self):
        graph = KnowledgeGraph(self.root / "absent")
        with self.assertRaises(GraphError):
            graph.search("no such terms")
        with patch("eds.graph.graphqlite", None):
            with self.assertRaises(GraphError):
                graph.search("no such terms")

    def test_corrupt_schema_is_reported_and_force_sync_recovers(self):
        make_unit(self.root / "a.md", "a", body="corruption seed"); self.kb.register(self.root / "a.md")
        graph = self._build()
        graph.path.write_bytes(b"not sqlite")
        status = graph.status()
        self.assertTrue(status.get("error") or status.get("stale"))
        graph.sync(force=True)
        self.assertFalse(graph.status()["stale"])

    def test_valid_sqlite_with_corrupt_graph_meta_is_rejected_and_rebuilt(self):
        make_unit(self.root / "a.md", "a", body="metacorruption seed"); self.kb.register(self.root / "a.md")
        graph = self._build()
        with closing(sqlite3.connect(graph.path)) as connection:
            connection.execute("UPDATE graph_meta SET value=? WHERE key='schema'", ("bad-schema",))
            connection.commit()
        status = graph.status()
        self.assertTrue(status.get("error") or status.get("stale"))
        graph.sync(force=True)
        self.assertFalse(graph.status()["stale"])

    def test_idempotency_delete_and_failed_rebuild_preserve_previous_graph(self):
        make_unit(self.root / "a.md", "a", body="stable seed"); self.kb.register(self.root / "a.md")
        graph = self._build(); before = hashlib.sha256(graph.path.read_bytes()).hexdigest()
        self.assertFalse(graph.sync()["rebuilt"])
        self.assertEqual(before, hashlib.sha256(graph.path.read_bytes()).hexdigest())
        (self.root / "a.md").unlink()
        with self.assertRaises(Exception):
            graph.sync(force=True)
        self.assertEqual(before, hashlib.sha256(graph.path.read_bytes()).hexdigest())
        make_unit(self.root / "a.md", "a", body="stable seed"); self.kb.register(self.root / "a.md"); self.kb.sync()
        with patch.object(graph, "_build", side_effect=RuntimeError("fixture failure")):
            with self.assertRaises(RuntimeError): graph.sync(force=True)
        self.assertEqual(before, hashlib.sha256(graph.path.read_bytes()).hexdigest())

    def test_fixed_version_missing_reference_is_unresolved_not_latest(self):
        make_unit(self.root / "a.md", "a", body="rootuniqueversion", relations=[{"id": "b", "version": "1", "type": "supports"}])
        make_unit(self.root / "b.md", "b", body="otherversion", version="2")
        self.kb.register(self.root / "a.md"); self.kb.register(self.root / "b.md")
        result = self._build().search("rootuniqueversion", depth=1)
        self.assertNotIn("b", {item["id"] for item in result["matches"]})
        self.assertTrue(result.get("unresolved_refs"))

    def test_unresolved_reference_cannot_bridge_two_registered_units(self):
        make_unit(self.root / "a.md", "a", body="rootuniquemissing", relations=[{"id": "ghost", "version": "1", "type": "supports"}])
        make_unit(self.root / "c.md", "c", body="unrelatedunit", relations=[{"id": "ghost", "version": "1", "type": "supports"}])
        self.kb.register(self.root / "a.md"); self.kb.register(self.root / "c.md")
        result = self._build().search("rootuniquemissing", depth=2)
        self.assertNotIn("c", {item["id"] for item in result["matches"]})
        self.assertTrue(result.get("unresolved_refs"))

    def test_preference_units_and_links_are_absent_from_projection(self):
        make_unit(self.root / "a.md", "a", body="ordinary seed", relations=[{"id": "pref", "version": "1", "type": "related_to"}])
        make_unit(self.root / "pref.md", "pref", body="private drawing preference", kind="preference",
                  preference_key="drawing.style", value="iso", scope="user", scope_id="u", preference_status="confirmed", origin="explicit")
        self.kb.register(self.root / "a.md"); self.kb.register(self.root / "pref.md")
        result = self._build().search("ordinary seed", depth=1)
        self.assertNotIn("pref", {item["id"] for item in result["matches"]})
        with closing(sqlite3.connect(KnowledgeGraph(self.kb).path.as_uri() + "?mode=ro", uri=True)) as connection:
            import graphqlite
            graphqlite.load(connection)
            rows = json.loads(connection.execute("SELECT cypher(?)", ("MATCH (n:EDSNode) RETURN n.id AS id",)).fetchone()[0])
        self.assertNotIn("pref", {row.get("id") for row in rows})

    def test_experience_evaluations_keep_positive_negative_full_fields_and_tamper_stales(self):
        evaluations = []
        for effect, ref in (("improved", "method-a@1"), ("degraded", "method-b@1")):
            evaluations.append({"knowledge_ref": ref, "product_features": {"feature": "fin"}, "conditions": {"load": 2},
                                "parameter_changes": {"mesh": 0.5}, "comparison": {"baseline": "old"}, "effect": effect,
                                "evidence_origin": "runtime", "evidence_refs": ["evidence@1"], "limitations": ["bounded"]})
        md, source = make_experience(self.root, evaluations=evaluations)
        self.kb.register(md)
        graph = self._build()
        result = graph.search("iteration", depth=1)
        values = [item for match in result["matches"] for item in match.get("evaluations", [])]
        self.assertEqual({item["effect"] for item in values}, {"improved", "degraded"})
        self.assertEqual(values[0]["parameter_changes"], {"mesh": 0.5})
        source.write_text(source.read_text(encoding="utf-8").replace('"title":"iteration"', '"title":"tampered"'), encoding="utf-8")
        self.assertTrue(graph.status().get("stale") or graph.status().get("error"))

    def test_selected_experience_hash_catches_same_size_tamper_with_restored_mtime(self):
        evaluation = {"knowledge_ref": "method-a@1", "product_features": {"feature": "fin"}, "conditions": {"load": 2},
                      "parameter_changes": {"mesh": 0.5}, "comparison": {"baseline": "old"}, "effect": "improved",
                      "evidence_origin": "runtime", "evidence_refs": ["evidence@1"], "limitations": ["bounded"]}
        md, source = make_experience(self.root, evaluations=[evaluation])
        self.kb.register(md)
        graph = self._build()
        original_stat = source.stat()
        tampered = source.read_bytes().replace(b'"effect":"improved"', b'"effect":"degraded"')
        self.assertEqual(len(tampered), original_stat.st_size)
        source.write_bytes(tampered)
        os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        with self.assertRaises(GraphError):
            graph.search("iteration", depth=1)
