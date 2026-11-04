"""Verified local text patches for pinned execution submodules; never deploys to a VM."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
import socket
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


class PatchError(ValueError):
    pass


def _git(folder, *args):
    try:
        result = subprocess.run(["git", *args], cwd=folder, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PatchError(f"Git unavailable: {type(exc).__name__}") from exc
    if result.returncode:
        raise PatchError(f"Git {args[0]} failed: {result.stderr.decode('utf-8', errors='replace').strip()[:600]}")
    return result.stdout


def _path(root, relative):
    if (not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative
            or "\x00" in relative or PurePosixPath(relative).is_absolute()
            or any(part.casefold() in {"", ".", "..", ".git"} or part.rstrip(". ") != part
                   for part in relative.split("/"))):
        raise PatchError(f"unsafe patch path: {relative!r}")
    target = root / relative
    for part in (target, *target.parents):
        if part == root:
            break
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise PatchError(f"linked patch path: {relative}")
    if not target.resolve().is_relative_to(root.resolve()):
        raise PatchError(f"patch path escapes root: {relative}")
    return target


def _text(data):
    if data is None:
        return None
    data.decode("utf-8")
    if b"\x00" in data:
        raise PatchError("only UTF-8 text patches are supported")
    return data.replace(b"\r\n", b"\n")


def _hash(data):
    return hashlib.sha256(_text(data)).hexdigest() if data is not None else None


def _read(path):
    if not path.exists():
        return None
    if not path.is_file():
        raise PatchError(f"expected regular file: {path.name}")
    return path.read_bytes()


def _manifest(root, known):
    path = _path(root, known["patch_manifest"])
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict) or manifest.get("schema") != "eds-execution-patches/v1"
            or manifest.get("submodule") != f"execution-skills/{known['id']}"
            or manifest.get("base_commit") != known["pinned_commit"]
            or manifest.get("content_hash") != "sha256-utf8-lf"):
        raise PatchError("patch manifest schema, submodule, base or hash convention mismatch")
    patches = manifest.get("patches")
    if not isinstance(patches, list) or not patches:
        raise PatchError("patch manifest must contain an ordered nonempty patch list")
    seen = set()
    for patch in patches:
        if not isinstance(patch, dict) or not isinstance(patch.get("file"), str) or patch["file"] in seen:
            raise PatchError("invalid or duplicate patch entry")
        seen.add(patch["file"])
        patch_path = _path(path.parent, patch["file"])
        raw = patch_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != patch.get("sha256"):
            raise PatchError(f"patch checksum mismatch: {patch['file']}")
        files = patch.get("files")
        if not isinstance(files, dict) or not files:
            raise PatchError(f"missing file hashes: {patch['file']}")
        for name, hashes in files.items():
            _path(root, name)
            if not isinstance(hashes, dict) or set(hashes) != {"before", "after"}:
                raise PatchError(f"invalid file hash entry: {name}")
            if hashes["before"] == hashes["after"]:
                raise PatchError(f"empty change: {name}")
            if any(value is not None and (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value))
                   for value in hashes.values()):
                raise PatchError(f"invalid SHA-256: {name}")
        patch["_path"] = patch_path
    return manifest, hashlib.sha256(path.read_bytes()).hexdigest()


def _expected(folder, manifest):
    """Reconstruct the whole stack away from the checkout, including during --check."""
    names = sorted({name for patch in manifest["patches"] for name in patch["files"]})
    entries = _git(folder, "ls-tree", "-z", "HEAD", "--", *names).split(b"\0")
    base = dict.fromkeys(names)
    for entry in filter(None, entries):
        meta, raw_name = entry.split(b"\t", 1)
        mode, kind, _ = meta.split()
        name = raw_name.decode("utf-8")
        if mode not in {b"100644", b"100755"} or kind != b"blob" or name not in base:
            raise PatchError("patch targets must be regular tracked text files")
        base[name] = _text(_git(folder, "show", f"HEAD:{name}"))
    prefixes = []
    with tempfile.TemporaryDirectory(prefix="eds-patch-check-") as directory:
        scratch = Path(directory)
        # Git still applies a containing repository's path prefix with --no-index.
        # A disposable repository prevents that when TMPDIR is inside this checkout.
        _git(scratch, "init", "--quiet")
        for name, data in base.items():
            if data is not None:
                target = _path(scratch, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        for patch in manifest["patches"]:
            # --no-index makes this independent of any containing repository.
            stats = _git(scratch, "apply", "--no-index", "--numstat", "-z", str(patch["_path"]))
            paths = []
            for entry in filter(None, stats.split(b"\0")):
                added, deleted, raw_name = entry.split(b"\t", 2)
                if not added.isdigit() or not deleted.isdigit():
                    raise PatchError("binary or rename patches are not supported")
                name = raw_name.decode("utf-8")
                _path(scratch, name)
                paths.append(name)
            if len(paths) != len(set(paths)) or set(paths) != set(patch["files"]):
                raise PatchError(f"patch paths differ from manifest: {patch['file']}")
            raw = patch["_path"].read_bytes()
            if re.search(rb"^(?:old mode|new mode|rename from|rename to|copy from|copy to) ", raw, re.M):
                raise PatchError("mode, rename and copy patches are not supported")
            if any(mode not in {b"100644", b"100755"}
                   for mode in re.findall(rb"^(?:new file|deleted file) mode (\d+)$", raw, re.M)):
                raise PatchError("linked or nonregular patch target")
            if re.search(rb"^new file mode 100755$", raw, re.M):
                raise PatchError("new executable files are not supported by the text patch installer")
            for name, hashes in patch["files"].items():
                if _hash(_read(_path(scratch, name))) != hashes["before"]:
                    raise PatchError(f"patch order or before hash mismatch: {patch['file']}: {name}")
            _git(scratch, "apply", "--no-index", "--check", "--whitespace=nowarn", str(patch["_path"]))
            _git(scratch, "apply", "--no-index", "--whitespace=nowarn", str(patch["_path"]))
            for name, hashes in patch["files"].items():
                if _hash(_read(_path(scratch, name))) != hashes["after"]:
                    raise PatchError(f"after hash mismatch: {patch['file']}: {name}")
            prefixes.append({name: _text(_read(_path(scratch, name))) for name in names})
        final = {name: _text(_read(_path(scratch, name))) for name in names}
    return base, final, prefixes[:-1]


def _working_state(folder, base, final, prefixes=()):
    if _git(folder, "diff", "--cached", "--name-only", "-z", "HEAD", "--"):
        raise PatchError("staged submodule changes must be reviewed before patch installation")
    raw = _git(folder, "diff", "--raw", "--no-renames", "-z", "HEAD", "--").split(b"\0")
    changed = set()
    for index in range(0, len(raw) - 1, 2):
        header, name = raw[index], raw[index + 1].decode("utf-8")
        fields = header.split()
        old_mode, new_mode = fields[0][1:], fields[1]
        if old_mode != new_mode and new_mode != b"000000":
            raise PatchError(f"unexpected file mode change: {name}")
        changed.add(name)
    changed.update(name.decode("utf-8") for name in
                   _git(folder, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0") if name)
    extra = changed - set(base)
    if extra:
        raise PatchError("additional submodule changes: " + ", ".join(sorted(extra)))
    current = {name: _read(_path(folder, name)) for name in base}
    normalized = {name: _text(data) for name, data in current.items()}
    if normalized == final:
        return "applied", current
    if normalized == base or normalized in prefixes:
        return "ready_to_apply", current
    raise PatchError("patch target has local edits or an incomplete patch stack; files preserved")


def _write(path, data):
    if data is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode if path.exists() else None
    fd, temporary = tempfile.mkstemp(prefix=".eds-patch-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _apply(root, folder, known, base, final, manifest_hash, prefixes=()):
    state_root = _path(root, "local/execution-patches")
    state_root.mkdir(parents=True, exist_ok=True)
    lock = state_root / f"{known['id']}.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        details = lock.read_text(encoding="utf-8", errors="replace")[:600]
        raise PatchError(f"another patch install or interrupted transaction needs review: {lock}; {details}") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump({"pid": os.getpid(), "host": socket.gethostname(),
                   "created_at": datetime.now(timezone.utc).isoformat(),
                   "manifest_sha256": manifest_hash}, stream)
    try:
        if _git(folder, "rev-parse", "HEAD").decode().strip() != known["pinned_commit"]:
            raise PatchError("submodule HEAD changed during patch preparation")
        state, current = _working_state(folder, base, final, prefixes)
        if state == "applied":
            return None
        backup = state_root / f"{known['id']}-{uuid.uuid4().hex}"
        backup.mkdir()
        for name, data in current.items():
            if data is not None:
                _write(_path(backup, name), data)
        receipt = {"status": "prepared", "manifest_sha256": manifest_hash,
                   "submodule": str(folder), "original_files": {name: data is not None for name, data in current.items()}}
        receipt_path = backup / "transaction.json"
        _write(receipt_path, json.dumps(receipt, indent=2).encode("utf-8"))
        written = {}
        try:
            for name, data in final.items():
                target = _path(folder, name)
                if _read(target) != current[name]:
                    raise PatchError(f"file changed during installation: {name}")
                original = current[name]
                # Preserve an existing CRLF checkout. Hash comparisons are LF-normalized.
                if data is not None and original and b"\r\n" in original and b"\n" not in original.replace(b"\r\n", b""):
                    data = data.replace(b"\n", b"\r\n")
                _write(target, data)
                written[name] = data
            if _working_state(folder, base, final)[0] != "applied":
                raise PatchError("patch final verification failed")
        except (OSError, ValueError) as exc:
            conflicts = []
            for name, data in reversed(list(written.items())):
                try:
                    target = _path(folder, name)
                    if _read(target) != data:
                        conflicts.append(name)
                    else:
                        _write(target, current[name])
                except (OSError, ValueError):
                    conflicts.append(name)
            receipt.update(status="rollback_needs_review" if conflicts else "rolled_back", conflicts=conflicts)
            _write(receipt_path, json.dumps(receipt, indent=2).encode("utf-8"))
            raise PatchError(f"{exc}; recovery evidence: {backup}") from exc
        receipt["status"] = "applied"
        _write(receipt_path, json.dumps(receipt, indent=2).encode("utf-8"))
        return str(backup)
    finally:
        lock.unlink()


def patch_status(repo_root, known, *, apply=False):
    """Inspect or install the exact registered stack. No marker is trusted as proof."""
    result = {"id": known["id"], "status": "not_required", "ready": True,
              "expected_dirty": False, "reasons": []}
    if not known.get("patch_manifest"):
        return result
    result.update(status="invalid", ready=False, manifest=known["patch_manifest"])
    try:
        root = Path(repo_root).resolve()
        folder = _path(root, f"execution-skills/{known['id']}")
        if not (folder / ".git").is_file():
            result.update(status="not_initialized", reasons=["initialize the registered submodule first"])
            return result
        head = _git(folder, "rev-parse", "HEAD").decode().strip()
        result.update(base_commit=known["pinned_commit"], actual_commit=head)
        if head != known["pinned_commit"]:
            result.update(status="base_mismatch", reasons=["submodule HEAD differs from the patch base; checkout preserved"])
            return result
        manifest, digest = _manifest(root, known)
        result.update(manifest_sha256=digest, patches=[item["file"] for item in manifest["patches"]])
        base, final, prefixes = _expected(folder, manifest)
        result["files"] = {name: {"before": _hash(base[name]), "after": _hash(data)} for name, data in final.items()}
        result["status"] = "conflict"
        state, _ = _working_state(folder, base, final, prefixes)
        if apply and state == "ready_to_apply":
            result["recovery_directory"] = _apply(root, folder, known, base, final, digest, prefixes)
            state, _ = _working_state(folder, base, final)
        result.update(status=state, ready=state == "applied", expected_dirty=state == "applied")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result.update(ready=False, expected_dirty=False, reasons=[str(exc)])
    return result
