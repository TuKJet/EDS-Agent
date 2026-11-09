import json
import concurrent.futures
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from eds import personal_data


class PersonalDataTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / ".test-tmp"
        test_root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=test_root)
        self.root = Path(self.tmp.name) / "data"

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_requires_identity_and_is_idempotent(self):
        with self.assertRaises(personal_data.PersonalDataError):
            personal_data.init(self.root, user_id="")
        first = personal_data.init(self.root, user_id="alice")
        for name in ("knowledge", "studies", "assets"):
            self.assertTrue((self.root / name / ".gitkeep").is_file())
        self.assertEqual(personal_data.init(self.root, user_id="alice"), first)
        with self.assertRaises(personal_data.PersonalDataError):
            personal_data.init(self.root, user_id="bob")

    def test_nonempty_uninitialized_root_is_not_taken_over(self):
        self.root.mkdir(parents=True)
        (self.root / "existing.txt").write_text("user data", encoding="utf-8")
        with self.assertRaises(personal_data.PersonalDataError):
            personal_data.init(self.root, user_id="alice")

    def test_competing_initializers_cannot_replace_owner(self):
        barrier = threading.Barrier(2)
        local = threading.local()
        original_mkdir = Path.mkdir

        def gated_mkdir(path, *args, **kwargs):
            if path == self.root and not getattr(local, "past_preflight", False):
                local.past_preflight = True
                barrier.wait(timeout=5)
            return original_mkdir(path, *args, **kwargs)

        def initialize(identity):
            try:
                result = personal_data.init(self.root, user_id=identity)
                self.assertEqual(result["user_id"], identity)
                return identity
            except personal_data.PersonalDataError:
                return None

        with patch.object(Path, "mkdir", gated_mkdir):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(initialize, ("alice", "bob")))
        winners = [item for item in results if item is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(personal_data.get_paths(self.root)["user_id"], winners[0])

    def test_precedence_explicit_env_config_default(self):
        first = self.root / "first"
        second = self.root / "second"
        third = self.root / "third"
        personal_data.init(first, user_id="alice")
        personal_data.init(second, user_id="alice")
        personal_data.init(third, user_id="alice")
        config = self.root / "config.json"
        config.write_text(json.dumps({"data_root": str(first)}), encoding="utf-8")
        with patch.object(personal_data, "CONFIG_PATH", config), patch.dict(os.environ, {"EDS_DATA_HOME": str(second)}):
            self.assertEqual(Path(personal_data.get_paths()["root"]), second.resolve())
            self.assertEqual(Path(personal_data.get_paths(third)["root"]), third.resolve())
        with patch.object(personal_data, "CONFIG_PATH", config), patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EDS_DATA_HOME", None)
            self.assertEqual(Path(personal_data.get_paths()["root"]), first.resolve())

    def test_status_is_read_only_and_default_uninitialized(self):
        absent = self.root / "absent"
        with patch.dict(os.environ, {"EDS_DATA_HOME": str(absent)}):
            before = absent.exists()
            result = personal_data.status()
            self.assertFalse(result["initialized"])
            self.assertEqual(absent.exists(), before)

    def test_aliases_and_path_traversal(self):
        personal_data.init(self.root, user_id="alice")
        self.assertEqual(Path(personal_data.resolve_alias("@knowledge", self.root)), self.root / "knowledge")
        self.assertEqual(Path(personal_data.resolve_alias("@study/job-1", self.root)), self.root / "studies" / "job-1")
        self.assertEqual(personal_data.resolve_alias("C:/explicit/file", self.root), "C:/explicit/file")
        for value in ("@study/../secret", "@study/a/b", "@unknown"):
            with self.assertRaises(personal_data.PersonalDataError):
                personal_data.resolve_alias(value, self.root)
        self.assertEqual(personal_data.resolve_alias(Path("C:/explicit/file"), self.root), Path("C:/explicit/file"))

    def test_study_alias_rejects_existing_link_escape(self):
        personal_data.init(self.root, user_id="alice")
        outside = Path(self.tmp.name) / "outside-study"
        outside.mkdir()
        link = self.root / "studies" / "escape"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation is unavailable")
        with self.assertRaises(personal_data.PersonalDataError):
            personal_data.resolve_alias("@study/escape", self.root)

    def test_relocated_byte_copy_rebuilds_without_sqlite(self):
        personal_data.init(self.root, user_id="alice")
        source = self.root / "knowledge" / "note.md"
        source.write_text("portable", encoding="utf-8")
        target = Path(self.tmp.name) / "relocated"
        target.mkdir()
        for relative in ("eds-data.json", "README.md", ".gitignore"):
            (target / relative).write_bytes((self.root / relative).read_bytes())
        for relative in ("knowledge", "studies", "assets"):
            (target / relative).mkdir()
        (target / "knowledge" / "note.md").write_bytes(source.read_bytes())
        self.assertEqual(personal_data.get_paths(target)["user_id"], "alice")
        self.assertEqual(personal_data.resolve_alias("@knowledge", target), str(target / "knowledge"))

    def test_cache_is_external_and_distinguishes_roots_and_subpaths(self):
        personal_data.init(self.root, user_id="alice")
        child = self.root / "knowledge"
        external_cache = Path(self.tmp.name) / "machine-cache"
        with patch.dict(os.environ, {"EDS_CACHE_HOME": str(external_cache)}):
            cache1 = Path(personal_data.managed_cache_root(child))
            cache2 = Path(personal_data.managed_cache_root(self.root / "studies"))
            self.assertTrue(cache1.is_relative_to(external_cache.resolve()))
            self.assertNotEqual(cache1, cache2)
            self.assertFalse(cache1.exists())
        with patch.dict(os.environ, {"EDS_CACHE_HOME": str(self.root / "cache-config")}):
            with self.assertRaises(personal_data.PersonalDataError):
                personal_data.managed_cache_root(child)
        self.assertIsNone(personal_data.managed_cache_root(self.root.parent))

    def test_invalid_manifest_and_symlink_escape_are_rejected(self):
        personal_data.init(self.root, user_id="alice")
        manifest = self.root / "eds-data.json"
        value = json.loads(manifest.read_text(encoding="utf-8"))
        value["directories"]["knowledge"] = "../outside"
        manifest.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(personal_data.PersonalDataError):
            personal_data.status(self.root)
        escaped = Path(self.tmp.name) / "symlink-root"
        personal_data.init(escaped, user_id="alice")
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        try:
            (escaped / "knowledge" / ".gitkeep").unlink()
            (escaped / "knowledge").rmdir()
            os.symlink(outside, escaped / "knowledge", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation is unavailable")
        with self.assertRaises(personal_data.PersonalDataError):
            personal_data.status(escaped)

    def test_deep_subdirectories_keep_cache_outside_data_root(self):
        personal_data.init(self.root, user_id="alice")
        deep = self.root / "knowledge" / Path(*(["nested"] * 12))
        deep.mkdir(parents=True)
        cache = Path(self.tmp.name) / "machine-cache"
        with patch.dict(os.environ, {"EDS_CACHE_HOME": str(cache)}):
            self.assertTrue(personal_data.managed_cache_root(deep).is_relative_to(cache.resolve()))

    def test_default_cache_is_stable_across_launcher_environment(self):
        personal_data.init(self.root, user_id="alice")
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root), "EDS_CACHE_HOME": ""}):
            first = personal_data.managed_cache_root(self.root / "knowledge")
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "redirected"), "EDS_CACHE_HOME": ""}):
            second = personal_data.managed_cache_root(self.root / "knowledge")
        self.assertEqual(first, second)
        self.assertTrue(first.is_relative_to((Path.home() / ".eds" / "cache").resolve()))


if __name__ == "__main__":
    unittest.main()
