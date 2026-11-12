import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = Path(r"C:\Program Files\PowerShell\7\pwsh.exe")
TEST_TMP = REPO_ROOT / "output" / "repository-tests" / "tmp"


@unittest.skipUnless(POWERSHELL.is_file(), "PowerShell 7 is required")
class InvokeMcpPowerShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TEST_TMP.mkdir(parents=True, exist_ok=True)

    def test_tokenless_call_clears_inherited_token_and_restores_it(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as directory:
            root = Path(directory)
            child_log = root / "child-token.txt"
            after_log = root / "after-token.txt"
            fake_python = root / "fake-python.cmd"
            fake_python.write_text(
                f'@echo off\r\n"{POWERSHELL}" -NoProfile -Command "[IO.File]::WriteAllText(\'{child_log}\',$env:EDS_MCP_TOKEN)"\r\nexit /b 23\r\n',
                encoding="utf-8",
            )
            config = root / "config.json"
            config.write_text(json.dumps({"python_path": str(fake_python), "url": "http://127.0.0.1:1/mcp"}), encoding="utf-8")
            output = root / "output.json"
            command = (
                f'$env:EDS_MCP_TOKEN="inherited"; '
                f'& "{REPO_ROOT / "scripts" / "invoke_mcp.ps1"}" '
                f'-ConfigPath "{config}" -OutputPath "{output}" -Discover; '
                f'$code=$LASTEXITCODE; [IO.File]::WriteAllText("{after_log}",$env:EDS_MCP_TOKEN); exit $code'
            )
            result = subprocess.run([str(POWERSHELL), "-NoProfile", "-Command", command],
                                    cwd=REPO_ROOT, text=True, encoding="utf-8", capture_output=True)
            self.assertEqual(result.returncode, 23, result.stderr)
            self.assertEqual(child_log.read_text(encoding="utf-8"), "")
            self.assertEqual(after_log.read_text(encoding="utf-8"), "inherited")

    def test_configured_missing_credential_fails_without_downgrade(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as directory:
            root = Path(directory)
            config = root / "config.json"
            config.write_text(json.dumps({
                "python_path": str(POWERSHELL),
                "token_credential_path": str(root / "missing.xml"),
                "url": "http://127.0.0.1:1/mcp",
            }), encoding="utf-8")
            result = subprocess.run([
                str(POWERSHELL), "-NoProfile", "-File", str(REPO_ROOT / "scripts" / "invoke_mcp.ps1"),
                "-ConfigPath", str(config), "-OutputPath", str(root / "output.json"), "-Discover",
            ], cwd=REPO_ROOT, text=True, encoding="utf-8", capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing.xml", result.stderr)


if __name__ == "__main__":
    unittest.main()
