import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from eds.knowledge import KnowledgeBase, KnowledgeError


def unit(path, uid, version="1", kind="method", relations=None, body="层流模型 压力计算 pressure drop. Re = rho U h / mu; rho kg/m3, U m/s, h m, mu Pa s.", **extra):
    metadata = {"id": uid, "version": version, "type": kind, "title": uid,
                "date": "2026-11-02", "attribution": "synthetic_fixture",
                "sources": [{"uri": "fixture.md", "locator": "equation 1"}],
                "conditions": {"flow": "laminar", "unit": "m"}, "relations": relations or [], **extra}
    path.write_text("<!-- eds-knowledge: " + json.dumps(metadata, ensure_ascii=False) + " -->\n\n" + body + "\n", encoding="utf-8")
    return metadata


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parent.parent / ".test-tmp"
        test_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root, prefix="knowledge-")
        self.root = Path(self.temp.name)
        self.kb = KnowledgeBase(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def add(self, name="method", **kwargs):
        path = self.root / (name + ".md")
        unit(path, name, **kwargs)
        self.kb.register(path)
        return path

    def test_status_and_constructor_do_not_create_workspace(self):
        root = self.root / "absent"
        kb = KnowledgeBase(root)
        self.assertFalse(kb.status()["available"])
        self.assertFalse(root.exists())

    def test_bilingual_ngram_recall_and_original_formula(self):
        self.add()
        for query in ("压力 层流", "层流 pressure", "pressure drop", "流"):
            with self.subTest(query=query):
                self.assertEqual(self.kb.search(query)[0]["id"], "method")
        item = self.kb.read("method", "1")
        self.assertIn("Re = rho U h / mu", item["content"])
        self.assertEqual(item["metadata"]["conditions"]["unit"], "m")

    def test_fields_filters_and_source_locations(self):
        self.add(domain="cae", project="demo", problem="热变形", body="Some other body")
        result = self.kb.search("热变形", domain="cae", project="demo")[0]
        self.assertIn("problem", result["matched_fields"])
        self.assertTrue(result["locators"])
        self.assertEqual(result["sources"][0]["locator"], "equation 1")
        self.assertEqual(self.kb.search("热变形", type="feedback"), [])
        self.assertTrue(self.kb.search("laminar"))
        self.assertTrue(self.kb.search("fixture"))

    def test_read_defaults_to_locator_only_and_expands_on_request(self):
        self.add("a", relations=[{"type": "uses", "id": "b", "version": "1"}])
        self.add("b", body="dependency body")
        compact = self.kb.read("a")
        self.assertNotIn("content", compact["dependencies"][0])
        self.assertIn("dependency body", self.kb.read("a", depth=1)["dependencies"][0]["content"])

    def test_route_is_question_first_and_does_not_fallback_to_all_types(self):
        route = self.kb.knowledge_route(question="drawing", stage="discussion")
        self.assertEqual(route["selected_types"][0], "preference")
        self.assertNotIn("method", route["selected_types"])
        with self.assertRaises(KnowledgeError):
            self.kb.knowledge_route(question="unknown")
        self.assertEqual(self.kb.knowledge_route()["selected_types"], None)

    def test_search_routes_by_question_and_projects_summary_metadata(self):
        self.add("design-unit", kind="design", question="design", body="thermal bracket design")
        self.add("method-unit", kind="method", question="method-selection", body="thermal bracket design")
        results = self.kb.search("thermal bracket", question="design")
        self.assertEqual([item["id"] for item in results], ["design-unit"])
        self.assertNotIn("content", results[0])
        self.assertTrue(results[0]["conditions_available"])

    def test_confirmed_preference_conflict_is_visible_beyond_limit(self):
        for name, value in (("pref-a", "iso"), ("pref-b", "ansi")):
            path = self.root / (name + ".md")
            unit(path, name, kind="preference", preference_key="drawing.style", value=value,
                 scope="project", scope_id="p1", preference_status="confirmed", origin="explicit")
            self.kb.register(path)
        results = self.kb.search("drawing.style", type="preference", project="p1", limit=1)
        self.assertEqual(len(results), 1)
        self.assertTrue(all(item.get("conflict") for item in results))
        self.assertEqual(len(results[0]["conflict_refs"]), 2)

    def test_preference_requires_explicit_confirmation_and_scope(self):
        path = self.root / "pref.md"
        unit(path, "pref", kind="preference", preference_key="drawing.dimension_style", value="iso",
             scope="user", scope_id="u1", preference_status="candidate", origin="inferred")
        self.kb.register(path)
        self.assertEqual(self.kb.search("dimension_style", type="preference", user="u1"), [])
        unit(path, "pref", kind="preference", preference_key="drawing.dimension_style", value="iso",
             scope="user", scope_id="u1", preference_status="confirmed", origin="explicit")
        self.kb.sync()
        self.assertEqual(self.kb.search("dimension_style", type="preference", user="u1")[0]["id"], "pref")
        self.assertEqual(self.kb.search("dimension_style", type="preference", user="u2"), [])

    def test_cycle_and_diamond_dependencies_expand_once(self):
        self.add("a", relations=[{"type": "uses", "id": "b", "version": "1"}])
        self.add("b", relations=[{"type": "uses", "id": "a", "version": "1"}])
        result = self.kb.read("a", depth=1)
        self.assertEqual(result["dependencies"][0]["id"], "b")
        self.assertTrue(result["dependencies"][0]["dependencies"][0]["already_included"])

    def test_missing_version_never_resolves_to_latest(self):
        self.add("a", relations=[{"type": "uses", "id": "b", "version": "1"}])
        self.add("b", version="2")
        dependency = self.kb.read("a")["dependencies"][0]
        self.assertEqual(dependency["version"], "1")
        self.assertTrue(dependency["missing"])

    def test_multiple_versions_require_explicit_version(self):
        self.add("a")
        path = self.root / "a-new.md"
        unit(path, "a", version="2")
        self.kb.register(path)
        with self.assertRaises(KnowledgeError):
            self.kb.read("a")
        self.assertEqual(self.kb.read("a", "1")["version"], "1")

    def test_manual_edit_requires_sync_and_removes_old_terms(self):
        path = self.add(body="oldtermonly")
        path.write_text(path.read_text(encoding="utf-8").replace("oldtermonly", "newtermonly"), encoding="utf-8")
        self.assertFalse(self.kb.status()["consistent"])
        with self.assertRaises(KnowledgeError):
            self.kb.search("oldtermonly")
        self.kb.sync()
        self.assertEqual(self.kb.search("oldtermonly"), [])
        self.assertTrue(self.kb.search("newtermonly"))

    def test_external_delete_cleans_index_and_marks_gap(self):
        path = self.add("a", body="uniqueremoved")
        self.add("b", relations=[{"type": "uses", "id": "a", "version": "1"}])
        path.unlink()
        status = self.kb.sync()
        self.assertEqual(status["missing_files"], ["a.md"])
        self.assertFalse(status["complete"])
        self.assertEqual(self.kb.search("uniqueremoved"), [])
        self.assertTrue(self.kb.read("b")["dependencies"][0]["missing"])

    def test_reappeared_missing_source_requires_sync(self):
        path = self.add("method")
        path.unlink()
        self.kb.sync()
        unit(path, "method")
        with self.assertRaises(KnowledgeError):
            self.kb.search("pressure")
        self.kb.sync()
        self.assertTrue(self.kb.search("pressure"))

    def test_invalid_registration_does_not_pollute_registry(self):
        self.add("good")
        before = self.kb.registry_path.read_bytes()
        bad = self.root / "bad.md"
        bad.write_text("unstructured paper", encoding="utf-8")
        with self.assertRaises(KnowledgeError):
            self.kb.register(bad)
        self.assertEqual(before, self.kb.registry_path.read_bytes())
        unit(bad, "good")
        with self.assertRaises(KnowledgeError):
            self.kb.register(bad)
        self.assertEqual(before, self.kb.registry_path.read_bytes())

    def test_incremental_sync_preserves_unmodified_rows_and_noop_file(self):
        changed = self.add("a")
        self.add("b")
        with closing(sqlite3.connect(self.kb.db_path)) as db, db:
            before = db.execute("SELECT rowid FROM units WHERE id='b'").fetchone()[0]
        unit(changed, "a", body="different data")
        result = self.kb.sync()
        self.assertEqual(result["changes"]["updated"], 1)
        with closing(sqlite3.connect(self.kb.db_path)) as db, db:
            after = db.execute("SELECT rowid FROM units WHERE id='b'").fetchone()[0]
        self.assertEqual(before, after)
        prior_bytes = self.kb.db_path.read_bytes()
        self.kb.sync()
        self.assertEqual(prior_bytes, self.kb.db_path.read_bytes())

    def test_corrupted_database_rebuilds_from_markdown(self):
        self.add("a")
        self.kb.db_path.write_bytes(b"not sqlite at all")
        self.assertFalse(self.kb.status()["available"])
        self.kb.rebuild()
        self.assertEqual(self.kb.search("pressure")[0]["id"], "a")

    def test_failed_rebuild_preserves_old_database(self):
        self.add("a")
        prior = self.kb.db_path.read_bytes()
        with patch("eds.knowledge.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                self.kb.rebuild()
        self.assertEqual(prior, self.kb.db_path.read_bytes())
        self.assertTrue(self.kb.search("pressure"))

    def test_registry_exact_path_set_not_just_count(self):
        self.add("a")
        unit(self.root / "b.md", "b")
        self.kb.registry_path.write_text(json.dumps({"documents": ["b.md"]}), encoding="utf-8")
        self.assertFalse(self.kb.status()["consistent"])
        self.kb.sync()
        self.assertEqual(self.kb.search("pressure")[0]["id"], "b")

    def test_bad_index_version_requires_rebuild(self):
        self.add()
        with closing(sqlite3.connect(self.kb.db_path)) as db, db:
            db.execute("UPDATE meta SET value='unsupported' WHERE key='index_version'")
        self.assertFalse(self.kb.status()["available"])
        self.kb.sync()
        self.assertTrue(self.kb.status()["available"])

    def test_concurrent_registration_keeps_every_document(self):
        paths = []
        for i in range(8):
            path = self.root / f"unit{i}.md"
            unit(path, str(i))
            paths.append(path)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda p: KnowledgeBase(self.root).register(p), paths))
        self.assertEqual(self.kb.status()["registered"], 8)
        self.assertEqual(self.kb.status()["indexed"], 8)

    def test_registry_path_escape_rejected(self):
        self.kb.registry_path.write_text('{"documents":["../outside.md"]}', encoding="utf-8")
        with self.assertRaises(KnowledgeError):
            self.kb.sync()

    def test_malformed_metadata_is_rejected(self):
        for extra in ({"id": ""}, {"sources": [{}]}, {"relations": [{"id": "x"}]}, {"conditions": None}):
            path = self.root / "bad.md"
            unit(path, "bad", **extra)
            with self.subTest(extra=extra), self.assertRaises(KnowledgeError):
                self.kb.register(path)

    def test_nonfinite_json_and_malformed_registry_rejected(self):
        path = self.root / "bad.md"
        unit(path, "bad", conditions={"load": float("nan")})
        with self.assertRaises(KnowledgeError):
            self.kb.register(path)
        self.kb.registry_path.write_text("[]", encoding="utf-8")
        with self.assertRaises(KnowledgeError):
            self.kb.sync()

    def test_unregistered_files_are_never_indexed(self):
        self.add("a")
        unit(self.root / "private.md", "private", body="secretword")
        self.kb.sync()
        self.assertEqual(self.kb.search("secretword"), [])

    def test_empty_punctuation_and_sql_like_query_are_safe(self):
        self.add()
        self.assertEqual(self.kb.search("!!! () * %"), [])
        self.assertEqual(self.kb.search(""), [])
        self.kb.search("\" OR 1=1; DROP TABLE units; --")
        self.assertEqual(self.kb.status()["indexed"], 1)

    def test_rebuild_reproduces_queries_and_relations(self):
        self.add("a", relations=[{"type": "uses", "id": "b", "version": "1"}])
        self.add("b", kind="feedback")
        before = [(r["id"], r["version"]) for r in self.kb.search("层流 pressure")]
        self.kb.db_path.unlink()
        self.kb.rebuild()
        self.assertEqual(before, [(r["id"], r["version"]) for r in self.kb.search("层流 pressure")])
        self.assertEqual(self.kb.read("a")["dependencies"][0]["id"], "b")

    def test_unicode_bom_and_crlf_hash_are_stable(self):
        path = self.add()
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes().replace(b"\n", b"\r\n"))
        self.kb.sync()
        self.assertTrue(self.kb.status()["consistent"])
        self.assertTrue(self.kb.search("pressure"))

    def test_unregister_preserves_markdown_and_cleans_hits(self):
        path = self.add()
        result = self.kb.unregister(path)
        self.assertTrue(path.is_file())
        self.assertFalse(result["registered"])
        self.assertEqual(self.kb.search("pressure"), [])

    def test_failed_incremental_transaction_preserves_old_index(self):
        path = self.add()
        previous = self.kb.db_path.read_bytes()
        unit(path, "method", body="changed content")
        with patch.object(KnowledgeBase, "_insert", side_effect=RuntimeError("injected failure")):
            with self.assertRaises(RuntimeError):
                self.kb.sync()
        self.assertEqual(previous, self.kb.db_path.read_bytes())
        self.assertFalse(self.kb.status()["consistent"])
        self.kb.sync()
        self.assertTrue(self.kb.search("changed"))

    def test_read_detects_edit_after_initial_freshness_check(self):
        path = self.add()
        original = self.kb._light_health
        calls = []

        def initial_check_then_edit(*, check_sources):
            health = original(check_sources=check_sources)
            calls.append(1)
            if len(calls) == 1:
                unit(path, "method", body="edited during read")
            return health

        with patch.object(self.kb, "_light_health", side_effect=initial_check_then_edit):
            with self.assertRaises(KnowledgeError):
                self.kb.read("method")

    def test_normal_reads_do_not_run_full_database_audit(self):
        self.add("method")
        self.add("other", body="unrelated content")
        statements = []
        connect = self.kb._connect

        def traced_connect(*args, **kwargs):
            connection = connect(*args, **kwargs)
            connection.set_trace_callback(statements.append)
            return connection

        with patch.object(self.kb, "_check_database", side_effect=AssertionError("deep audit in normal read")), \
                patch.object(self.kb, "_connect", side_effect=traced_connect):
            self.assertEqual(self.kb.read("method")["id"], "method")
            self.assertTrue(self.kb.search("pressure"))
        self.assertNotIn("quick_check", " ".join(statements).lower())
        self.assertNotIn("select path from units", " ".join(statements).lower())

    def test_method_search_does_not_load_preference_graph_or_deep_sql_checks(self):
        self.add("method")
        self.add("pref", kind="preference", body="drawing preference", preference_key="style",
                 scope="user", scope_id="u1", preference_status="confirmed", value="drawing",
                 origin="explicit")
        with patch.object(self.kb, "_check_database", side_effect=AssertionError("deep audit")), \
                patch.object(self.kb, "_superseded_preferences", side_effect=AssertionError("preference graph")):
            self.assertTrue(self.kb.search("pressure", type="method"))
            self.assertTrue(self.kb.search("pressure", question="method-selection", user="u1"))

    def test_read_verifies_selected_source_with_one_bytes_read(self):
        path = self.add("method")
        original = Path.read_bytes
        reads = []

        def counted(target):
            if target == path:
                reads.append(1)
            return original(target)

        with patch.object(Path, "read_bytes", counted):
            self.assertEqual(self.kb.read("method")["id"], "method")
        self.assertEqual(reads, [1])

    def test_legacy_index_without_stats_preserves_missing_source_status(self):
        self.add("method")
        missing = self.add("missing")
        missing.unlink()
        self.kb.sync()
        with closing(sqlite3.connect(self.kb.db_path)) as db, db:
            db.execute("DELETE FROM meta WHERE key='source_stats'")
        with patch.object(self.kb, "_check_database", side_effect=AssertionError("legacy deep audit")):
            result = self.kb.search("pressure")
        self.assertEqual(result[0]["index_status"], {"complete": False, "missing_files": ["missing.md"]})

    def test_read_uses_source_relations_when_derived_rows_need_maintenance(self):
        self.add("a", relations=[{"type": "uses", "id": "b", "version": "1"}])
        self.add("b")
        with closing(sqlite3.connect(self.kb.db_path)) as db, db:
            db.execute("DELETE FROM relations")
        self.assertEqual(self.kb.read("a")["dependencies"][0]["id"], "b")
        self.assertFalse(self.kb.status()["available"])

    def test_search_rejects_forged_cached_content(self):
        self.add("method")
        with closing(sqlite3.connect(self.kb.db_path)) as db, db:
            db.execute("UPDATE units SET content=content || ' forged search cache'")
        with self.assertRaises(KnowledgeError):
            self.kb.search("pressure")

    def test_read_allows_unrelated_edit_but_selected_edit_requires_sync(self):
        self.add("method")
        other = self.add("other", body="unrelated content")
        other.write_text(other.read_text(encoding="utf-8").replace("unrelated", "edited"), encoding="utf-8")
        self.assertEqual(self.kb.read("method")["id"], "method")
        selected = self.root / "method.md"
        selected.write_text(selected.read_text(encoding="utf-8").replace("pressure", "editedpressure"), encoding="utf-8")
        with self.assertRaises(KnowledgeError):
            self.kb.read("method")

    def test_search_detects_registered_edit_until_sync(self):
        path = self.add("method")
        path.write_text(path.read_text(encoding="utf-8").replace("pressure", "newterm"), encoding="utf-8")
        with self.assertRaises(KnowledgeError):
            self.kb.search("pressure")
        self.kb.sync()
        self.assertEqual(self.kb.search("pressure"), [])
        self.assertTrue(self.kb.search("newterm"))

    def test_multiline_metadata_locator_covers_actual_metadata(self):
        path = self.root / "multiline.md"
        meta = unit(path, "multiline", problem="热应力", body="body")
        path.write_text("<!-- eds-knowledge: " + json.dumps(meta, ensure_ascii=False, indent=2) + " -->\nbody\n", encoding="utf-8")
        self.kb.register(path)
        hit = self.kb.search("热应力")[0]
        location = next(item for item in hit["locators"] if item["field"] == "problem")
        original_lines = path.read_text(encoding="utf-8").splitlines()
        located_text = "\n".join(original_lines[location["line_start"] - 1:location["line_end"]])
        self.assertIn("热应力", located_text)

    def test_dependency_depth_is_bounded_and_explicit(self):
        documents = []
        for i in range(40):
            path = self.root / f"chain-{i}.md"
            relation = [{"type": "uses", "id": str(i + 1), "version": "1"}] if i < 39 else []
            unit(path, str(i), relations=relation)
            documents.append(path.name)
        self.kb.registry_path.write_text(json.dumps({"documents": documents}), encoding="utf-8")
        self.kb.sync()
        result = self.kb.read("0", depth=3)
        self.assertFalse(result["dependencies_complete"])
        self.assertIn("not_expanded", json.dumps(result))

    def test_shipped_sources_are_readable_and_not_knowledge_units(self):
        import shutil
        fixture_root = Path(__file__).resolve().parent.parent / "examples" / "knowledge"
        for source in fixture_root.glob("*.md"):
            shutil.copy2(source, self.root / source.name)
        for name in ("method-fluid-gap", "experiment-gap-sweep", "feedback-gap-laminar"):
            self.kb.register(name + ".md")
        self.assertEqual(self.kb.status()["indexed"], 3)
        self.assertTrue(self.kb.search("层流"))
        self.assertTrue(self.kb.search("pressure"))
        result = self.kb.read("method-fluid-gap", "1")
        self.assertIn("Delta_p = 12", result["content"])
        for source in result["sources"]:
            self.assertTrue((self.root / source["uri"]).is_file())
        with self.assertRaises(KnowledgeError):
            self.kb.register("synthetic-source.md")

    def test_deleted_search_rows_are_unavailable_and_sync_recovers(self):
        self.add()
        with closing(sqlite3.connect(self.kb.db_path)) as db, db:
            db.execute("DELETE FROM unit_search")
        self.assertFalse(self.kb.status()["available"])
        self.assertFalse(self.kb.status()["complete"])
        self.assertEqual(self.kb.sync()["changes"]["rebuilt"], 1)
        self.assertTrue(self.kb.search("pressure"))

    def test_deleted_relations_are_unavailable_and_rebuild_recovers(self):
        self.add("a", relations=[{"type": "uses", "id": "b", "version": "1"}])
        self.add("b")
        with closing(sqlite3.connect(self.kb.db_path)) as db, db:
            db.execute("DELETE FROM relations")
        self.assertFalse(self.kb.status()["available"])
        self.kb.rebuild()
        self.assertEqual(self.kb.read("a")["dependencies"][0]["id"], "b")

    def test_derived_content_and_metadata_corruption_detected(self):
        self.add()
        corruptions = (
            "UPDATE units SET content=content || ' forged result'",
            "UPDATE units SET metadata_json='{}'",
            "UPDATE units SET title='forged title'",
            "UPDATE unit_search SET lexemes='forgedtoken' WHERE field='content'",
            "UPDATE unit_search SET text='forged field' WHERE field='conditions'",
            "DELETE FROM unit_search WHERE field='conditions'",
        )
        for sql in corruptions:
            with self.subTest(sql=sql):
                with closing(sqlite3.connect(self.kb.db_path)) as db, db:
                    db.execute(sql)
                self.assertFalse(self.kb.status()["available"])
                self.kb.sync()
                self.assertTrue(self.kb.status()["complete"])
                self.assertNotIn("forged", self.kb.read("method")["content"])

    def test_orphan_and_duplicate_derived_rows_are_detected(self):
        self.add("a", relations=[{"type": "uses", "id": "b", "version": "1"}])
        corruptions = (
            "INSERT INTO unit_search(unit_row,field,text,lexemes) VALUES (999,'content','orphan','orphan')",
            "INSERT INTO unit_search(unit_row,field,text,lexemes) SELECT unit_row,field,text,lexemes FROM unit_search LIMIT 1",
            "INSERT INTO relations VALUES (999,'uses','b','1')",
            "INSERT INTO relations SELECT * FROM relations LIMIT 1",
            "UPDATE relations SET target_version='forged-version'",
        )
        for sql in corruptions:
            with self.subTest(sql=sql):
                with closing(sqlite3.connect(self.kb.db_path)) as db, db:
                    db.execute(sql)
                self.assertFalse(self.kb.status()["available"])
                self.kb.rebuild()
                self.assertTrue(self.kb.status()["complete"])

    def test_self_consistent_but_forged_cache_is_compared_to_original(self):
        self.add()
        docs, _ = self.kb._documents(["method.md"])
        forged = dict(docs["method.md"])
        forged["content"] += "\nforgedcacheddata\n"
        with closing(self.kb._connect()) as db, db:
            db.execute("DELETE FROM unit_search")
            db.execute("DELETE FROM relations")
            db.execute("DELETE FROM units")
            self.kb._insert(db, forged)
        self.assertFalse(self.kb.status()["available"])
        with self.assertRaises(KnowledgeError):
            self.kb.read("method")
        self.kb.sync()
        self.assertTrue(self.kb.status()["complete"])
        self.assertEqual(self.kb.search("forgedcacheddata"), [])

    def test_failed_corruption_recovery_keeps_old_database_unavailable(self):
        self.add()
        with closing(sqlite3.connect(self.kb.db_path)) as db, db:
            db.execute("DELETE FROM unit_search")
        previous = self.kb.db_path.read_bytes()
        with patch("eds.knowledge.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                self.kb.sync()
        self.assertEqual(previous, self.kb.db_path.read_bytes())
        self.assertFalse(self.kb.status()["available"])
        self.kb.rebuild()
        self.assertTrue(self.kb.search("pressure"))


if __name__ == "__main__":
    unittest.main()



