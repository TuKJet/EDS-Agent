import tempfile
import unittest
from pathlib import Path

from eds.assets import check_assets, fingerprint


class AssetTests(unittest.TestCase):
    def test_manual_change_and_missing_asset_are_visible(self):
        temporary_root = Path(__file__).resolve().parent.parent / "output" / "repository-tests" / "tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as root:
            path = Path(root) / "part.step"
            path.write_bytes(b"initial fixture")
            snapshot = fingerprint(path)
            self.assertFalse(check_assets([snapshot])["requires_impact_review"])
            path.write_bytes(b"edited fixture")
            changed = check_assets([snapshot])
            self.assertEqual(changed["assets"][0]["status"], "changed")
            self.assertEqual(snapshot["sha256"], changed["assets"][0]["previous"]["sha256"])
            path.unlink()
            self.assertEqual(check_assets([snapshot])["assets"][0]["status"], "missing")
