import difflib
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eds import patches


def digest(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest() if data is not None else None


class PatchTests(unittest.TestCase):
    def setUp(self):
        temporary_root = Path(__file__).resolve().parent.parent / ".test-tmp"
        temporary_root.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=temporary_root)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        temporary_setting = patch("tempfile.tempdir", str(self.root))
        temporary_setting.start()
        self.addCleanup(temporary_setting.stop)
        self.vendor = self.root / "execution-skills/demo"
        self.vendor.mkdir(parents=True)
        self.git("init", "-q", f"--separate-git-dir={self.root / 'git-storage'}")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "core.filemode", "false")
        for name, data in {"a.py": b"a = 1\n", "b.py": b"b = 1\n", "unrelated.py": b"other = 1\n", ".gitignore": b"*.pyc\n"}.items():
            (self.vendor / name).write_bytes(data)
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD").decode().strip()
        self.directory = self.root / "patches/demo"
        self.directory.mkdir(parents=True)
        self.known = {"id": "demo", "pinned_commit": self.base, "patch_manifest": "patches/demo/manifest.json"}
        self.manifest = {"schema": "eds-execution-patches/v1", "submodule": "execution-skills/demo",
                         "base_commit": self.base, "content_hash": "sha256-utf8-lf", "patches": []}
        self.add_patch("one.patch", {"a.py": (b"a = 1\n", b"a = 2\n"), "tests/new.py": (None, b"test = 1\n")})
        self.add_patch("two.patch", {"a.py": (b"a = 2\n", b"a = 3\n"), "b.py": (b"b = 1\n", b"b = 2\n")})
        self.save_manifest()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.vendor, capture_output=True, check=True).stdout

    def add_patch(self, filename, files):
        lines = []
        for name, (before, after) in files.items():
            lines.append(f"diff --git a/{name} b/{name}\n")
            if before is None:
                lines.append("new file mode 100644\n")
            if after is None:
                lines.append("deleted file mode 100644\n")
            lines.extend(difflib.unified_diff((before or b"").decode().splitlines(True),
                                             (after or b"").decode().splitlines(True),
                                             fromfile=f"a/{name}" if before is not None else "/dev/null",
                                             tofile=f"b/{name}" if after is not None else "/dev/null"))
        data = "".join(lines).encode()
        (self.directory / filename).write_bytes(data)
        self.manifest["patches"].append({"file": filename, "sha256": hashlib.sha256(data).hexdigest(),
                                         "files": {name: {"before": digest(before), "after": digest(after)}
                                                   for name, (before, after) in files.items()}})

    def save_manifest(self):
        (self.directory / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def check(self, apply=False):
        return patches.patch_status(self.root, self.known, apply=apply)

    def test_ordered_stack_check_only_apply_and_idempotence(self):
        before = (self.vendor / "a.py").read_bytes()
        result = self.check()
        self.assertEqual(result["status"], "ready_to_apply", result)
        self.assertFalse(result["ready"])
        self.assertFalse((self.root / "local").exists())
        self.assertEqual((self.vendor / "a.py").read_bytes(), before)
        result = self.check(apply=True)
        self.assertTrue(result["ready"], result)
        self.assertTrue(result["expected_dirty"])
        self.assertEqual((self.vendor / "a.py").read_bytes(), b"a = 3\n")
        self.assertEqual((self.vendor / "b.py").read_bytes(), b"b = 2\n")
        self.assertTrue((self.vendor / "tests/new.py").is_file())
        modified = (self.vendor / "a.py").stat().st_mtime_ns
        second = self.check(apply=True)
        self.assertEqual(second["status"], "applied", second)
        self.assertEqual((self.vendor / "a.py").stat().st_mtime_ns, modified)
        self.assertEqual(self.git("rev-parse", "HEAD").decode().strip(), self.base)
        self.assertEqual(self.git("diff", "--cached", "--name-only"), b"")
        (self.vendor / "ignored.pyc").write_bytes(b"cache")
        self.assertTrue(self.check()["ready"])

    def test_checksum_before_after_and_order_mismatches_preserve_checkout(self):
        original = json.loads(json.dumps(self.manifest))
        for field in ("sha256", "before", "after", "order"):
            with self.subTest(field=field):
                self.manifest = json.loads(json.dumps(original))
                if field == "sha256":
                    self.manifest["patches"][0]["sha256"] = "0" * 64
                elif field == "order":
                    self.manifest["patches"].reverse()
                else:
                    self.manifest["patches"][0]["files"]["a.py"][field] = "0" * 64
                self.save_manifest()
                result = self.check(apply=True)
                self.assertFalse(result["ready"], result)
                self.assertEqual((self.vendor / "a.py").read_bytes(), b"a = 1\n")
                self.assertFalse((self.vendor / "tests/new.py").exists())

    def test_local_target_edits_and_additional_tracked_or_untracked_edits_block(self):
        for name in ("a.py", "unrelated.py", "new-user-file.txt"):
            with self.subTest(name=name):
                target = self.vendor / name
                before = target.read_bytes() if target.exists() else None
                target.write_bytes(b"user edits\n")
                result = self.check(apply=True)
                self.assertEqual(result["status"], "conflict", result)
                self.assertFalse(result["ready"])
                self.assertEqual(target.read_bytes(), b"user edits\n")
                if before is None:
                    target.unlink()
                else:
                    target.write_bytes(before)
        self.assertTrue(self.check(apply=True)["ready"])
        (self.vendor / "unrelated.py").write_bytes(b"later user edit\n")
        self.assertFalse(self.check()["ready"])

    def test_partial_stack_is_not_silently_overwritten(self):
        (self.vendor / "a.py").write_bytes(b"a = 2\n")
        result = self.check(apply=True)
        self.assertFalse(result["ready"], result)
        self.assertEqual((self.vendor / "a.py").read_bytes(), b"a = 2\n")

    def test_upgrade_from_a_verified_complete_prefix_applies_only_known_changes(self):
        newer = self.manifest['patches'].pop()
        self.save_manifest()
        self.assertTrue(self.check(apply=True)['ready'])
        self.assertEqual((self.vendor / 'a.py').read_bytes(), b'a = 2\n')
        self.manifest['patches'].append(newer)
        self.save_manifest()
        self.assertEqual(self.check()['status'], 'ready_to_apply')
        self.assertTrue(self.check(apply=True)['ready'])
        self.assertEqual((self.vendor / 'a.py').read_bytes(), b'a = 3\n')
        self.assertEqual((self.vendor / 'tests/new.py').read_bytes(), b'test = 1\n')

    def test_wrong_base_and_staged_changes_block(self):
        self.known["pinned_commit"] = "0" * 40
        self.assertEqual(self.check(apply=True)["status"], "base_mismatch")
        self.known["pinned_commit"] = self.base
        (self.vendor / "a.py").write_bytes(b"staged = 1\n")
        self.git("add", "a.py")
        result = self.check(apply=True)
        self.assertFalse(result["ready"], result)
        self.assertIn("staged", " ".join(result["reasons"]))

    def test_crlf_checkout_is_recognized_and_preserved(self):
        (self.vendor / "a.py").write_bytes(b"a = 1\r\n")
        result = self.check(apply=True)
        self.assertTrue(result["ready"], result)
        self.assertEqual((self.vendor / "a.py").read_bytes(), b"a = 3\r\n")
        self.assertEqual(self.check()["status"], "applied")

    def test_manifest_paths_and_undeclared_patch_paths_are_rejected(self):
        self.manifest["patches"][0]["file"] = "../../escape.patch"
        self.save_manifest()
        self.assertFalse(self.check(apply=True)["ready"])
        self.manifest["patches"][0]["file"] = "one.patch"
        del self.manifest["patches"][0]["files"]["tests/new.py"]
        self.save_manifest()
        self.assertFalse(self.check(apply=True)["ready"])
        self.assertEqual((self.vendor / "a.py").read_bytes(), b"a = 1\n")

    def test_failed_write_rolls_back_owned_files_and_keeps_recovery_evidence(self):
        real_write = patches._write
        def fail_second(path, data):
            if path == self.vendor / "b.py" and data == b"b = 2\n":
                raise OSError("simulated disk error")
            return real_write(path, data)
        with patch("eds.patches._write", side_effect=fail_second):
            result = self.check(apply=True)
        self.assertFalse(result["ready"], result)
        self.assertEqual((self.vendor / "a.py").read_bytes(), b"a = 1\n")
        self.assertEqual((self.vendor / "b.py").read_bytes(), b"b = 1\n")
        receipts = list((self.root / "local/execution-patches").glob("*/transaction.json"))
        self.assertEqual(len(receipts), 1)
        self.assertEqual(json.loads(receipts[0].read_text())["status"], "rolled_back")

    def test_git_failure_and_missing_manifest_are_not_ready(self):
        with patch("eds.patches._git", side_effect=patches.PatchError("Git unavailable")):
            self.assertFalse(self.check()["ready"])
        (self.directory / "manifest.json").unlink()
        self.assertFalse(self.check(apply=True)["ready"])


if __name__ == "__main__":
    unittest.main()
