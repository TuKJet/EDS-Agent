"""Portable, user-owned data root discovery and local bindings.

The managed root contains portable Markdown, studies and assets. Search indexes,
locks and machine-specific bindings stay outside the manifest and can be rebuilt.
This module does not copy data, contact a remote service, or infer an identity.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

SCHEMA = "eds-personal-data/v1"
DEFAULT_DIRS = {"knowledge": "knowledge", "studies": "studies", "assets": "assets"}
CONFIG_PATH = Path.home() / ".eds" / "config.json"
_IDENTITY = re.compile(r"^[^\\/\x00]+$")
_STUDY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class PersonalDataError(ValueError):
    """Invalid, unsafe, or uninitialized personal data root."""


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PersonalDataError(f"{label} must be nonempty text")
    return value.strip()


def _root(value: str | os.PathLike[str]) -> Path:
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if not isinstance(value, str) or not value.strip():
        raise PersonalDataError("personal data root must be nonempty text")
    candidate = Path(value).expanduser().resolve()
    home = Path.home().resolve()
    if candidate == home or candidate == Path(candidate.anchor) or home.is_relative_to(candidate):
        raise PersonalDataError("personal data root cannot be a home directory or filesystem root")
    repo = Path(__file__).resolve().parent.parent
    forbidden = (repo / "skills", repo / ".agents" / "skills", repo / "execution-skills")
    if any(candidate == item or item in candidate.parents for item in forbidden):
        raise PersonalDataError("personal data root cannot be inside a distributable Skill directory")
    return candidate


def _manifest_path(root: Path) -> Path:
    return root / "eds-data.json"


def _manifest(root: Path) -> dict[str, Any]:
    path = _manifest_path(root)
    if not path.is_file():
        raise PersonalDataError(f"personal data root is not initialized: {root}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersonalDataError("personal data manifest is unreadable") from exc
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise PersonalDataError("unsupported personal data manifest")
    user_id = _text(value.get("user_id"), "manifest.user_id")
    if not _IDENTITY.fullmatch(user_id):
        raise PersonalDataError("manifest.user_id contains a path separator")
    directories = value.get("directories")
    if directories != DEFAULT_DIRS:
        raise PersonalDataError("manifest directories are invalid")
    for relative in directories.values():
        path_value = Path(relative)
        if path_value.is_absolute() or ".." in path_value.parts:
            raise PersonalDataError("manifest directory must be relative and contained")
        directory = (root / path_value).resolve(strict=False)
        if not directory.is_relative_to(root) or not directory.is_dir():
            raise PersonalDataError("manifest directory escapes root or is missing")
    return value


def _chosen_root(explicit: str | os.PathLike[str] | None = None) -> Path:
    if explicit is not None:
        return _root(explicit)
    env_value = os.environ.get("EDS_DATA_HOME")
    if env_value:
        return _root(env_value)
    config = CONFIG_PATH
    if config.is_file():
        try:
            value = json.loads(config.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PersonalDataError("local EDS binding is unreadable") from exc
        if not isinstance(value, dict) or not isinstance(value.get("data_root"), str) or not value["data_root"].strip():
            raise PersonalDataError("local EDS binding requires data_root")
        return _root(value["data_root"])
    return _root(Path.home() / "EDS-Data")


def _atomic_json(path: Path, value: dict[str, Any], *, overwrite: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".eds-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        elif os.name == "nt":
            # On Windows rename refuses an existing destination atomically.
            os.rename(temporary, path)
        else:
            # Publish a complete manifest without replacing another initializer's
            # identity. Both files are on the same filesystem.
            os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def init(root: str | os.PathLike[str] | None = None, *, user_id: str) -> dict[str, Any]:
    """Create or validate a portable root. No OS username is inferred."""
    target = _chosen_root(root)
    identity = _text(user_id, "user_id")
    if not _IDENTITY.fullmatch(identity):
        raise PersonalDataError("user_id cannot contain path separators")
    if target.exists():
        manifest_path = _manifest_path(target)
        if manifest_path.exists():
            existing = _manifest(target)
            if existing["user_id"] != identity:
                raise PersonalDataError("personal data root belongs to a different user_id")
            return get_paths(target)
        if any(target.iterdir()):
            raise PersonalDataError("existing nonempty directory is not an initialized EDS root")
    target.mkdir(parents=True, exist_ok=True)
    for relative in DEFAULT_DIRS.values():
        directory = target / relative
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ".gitkeep").touch(exist_ok=True)
    manifest = {"schema": SCHEMA, "user_id": identity, "directories": DEFAULT_DIRS}
    try:
        _atomic_json(_manifest_path(target), manifest, overwrite=False)
    except FileExistsError:
        existing = _manifest(target)
        if existing["user_id"] != identity:
            raise PersonalDataError("personal data root belongs to a different user_id")
    readme = target / "README.md"
    if not readme.exists():
        readme.write_text("# EDS 个人数据根\n\n此目录包含 `knowledge`、`studies` 和 `assets`，可由私有同步工具同步。搜索索引和锁文件可在每台电脑重建；机器缓存保存在同步根之外。使用 `python -m eds data use <root>` 将本机绑定到这份数据。\n", encoding="utf-8")
    ignore = target / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*.sqlite3\n*.sqlite3-*\n*.lock\n*.tmp\n.eds-cache/\n", encoding="utf-8")
    return get_paths(target)


def use(root: str | os.PathLike[str]) -> dict[str, Any]:
    """Explicitly bind this computer to an initialized root."""
    target = _root(root)
    manifest = _manifest(target)
    _atomic_json(CONFIG_PATH, {"schema": "eds-local-binding/v1", "data_root": str(target)})
    return get_paths(target, manifest=manifest)


def status(root: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Read-only health/status; does not create a directory or config."""
    target = _chosen_root(root)
    result = {"root": str(target), "initialized": False, "user_id": None,
              "directories": {key: str(target / value) for key, value in DEFAULT_DIRS.items()},
              "exists": target.exists()}
    if _manifest_path(target).is_file():
        manifest = _manifest(target)
        result.update({"initialized": True, "user_id": manifest["user_id"]})
    return result


def get_paths(root: str | os.PathLike[str] | None = None, *, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    target = _root(root) if root is not None else _chosen_root()
    data = manifest or _manifest(target)
    return {"root": str(target), "user_id": data["user_id"],
            **{key: str(target / relative) for key, relative in data["directories"].items()},
            "manifest": str(_manifest_path(target))}


def resolve_alias(value: str | os.PathLike[str], root: str | os.PathLike[str] | None = None) -> str | os.PathLike[str]:
    """Resolve @knowledge and @study/<safe-id>; explicit paths are unchanged."""
    original = value
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    text = _text(value, "path")
    if not text.startswith("@"):
        return original
    paths = get_paths(root)
    if text == "@knowledge":
        return paths["knowledge"]
    if text == "@assets":
        return paths["assets"]
    prefix = "@study/"
    if text.startswith(prefix):
        study_id = text[len(prefix):]
        if not _STUDY.fullmatch(study_id):
            raise PersonalDataError("study alias contains an unsafe id")
        studies_root = Path(paths["studies"]).resolve()
        candidate = (studies_root / study_id).resolve(strict=False)
        if not candidate.is_relative_to(studies_root):
            raise PersonalDataError("study alias escapes the managed studies directory")
        return str(candidate)
    raise PersonalDataError(f"unknown personal data alias: {text}")


def managed_data_root(path: str | os.PathLike[str]) -> Path | None:
    """Find the containing portable root without scanning other directories."""
    target = Path(path).expanduser().resolve()
    current = target if target.is_dir() else target.parent
    while True:
        if (current / "eds-data.json").is_file():
            _manifest(current)
            return current
        if current.parent == current:
            break
        current = current.parent
    return None


def managed_cache_root(path: str | os.PathLike[str]) -> Path | None:
    """Return a machine-local cache path for a path inside a valid data root."""
    target = Path(path).expanduser().resolve()
    current = managed_data_root(target)
    if current is None:
        return None
    relative = target.relative_to(current).as_posix() if target != current else "."
    token = hashlib.sha256((str(current) + "\0" + relative).encode("utf-8")).hexdigest()[:24]
    cache_base = os.environ.get("EDS_CACHE_HOME")
    # Some desktop launchers redirect LOCALAPPDATA per process. Keep one lock.
    base = (Path(cache_base) if cache_base else Path.home() / ".eds" / "cache").expanduser().resolve()
    if base == current or current in base.parents:
        raise PersonalDataError("machine cache must be outside the synchronized data root")
    result = base / token
    if result.resolve().is_relative_to(current):
        raise PersonalDataError("existing machine cache link points into the synchronized data root")
    return result


# Explicit names used by the command-line data root entrypoint. The shorter
# aliases remain available to callers that already imported this module.
init_data = init
use_data = use
data_status = status


__all__ = ["PersonalDataError", "SCHEMA", "get_paths", "init", "init_data", "managed_cache_root", "managed_data_root",
           "resolve_alias", "status", "data_status", "use", "use_data"]
