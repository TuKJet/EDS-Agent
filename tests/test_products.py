import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eds.personal_data import init
from eds.products import ProductError, ProductStore
from eds.study import StudyStore


class ProductStoreTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).parents[1] / "output" / "repository-tests" / "tmp"
        scratch.mkdir(parents=True, exist_ok=True)
        self.tmp = self.enterContext(tempfile.TemporaryDirectory(dir=scratch))
        self.root = Path(self.tmp)
        self.data = self.root / "data"
        init(self.data, user_id="product-test")
        self.enterContext(patch.dict("os.environ", {"EDS_CACHE_HOME": str(self.root / "cache")}))
        self.product = ProductStore.create(self.data / "studies" / "products" / "part", "part", "Part")

    def asset(self, content=b"stable", name="drawing.txt"):
        path = self.root / name
        path.write_bytes(content)
        return path

    def test_revisions_are_cas_and_prior_is_immutable(self):
        first = self.product.show()
        second = self.product.update({"gaps": ["material unknown"]}, base_ref=first["ref"])
        self.assertEqual(self.product.show(first["ref"])["payload"]["gaps"], [])
        with self.assertRaises(ProductError):
            self.product.update({"gaps": []}, base_ref=first["ref"])
        self.assertEqual(self.product.show()["ref"], second["ref"])

    def test_asset_copy_pinning_and_moved_root(self):
        source = self.asset(b"rev-a")
        baseline = self.product.attach(source, asset_id="drawing", role="drawing", base_ref="product-baseline@1")
        baseline = self.product.update({"statements": [{"id": "spacing", "subject": "mount", "topic": "parameter",
            "text": "120 mm", "attribution": "document", "sources": [{"asset_id": "drawing", "locator": "line 1"}]}]}, base_ref=baseline["ref"])
        source.write_bytes(b"changed")
        self.assertTrue(self.product.check_assets(baseline["ref"])["ok"])
        pinned = self.product.show(baseline["ref"])["payload"]["statements"][0]["sources"][0]
        self.assertEqual(pinned["sha256"], hashlib.sha256(b"rev-a").hexdigest())
        moved = self.root / "moved-data"
        shutil.copytree(self.data, moved)
        relocated = ProductStore(moved / "studies" / "products" / "part")
        self.assertTrue(relocated.check_assets(baseline["ref"])["ok"])
        target = StudyStore.create(moved / "studies" / "cae", "CAE", mode="cae")
        relocated.use(target.root, baseline_ref=baseline["ref"])

    def test_verified_requires_verification_sources(self):
        with self.assertRaises(ProductError):
            self.product.update({"statements": [{"id": "claim", "subject": "part", "topic": "function",
                "text": "verified?", "attribution": "user", "validation": "verified",
                "sources": [{"uri": "chat://turn/1", "locator": "message"}]}]}, base_ref="product-baseline@1")
        self.product.update({"statements": [{"id": "claim", "subject": "part", "topic": "function",
            "text": "verified", "attribution": "document", "validation": "verified",
            "sources": [{"uri": "doc://drawing", "locator": "p1"}],
            "verification_sources": [{"uri": "doc://test", "locator": "report p2"}]}]}, base_ref="product-baseline@1")

    def test_asset_revision_preserves_old_source_and_warns_on_reuse(self):
        first = self.product.attach(self.asset(b"rev-a"), asset_id="drawing", role="drawing", base_ref="product-baseline@1")
        first = self.product.update({"statements": [{"id": "claim", "subject": "part", "topic": "history",
            "text": "old source", "attribution": "document", "sources": [{"asset_id": "drawing", "locator": "p1"}]}]}, base_ref=first["ref"])
        second = self.product.attach(self.asset(b"rev-b", "drawing-new.txt"), asset_id="drawing", role="drawing", base_ref=first["ref"], revision="B")
        old_source = self.product.show(first["ref"])["payload"]["statements"][0]["sources"][0]
        self.assertEqual(old_source["sha256"], hashlib.sha256(b"rev-a").hexdigest())
        self.assertIn("claim", self.product.resume()["stale_sources"])
        target = StudyStore.create(self.data / "studies" / "cae", "CAE", mode="cae")
        snapshot = self.product.use(target.root, baseline_ref=second["ref"])
        self.assertEqual(snapshot["payload"]["stale_source_statements"], ["claim"])
        # The old source is still evidence for the carried statement; losing it
        # must be detected even though the new drawing is intact.
        (self.data / old_source["location"]).unlink()
        with self.assertRaises(ProductError):
            self.product.use(target.root, baseline_ref=second["ref"])

    def test_missing_or_tampered_asset_refuses_use(self):
        baseline = self.product.attach(self.asset(), asset_id="drawing", role="drawing", base_ref="product-baseline@1")
        asset = self.product.show(baseline["ref"])["payload"]["assets"][0]
        copied = self.data / asset["location"]
        target = StudyStore.create(self.data / "studies" / "cae", "CAE", mode="cae")
        copied.write_bytes(b"tampered")
        with self.assertRaises(ProductError):
            self.product.use(target.root, baseline_ref=baseline["ref"])
        copied.unlink()
        with self.assertRaises(ProductError):
            self.product.use(target.root, baseline_ref=baseline["ref"])

    def test_invalid_attach_does_not_copy_before_cas_failure(self):
        current = self.product.update({"gaps": ["current"]}, base_ref="product-baseline@1")
        before = sorted(str(path) for path in (self.data / "assets").rglob("*") if path.is_file())
        with self.assertRaises(ProductError):
            self.product.attach(self.asset(b"new", "new.txt"), asset_id="new", role="cad", base_ref="product-baseline@1")
        after = sorted(str(path) for path in (self.data / "assets").rglob("*") if path.is_file())
        self.assertEqual(before, after)
        self.assertEqual(self.product.show()["ref"], current["ref"])

    def test_private_paths_and_ordinary_study_rejected(self):
        ordinary = StudyStore.create(self.data / "studies" / "ordinary", "ordinary", mode="cad")
        with self.assertRaises(ProductError):
            ProductStore.create(ordinary.root, "bad", "Bad")
        with tempfile.TemporaryDirectory(prefix="_product-test-", dir=Path(__file__).parents[1] / "skills") as directory:
            skill_path = Path(directory)
            with self.assertRaises(ProductError):
                ProductStore.create(skill_path, "bad", "Bad")
            self.assertFalse((skill_path / "study.json").exists())

    def test_publish_retry_and_conflict_preserve_files(self):
        with patch("eds.products.KnowledgeBase.register", side_effect=OSError("index unavailable")):
            with self.assertRaises(ProductError):
                self.product.publish(baseline_ref="product-baseline@1")
        published = self.product.publish(baseline_ref="product-baseline@1")
        snapshot = Path(published["snapshot_path"])
        snapshot.write_bytes(b"conflict")
        with self.assertRaises(ProductError):
            self.product.publish(baseline_ref="product-baseline@1")
        self.assertEqual(snapshot.read_bytes(), b"conflict")

    def test_tampered_relative_asset_location_is_rejected(self):
        state = self.product.study.read()
        state["entities"][0]["payload"]["assets"] = [{"id": "x", "role": "cad", "sha256": "0" * 64,
            "size": 1, "location": "../../escape", "location_base": "data/product"}]
        self.product.study._write(state)
        with self.assertRaises(ProductError):
            self.product.check_assets()

    def test_cross_root_snapshot_keeps_explicit_product_locator(self):
        external = ProductStore.create(self.root / "external-product", "external", "External")
        baseline = external.attach(self.asset(b"cross-root"), asset_id="drawing", role="drawing", base_ref="product-baseline@1")
        target = StudyStore.create(self.data / "studies" / "cae", "CAE", mode="cae")
        snapshot = external.use(target.root, baseline_ref=baseline["ref"])
        self.assertEqual(snapshot["payload"]["asset_context"]["product_root"], str(external.root))
        self.assertTrue(snapshot["payload"]["asset_context"]["requires_rebind_on_move"])
        self.assertEqual(snapshot["payload"]["baseline"]["assets"][0]["location"], "assets/" + baseline["payload"]["assets"][0]["location"].split("assets/", 1)[-1])
        self.assertFalse((target.root / snapshot["payload"]["baseline"]["assets"][0]["location"]).exists())

    def test_foreign_target_identity_and_mutated_product_identity_are_rejected(self):
        target = StudyStore.create(self.data / "studies" / "cad", "CAD", mode="cad")
        original = target.add("proposal", {"purpose": "unrelated", "assumptions": []}, ref="product-part")
        before = target.path.read_bytes()
        with self.assertRaises(ProductError):
            self.product.use(target.root, baseline_ref="product-baseline@1")
        self.assertEqual(target.path.read_bytes(), before)
        self.assertEqual(target.get(ref=original["ref"]), original)
        invalid = self.product.show()["payload"]
        invalid["product_id"] = "another-product"
        self.product.study.add("design", invalid, ref="product-baseline@1")
        with self.assertRaises(ProductError):
            self.product.resume()

    def test_changed_source_during_copy_does_not_commit_a_baseline(self):
        from eds import products
        source = self.asset(b"before")
        real_copy = products._copy_asset

        def changed_copy(source, target, expected):
            source.write_bytes(b"after")
            return real_copy(source, target, expected)

        with patch("eds.products._copy_asset", side_effect=changed_copy):
            with self.assertRaises(ProductError):
                self.product.attach(source, asset_id="drawing", role="drawing", base_ref="product-baseline@1")
        self.assertEqual(self.product.show()["ref"], "product-baseline@1")
        self.assertFalse(list((self.data / "assets").rglob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
