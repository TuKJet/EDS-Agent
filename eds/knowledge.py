"""Explicit Markdown knowledge units with a disposable, incremental SQLite index.

Codex supplies complete units and judges applicability. This module performs no
extraction or model calls. A workspace is created only by a write operation.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
from collections import Counter
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Iterator

INDEX_VERSION = "2"
META_RE = re.compile(r"<!--\s*eds-knowledge:\s*(\{.*?\})\s*-->", re.S)
CJK_RE = re.compile(r"[\u3400-\u9fff]+")
WORD_RE = re.compile(r"[A-Za-z0-9_]+|[\u0370-\u03ff]+")

KNOWLEDGE_QUESTIONS = {
    "design", "method-selection", "experiment-design", "result-interpretation",
    "cad-modeling", "drawing", "delivery",
}
KNOWLEDGE_STAGES = {"discussion", "planning", "execution", "interpretation", "delivery"}
PREFERENCE_SCOPES = {"user", "team", "project"}
PREFERENCE_STATUSES = {"candidate", "confirmed", "retired"}
PREFERENCE_ORIGINS = {"explicit", "inferred"}


class KnowledgeError(ValueError):
    """Malformed knowledge or a derived index that cannot be used as current."""


def _reject_constant(value: str) -> None:
    raise KnowledgeError(f"nonfinite JSON value: {value}")


def _json(text: str) -> Any:
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise KnowledgeError(f"invalid JSON: {exc}") from exc


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, allow_nan=False)


def _terms(text: str, *, indexing: bool = False) -> set[str]:
    """Encode ngrams as ASCII tokens so SQLite tokenizer choices cannot split them."""
    terms = {"w" + word.lower().encode("utf-8").hex() for word in WORD_RE.findall(text)}
    for run in CJK_RE.findall(text):
        if indexing or len(run) == 1:
            terms.update("u" + char.encode("utf-8").hex() for char in run)
        terms.update("c" + run[i:i + 2].encode("utf-8").hex() for i in range(len(run) - 1))
    return terms


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _metadata(content: str) -> dict[str, Any]:
    matches = list(META_RE.finditer(content))
    if len(matches) != 1:
        raise KnowledgeError("a knowledge Markdown must contain exactly one eds-knowledge JSON comment")
    meta = _json(matches[0].group(1))
    if not isinstance(meta, dict):
        raise KnowledgeError("knowledge metadata must be an object")
    for field in ("id", "version", "type", "title"):
        if not _nonempty(meta.get(field)):
            raise KnowledgeError(f"metadata {field} must be nonempty text")
    for field in ("conditions", "sources", "relations"):
        if field not in meta:
            raise KnowledgeError(f"metadata requires {field}")
    if not isinstance(meta["conditions"], (dict, list)):
        raise KnowledgeError("conditions must be an object or list; missing conditions remain explicit")
    if not isinstance(meta["sources"], list) or (not meta["sources"] and meta.get("sources_missing") is not True):
        raise KnowledgeError("sources must be a nonempty list, or set sources_missing=true")
    for source in meta["sources"]:
        if not isinstance(source, dict) or not all(_nonempty(source.get(key)) for key in ("uri", "locator")):
            raise KnowledgeError("each source requires nonempty uri and locator")
    if not isinstance(meta["relations"], list):
        raise KnowledgeError("relations must be a list")
    for relation in meta["relations"]:
        if not isinstance(relation, dict) or not all(_nonempty(relation.get(key)) for key in ("id", "version", "type")):
            raise KnowledgeError("each relation requires explicit id, version, and type")
    for key in ("date", "attribution", "domain", "project"):
        if key in meta and not _nonempty(meta[key]):
            raise KnowledgeError(f"optional metadata {key} must be nonempty text")
    if meta.get("type") == "preference":
        required = ("preference_key", "value", "scope", "scope_id", "preference_status", "origin")
        if any(key not in meta or not _nonempty(meta.get(key)) for key in required):
            raise KnowledgeError("preference requires preference_key, value, scope, scope_id, preference_status, and origin")
        if meta["scope"] not in PREFERENCE_SCOPES or meta["preference_status"] not in PREFERENCE_STATUSES:
            raise KnowledgeError("preference scope or preference_status is unsupported")
        if meta["origin"] not in PREFERENCE_ORIGINS:
            raise KnowledgeError("preference origin is unsupported")
        if meta["origin"] == "inferred" and meta["preference_status"] == "confirmed":
            raise KnowledgeError("inferred preferences cannot be confirmed without explicit confirmation")
    for key, allowed in (("question", KNOWLEDGE_QUESTIONS), ("stage", KNOWLEDGE_STAGES)):
        if key in meta and (not _nonempty(meta[key]) or meta[key] not in allowed):
            raise KnowledgeError(f"metadata {key} is unsupported")
    return meta


def _fields(meta: dict[str, Any], content: str) -> dict[str, str]:
    fields = {key: _text(value) for key, value in meta.items() if key not in {"id", "version", "relations"}}
    # Mask metadata while preserving line numbers; it is indexed in named fields.
    body = META_RE.sub(lambda match: "\n" * match.group(0).count("\n"), content)
    fields["content"] = body
    return fields


class KnowledgeBase:
    """One explicit-registry knowledge workspace. Construction is read-only."""

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).resolve()
        self.registry_path = self.root / "registry.json"
        self.db_path = self.root / "index.sqlite3"

    @contextmanager
    def _lock(self) -> Iterator[None]:
        """OS-owned locks survive neither process exit nor a crashed writer."""
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.root / ".knowledge.lock", "a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            deadline = time.monotonic() + 10
            while True:
                handle.seek(0)
                try:
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise KnowledgeError("knowledge workspace is busy") from exc
                    time.sleep(0.02)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _relative(self, path: str | os.PathLike[str]) -> str:
        candidate = Path(path)
        candidate = candidate if candidate.is_absolute() else self.root / candidate
        try:
            relative = candidate.resolve().relative_to(self.root)
        except ValueError as exc:
            raise KnowledgeError("knowledge document must stay inside its workspace") from exc
        if relative.suffix.lower() != ".md":
            raise KnowledgeError("only Markdown knowledge units may be registered")
        return relative.as_posix()

    def _read_registry(self) -> list[str]:
        if not self.registry_path.exists():
            return []
        value = _json(self.registry_path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict) or not isinstance(value.get("documents"), list):
            raise KnowledgeError("registry requires a documents array")
        if value.get("schema", "eds-registry/v1") != "eds-registry/v1":
            raise KnowledgeError("unsupported registry schema")
        paths = value["documents"]
        if any(not _nonempty(path) or Path(path).is_absolute() for path in paths):
            raise KnowledgeError("registry paths must be nonempty relative paths")
        normalized = [self._relative(path) for path in paths]
        if len(set(normalized)) != len(normalized):
            raise KnowledgeError("registry contains duplicate paths")
        return sorted(normalized)

    def _write_registry(self, paths: list[str]) -> None:
        fd, temporary = tempfile.mkstemp(prefix="registry.", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump({"schema": "eds-registry/v1", "documents": sorted(paths)}, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.registry_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def read_metadata(path: str | os.PathLike[str]) -> dict[str, Any]:
        return _metadata(Path(path).read_text(encoding="utf-8-sig"))

    def _documents(self, paths: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
        documents, missing, seen = {}, [], set()
        for relative in paths:
            target = self.root / self._relative(relative)
            if not target.is_file():
                missing.append(relative)
                continue
            try:
                before = target.stat()
            except OSError:
                missing.append(relative)
                continue
            raw = target.read_bytes()
            try:
                after = target.stat()
            except OSError:
                raise KnowledgeError(f"knowledge source disappeared while reading: {relative}")
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise KnowledgeError(f"knowledge source changed while reading: {relative}; retry sync")
            try:
                content = raw.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise KnowledgeError(f"knowledge Markdown is not UTF-8: {relative}") from exc
            meta = _metadata(content)
            identity = (meta["id"], meta["version"])
            if identity in seen:
                raise KnowledgeError(f"duplicate knowledge identity: {identity}")
            seen.add(identity)
            documents[relative] = {"path": relative, "metadata": meta, "content": content,
                                   "content_hash": hashlib.sha256(raw).hexdigest(),
                                   "source_stat": [before.st_size, before.st_mtime_ns]}
        return documents, missing

    def _connect(self, path: Path | None = None, *, readonly: bool = False) -> sqlite3.Connection:
        target = path or self.db_path
        connection = sqlite3.connect(target.as_uri() + "?mode=ro", uri=True) if readonly else sqlite3.connect(target)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _schema(connection: sqlite3.Connection) -> None:
        connection.executescript("""
            CREATE TABLE units (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT NOT NULL, version TEXT NOT NULL, type TEXT NOT NULL,
                title TEXT NOT NULL, path TEXT NOT NULL UNIQUE, content_hash TEXT NOT NULL,
                metadata_json TEXT NOT NULL, content TEXT NOT NULL, UNIQUE(id, version));
            CREATE TABLE relations (
                source_row INTEGER NOT NULL, relation_type TEXT NOT NULL,
                target_id TEXT NOT NULL, target_version TEXT NOT NULL);
            CREATE VIRTUAL TABLE unit_search USING fts5(
                unit_row UNINDEXED, field UNINDEXED, text, lexemes);
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        connection.execute("INSERT INTO meta VALUES ('index_version', ?)", (INDEX_VERSION,))

    @staticmethod
    def _check_database(
        connection: sqlite3.Connection,
        documents: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        version = connection.execute("SELECT value FROM meta WHERE key='index_version'").fetchone()
        if not version or version[0] != INDEX_VERSION:
            raise KnowledgeError("unsupported knowledge index version; rebuild required")
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise KnowledgeError("knowledge database failed integrity check")
        # quick_check validates SQLite pages, not application-level completeness.
        # Reconstruct expected derived rows from each complete stored unit and
        # compare their multisets: missing, duplicate and orphan rows all matter.
        expected_fields: Counter[tuple[Any, ...]] = Counter()
        expected_relations: Counter[tuple[Any, ...]] = Counter()
        for row in connection.execute("SELECT * FROM units"):
            if not all(isinstance(row[key], str) for key in ("content", "metadata_json", "path", "content_hash")):
                raise KnowledgeError("knowledge index contains malformed cached unit values")
            metadata = _metadata(row["content"])
            if _json(row["metadata_json"]) != metadata:
                raise KnowledgeError(f"cached metadata differs from unit content: {row['path']}")
            if any(row[key] != metadata[key] for key in ("id", "version", "type", "title")):
                raise KnowledgeError(f"cached identity/title differs from unit metadata: {row['path']}")
            source = documents.get(row["path"]) if documents is not None else None
            # When source hashes differ, status reports a normal stale source.
            # Equal hashes with unequal cached content reveal derived corruption.
            if source is not None and row["content_hash"] == source["content_hash"]:
                if row["content"] != source["content"] or metadata != source["metadata"]:
                    raise KnowledgeError(f"cached unit differs from its original source snapshot: {row['path']}")
            for field, text in _fields(metadata, row["content"]).items():
                lexemes = " ".join(sorted(_terms(text, indexing=True)))
                expected_fields[(row["rowid"], field, text, lexemes)] += 1
            for relation in metadata["relations"]:
                expected_relations[(row["rowid"], relation["type"], relation["id"], relation["version"])] += 1
        actual_fields = Counter(tuple(row) for row in connection.execute("SELECT unit_row,field,text,lexemes FROM unit_search"))
        if actual_fields != expected_fields:
            raise KnowledgeError("knowledge search fields are missing, duplicated, orphaned or inconsistent; rebuild required")
        actual_relations = Counter(tuple(row) for row in connection.execute("SELECT source_row,relation_type,target_id,target_version FROM relations"))
        if actual_relations != expected_relations:
            raise KnowledgeError("knowledge relations are missing, duplicated, orphaned or inconsistent; rebuild required")

    @staticmethod
    def _insert(connection: sqlite3.Connection, document: dict[str, Any]) -> None:
        meta = document["metadata"]
        cursor = connection.execute("INSERT INTO units(id,version,type,title,path,content_hash,metadata_json,content) VALUES (?,?,?,?,?,?,?,?)",
                                    (meta["id"], meta["version"], meta["type"], meta["title"], document["path"],
                                     document["content_hash"], json.dumps(meta, ensure_ascii=False), document["content"]))
        rowid = cursor.lastrowid
        for field, text in _fields(meta, document["content"]).items():
            connection.execute("INSERT INTO unit_search(unit_row,field,text,lexemes) VALUES (?,?,?,?)",
                               (rowid, field, text, " ".join(sorted(_terms(text, indexing=True)))))
        for relation in meta["relations"]:
            connection.execute("INSERT INTO relations VALUES (?,?,?,?)", (rowid, relation["type"], relation["id"], relation["version"]))

    def _manifest(self, connection: sqlite3.Connection, paths: list[str], missing: list[str],
                  documents: dict[str, dict[str, Any]] | None = None) -> None:
        source_stats = {}
        for relative in paths:
            if documents is not None and relative in documents:
                source_stats[relative] = documents[relative]["source_stat"]
                continue
            target = self.root / relative
            try:
                stat = target.stat()
                source_stats[relative] = [stat.st_size, stat.st_mtime_ns]
            except OSError:
                continue
        for key, value in (("registered_paths", paths), ("missing_files", missing),
                           ("source_stats", source_stats)):
            connection.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value)))

    def _rebuild(self, paths: list[str], docs: dict[str, dict[str, Any]], missing: list[str]) -> dict[str, int]:
        fd, name = tempfile.mkstemp(prefix="index.", suffix=".sqlite3", dir=self.root)
        os.close(fd)
        temporary = Path(name)
        try:
            with closing(self._connect(temporary)) as connection, connection:
                self._schema(connection)
                for document in docs.values():
                    self._insert(connection, document)
                self._manifest(connection, paths, missing, docs)
            # All connections are closed before Windows replaces the old index.
            os.replace(temporary, self.db_path)
        finally:
            temporary.unlink(missing_ok=True)
        return {"added": len(docs), "updated": 0, "removed": 0, "rebuilt": 1}

    def _sync(self, paths: list[str], docs: dict[str, dict[str, Any]], missing: list[str], *, force: bool = False) -> dict[str, int]:
        if force or not self.db_path.is_file():
            return self._rebuild(paths, docs, missing)
        try:
            with closing(self._connect(readonly=True)) as connection:
                connection.execute("BEGIN")
                self._check_database(connection, docs)
                rows = {row["path"]: dict(row) for row in connection.execute("SELECT rowid,path,content_hash FROM units")}
                manifest = {row["key"]: row["value"] for row in connection.execute("SELECT * FROM meta")}
        except (sqlite3.DatabaseError, KnowledgeError):
            return self._rebuild(paths, docs, missing)
        deleted = set(rows) - set(docs)
        changed = {path for path, document in docs.items() if path not in rows or rows[path]["content_hash"] != document["content_hash"]}
        counts = {"added": len(changed - set(rows)), "updated": len(changed & set(rows)), "removed": len(deleted), "rebuilt": 0}
        source_stats = {path: document["source_stat"] for path, document in docs.items()}
        if (not changed and not deleted
                and manifest.get("registered_paths") == json.dumps(paths)
                and manifest.get("missing_files") == json.dumps(missing)
                and manifest.get("source_stats") == json.dumps(source_stats)):
            return counts
        with closing(self._connect()) as connection, connection:
            for path in deleted | changed:
                if path in rows:
                    rowid = rows[path]["rowid"]
                    connection.execute("DELETE FROM unit_search WHERE unit_row=?", (rowid,))
                    connection.execute("DELETE FROM relations WHERE source_row=?", (rowid,))
                    connection.execute("DELETE FROM units WHERE rowid=?", (rowid,))
            for path in sorted(changed):
                self._insert(connection, docs[path])
            self._manifest(connection, paths, missing, docs)
        return counts

    def register(self, path: str | os.PathLike[str]) -> dict[str, Any]:
        return self.register_many([path])[0]

    def register_many(self, paths: list[str | os.PathLike[str]]) -> list[dict[str, Any]]:
        """Validate a complete batch before changing the registry or index."""
        if not isinstance(paths, list) or not paths:
            raise KnowledgeError("register_many requires a nonempty path array")
        relatives = [self._relative(path) for path in paths]
        if len(set(relatives)) != len(relatives):
            raise KnowledgeError("duplicate registration paths")
        with self._lock():
            registered_paths = self._read_registry()
            candidate = sorted(set(registered_paths) | set(relatives))
            docs, missing = self._documents(candidate)
            if any(relative in missing for relative in relatives):
                raise KnowledgeError("cannot register missing Markdown in batch")
            # Validation, including identities and relation shapes, precedes mutation.
            if candidate != registered_paths or not self.registry_path.exists():
                self._write_registry(candidate)
            try:
                self._sync(candidate, docs, missing)
            except (OSError, sqlite3.DatabaseError) as exc:
                raise KnowledgeError(f"document saved and registered, but index failed: {exc}") from exc
            health = self.status()
            return [{**docs[relative]["metadata"], "path": relative, "saved": True, "registered": True,
                     "indexed": health["consistent"], "index_status": health} for relative in relatives]

    def preference_catalog(self) -> list[dict[str, Any]]:
        """Explicit low-frequency enumeration, with supersession; no lexical search."""
        self._light_health(check_sources=True)
        with closing(self._connect(readonly=True)) as connection:
            connection.execute("BEGIN")
            rows = list(connection.execute("SELECT * FROM units WHERE type='preference'"))
            superseded = self._superseded_preferences(rows)
            units = [{**self._unit(row), "superseded": (row["id"], row["version"]) in superseded}
                     for row in rows]
        self._verify_returned(units)
        return units

    def unregister(self, path: str | os.PathLike[str]) -> dict[str, Any]:
        relative = self._relative(path)
        with self._lock():
            paths = [item for item in self._read_registry() if item != relative]
            docs, missing = self._documents(paths)
            self._write_registry(paths)
            self._sync(paths, docs, missing)
            return {"path": relative, "saved": (self.root / relative).is_file(), "registered": False, "indexed": False}

    def sync(self) -> dict[str, Any]:
        with self._lock():
            paths = self._read_registry()
            docs, missing = self._documents(paths)
            if not self.registry_path.exists():
                self._write_registry(paths)
            changes = self._sync(paths, docs, missing)
        return {**self.status(), "changes": changes}

    def rebuild(self) -> dict[str, Any]:
        with self._lock():
            paths = self._read_registry()
            docs, missing = self._documents(paths)
            if not self.registry_path.exists():
                self._write_registry(paths)
            changes = self._sync(paths, docs, missing, force=True)
        return {**self.status(), "changes": changes}

    def status(self) -> dict[str, Any]:
        result: dict[str, Any] = {"root": str(self.root), "index": str(self.db_path), "available": False,
                                  "consistent": False, "complete": False, "registered": 0, "indexed": 0,
                                  "registry_exists": self.registry_path.is_file(), "missing_files": []}
        try:
            paths = self._read_registry()
            result["registered"] = len(paths)
            docs, missing = self._documents(paths)
            result["missing_files"] = missing
            if not self.db_path.is_file():
                return result
            with closing(self._connect(readonly=True)) as connection:
                connection.execute("BEGIN")
                self._check_database(connection, docs)
                rows = {row["path"]: row["content_hash"] for row in connection.execute("SELECT path,content_hash FROM units")}
                manifest = {row["key"]: row["value"] for row in connection.execute("SELECT * FROM meta")}
            result.update(available=True, indexed=len(rows))
            result["consistent"] = (manifest.get("registered_paths") == json.dumps(paths)
                                    and manifest.get("missing_files") == json.dumps(missing)
                                    and rows == {path: doc["content_hash"] for path, doc in docs.items()})
            result["complete"] = result["consistent"] and not missing
        except (OSError, KnowledgeError, sqlite3.DatabaseError) as exc:
            result["error"] = str(exc)
        return result

    def _light_health(self, *, check_sources: bool) -> dict[str, Any]:
        """Cheap freshness gate for normal reads; status() remains the deep audit."""
        paths = self._read_registry()
        if not self.db_path.is_file():
            raise KnowledgeError("knowledge index unavailable; sync/rebuild required")
        try:
            with closing(self._connect(readonly=True)) as connection:
                version = connection.execute("SELECT value FROM meta WHERE key='index_version'").fetchone()
                if not version or version[0] != INDEX_VERSION:
                    raise KnowledgeError("unsupported knowledge index version; rebuild required")
                manifest = {row["key"]: row["value"] for row in connection.execute("SELECT * FROM meta")}
        except sqlite3.DatabaseError as exc:
            raise KnowledgeError("knowledge index unavailable; sync/rebuild required") from exc
        try:
            indexed_missing = set(json.loads(manifest.get("missing_files", "[]")))
        except (TypeError, json.JSONDecodeError) as exc:
            raise KnowledgeError("knowledge index manifest is invalid; rebuild required") from exc
        if manifest.get("registered_paths") != json.dumps(paths):
            raise KnowledgeError("knowledge index registration is stale; sync/rebuild required")
        source_stats = manifest.get("source_stats")
        if check_sources:
            if source_stats is None:
                # Legacy indexes have no stat manifest.  Compare source hashes
                # once, without invoking the full application-level audit.
                documents, missing = self._documents(paths)
                with closing(self._connect(readonly=True)) as connection:
                    rows = {row["path"]: row["content_hash"]
                            for row in connection.execute("SELECT path,content_hash FROM units")}
                expected = {path: doc["content_hash"] for path, doc in documents.items()}
                if set(missing) != indexed_missing or rows != expected:
                    raise KnowledgeError("knowledge source changed; sync/rebuild required")
                return {"complete": not bool(missing), "missing_files": missing}
            try:
                expected = json.loads(source_stats)
            except (TypeError, json.JSONDecodeError) as exc:
                raise KnowledgeError("knowledge source freshness manifest is invalid; rebuild required") from exc
            for relative in paths:
                if relative in indexed_missing:
                    if (self.root / self._relative(relative)).exists():
                        raise KnowledgeError(f"knowledge source reappeared: {relative}; sync required")
                    continue
                target = self.root / self._relative(relative)
                try:
                    stat = target.stat()
                except OSError as exc:
                    raise KnowledgeError(f"knowledge source is missing: {relative}; sync required") from exc
                if expected.get(relative) != [stat.st_size, stat.st_mtime_ns]:
                    raise KnowledgeError(f"knowledge source changed: {relative}; sync required")
        try:
            missing = json.loads(manifest.get("missing_files", "[]"))
        except (TypeError, json.JSONDecodeError) as exc:
            raise KnowledgeError("knowledge index manifest is invalid; rebuild required") from exc
        return {"complete": not bool(missing), "missing_files": missing}

    def _verify_returned(self, units: list[dict[str, Any]]) -> None:
        """Reject edits between the index check and completion of a read."""
        registered = set(self._read_registry())
        sources = {}
        for unit in units:
            if unit["path"] not in registered:
                raise KnowledgeError(f"source was unregistered during read: {unit['path']}; retry")
            target = self.root / self._relative(unit["path"])
            try:
                if unit["path"] not in sources:
                    sources[unit["path"]] = target.read_bytes()
                raw = sources[unit["path"]]
                current_hash = hashlib.sha256(raw).hexdigest()
            except OSError as exc:
                raise KnowledgeError(f"source disappeared during read: {unit['path']}") from exc
            if current_hash != unit["content_hash"]:
                raise KnowledgeError(f"source changed during read: {unit['path']}; sync and retry")
            snapshot = unit.get("_source_content", unit)
            if "content" in snapshot:
                try:
                    current_content = raw.decode("utf-8-sig")
                except UnicodeDecodeError as exc:
                    raise KnowledgeError(f"source could not be decoded during read: {unit['path']}") from exc
                if current_content != snapshot["content"]:
                    raise KnowledgeError(f"cached unit differs from source during read: {unit['path']}; sync and retry")
                if _metadata(current_content) != snapshot["metadata"]:
                    raise KnowledgeError(f"cached metadata differs from source during read: {unit['path']}; sync and retry")

    @staticmethod
    def _unit(row: sqlite3.Row) -> dict[str, Any]:
        metadata = _json(row["metadata_json"])
        warnings = [f"metadata {key} is missing" for key in ("date", "attribution") if not metadata.get(key)]
        return {"id": row["id"], "version": row["version"], "type": row["type"], "title": row["title"],
                "path": row["path"], "content_hash": row["content_hash"], "content": row["content"],
                "metadata": metadata, "sources": metadata["sources"], "warnings": warnings,
                "line_start": 1, "line_end": len(row["content"].splitlines())}

    @staticmethod
    def _dependency_summary(unit: dict[str, Any]) -> dict[str, Any]:
        """Keep relation traversal a locator until the caller explicitly expands it."""
        return {key: unit[key] for key in
                ("id", "version", "type", "title", "path", "content_hash", "warnings", "line_start", "line_end")}

    def read(self, unit_id: str, version: str | None = None, *, relation_types: set[str] | list[str] | None = None,
             depth: int = 0, max_units: int = 20) -> dict[str, Any]:
        if type(depth) is not int or depth < 0 or depth > 3:
            raise KnowledgeError("depth must be an integer from 0 to 3")
        if type(max_units) is not int or not 1 <= max_units <= 100:
            raise KnowledgeError("max_units must be an integer from 1 to 100")
        if relation_types is not None:
            if not isinstance(relation_types, (set, list, tuple)) or not all(_nonempty(value) for value in relation_types):
                raise KnowledgeError("relation_types must be a collection of nonempty text")
            relation_types = set(relation_types)
        health = self._light_health(check_sources=False)
        with closing(self._connect(readonly=True)) as connection:
            connection.execute("BEGIN")
            rows = connection.execute("SELECT * FROM units WHERE id=? AND (? IS NULL OR version=?)", (unit_id, version, version)).fetchall()
            if not rows:
                raise KnowledgeError(f"knowledge unit not found: {unit_id}@{version or '?'}")
            if len(rows) > 1:
                raise KnowledgeError(f"version required for multi-version unit: {unit_id}")
            result = self._unit(rows[0])
            result["index_status"] = {"complete": health["complete"], "missing_files": health["missing_files"]}
            visited = {(rows[0]["id"], rows[0]["version"])}
            queue = [(result, rows[0]["rowid"], 0)]
            depth_limit = depth
            result["dependencies_complete"] = True
            result["read_options"] = {"depth": depth, "max_units": max_units,
                                      "relation_types": sorted(relation_types) if relation_types is not None else None}
            for parent, rowid, current_depth in queue:
                relations = [dict(relation) for relation in parent["metadata"].get("relations", [])]
                relations = [{"relation_type": relation["type"], "target_id": relation["id"],
                              "target_version": relation["version"]} for relation in relations]
                total_relations = len(relations)
                if relation_types is not None:
                    relations = [relation for relation in relations if relation["relation_type"] in relation_types]
                parent["relations_omitted"] = total_relations - len(relations)
                if parent["relations_omitted"]:
                    result["dependencies_complete"] = False
                parent["relations"], parent["dependencies"] = relations, []
                for relation in relations:
                    identity = (relation["target_id"], relation["target_version"])
                    entry = {"id": identity[0], "version": identity[1]}
                    if identity in visited:
                        entry["already_included"] = True
                    elif len(visited) >= max_units:
                        entry["not_expanded"] = "dependency read bound reached; read this id/version explicitly"
                        result["dependencies_complete"] = False
                    else:
                        visited.add(identity)
                        row = connection.execute("SELECT * FROM units WHERE id=? AND version=?", identity).fetchone()
                        if row is None:
                            entry["missing"] = "referenced unit/version is not registered or available"
                            result["dependencies_complete"] = False
                        else:
                            full = self._unit(row)
                            if current_depth < depth_limit:
                                entry = full
                                queue.append((entry, row["rowid"], current_depth + 1))
                            else:
                                entry = self._dependency_summary(full)
                                entry["not_expanded"] = "dependency read bound reached; read this id/version explicitly"
                                result["dependencies_complete"] = False
                    parent["dependencies"].append(entry)
        self._verify_returned([item[0] for item in queue])
        return result

    @staticmethod
    def _preference_scope_matches(metadata: dict[str, Any], filters: dict[str, Any]) -> bool:
        scope = metadata["scope"]
        if filters.get(scope) != metadata["scope_id"]:
            return False
        # A global personal/team preference also applies within a project, but
        # a project-restricted preference needs that exact project context.
        if metadata.get("project") and metadata["project"] != filters.get("project"):
            return False
        if filters.get("question"):
            if metadata.get("question") and metadata["question"] != filters["question"]:
                return False
        elif filters.get("stage") and metadata.get("stage") and metadata["stage"] != filters["stage"]:
            return False
        return not filters.get("domain") or metadata.get("domain") == filters["domain"]

    @staticmethod
    def _superseded_preferences(rows: list[sqlite3.Row]) -> set[tuple[str, str]]:
        metadata = {(row["id"], row["version"]): _json(row["metadata_json"]) for row in rows}
        edges: dict[tuple[str, str], set[tuple[str, str]]] = {}
        for identity, source in metadata.items():
            if source["origin"] != "explicit" or source["preference_status"] not in {"confirmed", "retired"}:
                continue
            for relation in source["relations"]:
                target = (relation["id"], relation["version"])
                if relation["type"] != "supersedes" or target not in metadata or target == identity:
                    continue
                # A narrow project/condition revision cannot retire a general rule.
                if all(source.get(key) == metadata[target].get(key) for key in
                       ("preference_key", "scope", "scope_id", "project", "domain", "question", "stage", "conditions")):
                    edges.setdefault(identity, set()).add(target)

        def reaches(start, destination):
            pending, seen = [start], set()
            while pending:
                node = pending.pop()
                if node == destination:
                    return True
                if node not in seen:
                    seen.add(node)
                    pending.extend(edges.get(node, ()))
            return False

        # Cyclic revisions are ambiguous: retain the records for conflict review.
        return {target for source, targets in edges.items() for target in targets
                if not reaches(target, source)}

    def search(self, query: str, limit: int = 10, **filters: Any) -> list[dict[str, Any]]:
        if not isinstance(query, str) or type(limit) is not int or not 1 <= limit <= 1000:
            raise KnowledgeError("query must be text and limit an integer from 1 to 1000")
        supported = {"type", "domain", "project", "question", "stage", "user", "team", "preference_status"}
        if set(filters) - supported:
            raise KnowledgeError(f"unsupported filters: {sorted(set(filters) - supported)}")
        if any(value is not None and not _nonempty(value) for value in filters.values()):
            raise KnowledgeError("filter values must be nonempty text")
        requested_status = filters.get("preference_status")
        if requested_status is not None and requested_status not in PREFERENCE_STATUSES:
            raise KnowledgeError("unsupported preference_status")
        route = self.knowledge_route(filters.get("question"), filters.get("stage"))
        selected_types = [filters["type"]] if filters.get("type") else route["selected_types"]
        route_order = {kind: index for index, kind in enumerate(selected_types or [])}
        health = self._light_health(check_sources=True)
        terms = _terms(query)
        if not terms:
            return []
        expression = " OR ".join('lexemes:"' + term + '"' for term in sorted(terms))
        verified = []
        preference_enabled = ((selected_types is None or "preference" in selected_types)
                              and any(filters.get(key) for key in ("user", "team", "project")))
        with closing(self._connect(readonly=True)) as connection:
            connection.execute("BEGIN")
            preference_rows = (list(connection.execute("SELECT * FROM units WHERE type='preference'"))
                               if preference_enabled else [])
            superseded = self._superseded_preferences(preference_rows) if preference_enabled else set()
            conflicts: dict[tuple[str, str, str], list[tuple[sqlite3.Row, dict[str, Any]]]] = {}
            for row in preference_rows:
                meta = _json(row["metadata_json"])
                if (meta["preference_status"] == "confirmed"
                        and (row["id"], row["version"]) not in superseded
                        and self._preference_scope_matches(meta, filters)):
                    key = (meta["preference_key"], meta["scope"], meta["scope_id"])
                    conflicts.setdefault(key, []).append((row, meta))

            rows = connection.execute(
                "SELECT unit_row,field,text,bm25(unit_search) AS rank FROM unit_search WHERE unit_search MATCH ?",
                (expression,)).fetchall()
            grouped: dict[int, list[sqlite3.Row]] = {}
            for row in rows:
                grouped.setdefault(row["unit_row"], []).append(row)
            results = []
            for rowid, hits in grouped.items():
                row = connection.execute("SELECT * FROM units WHERE rowid=?", (rowid,)).fetchone()
                item = self._unit(row)
                meta = item["metadata"]
                if selected_types is not None and item["type"] not in selected_types:
                    continue
                if item["type"] == "preference":
                    if (not self._preference_scope_matches(meta, filters)
                            or meta["preference_status"] != (requested_status or "confirmed")):
                        continue
                    if (item["id"], item["version"]) in superseded and requested_status is None:
                        continue
                else:
                    if requested_status is not None:
                        continue
                    if any(meta.get(key) != filters[key] for key in ("domain", "project")
                           if filters.get(key) is not None):
                        continue

                metadata_match = META_RE.search(item["content"])
                metadata_start = item["content"][:metadata_match.start()].count("\n") + 1
                metadata_end = item["content"][:metadata_match.end()].count("\n") + 1
                body_lines = _fields(meta, item["content"])["content"].splitlines()
                locators = []
                for hit in hits:
                    if hit["field"] == "content":
                        locators.extend({"field": "content", "path": item["path"], "line_start": i, "line_end": i}
                                        for i, line in enumerate(body_lines, 1)
                                        if terms & _terms(line, indexing=True))
                    else:
                        locators.append({"field": hit["field"], "path": item["path"],
                                         "line_start": metadata_start, "line_end": metadata_end})
                body_hit = next((locator for locator in locators if locator["field"] == "content"), None)
                item["line"] = body_hit["line_start"] if body_hit else metadata_start
                item["snippet"] = (body_lines[item["line"] - 1][:500] if body_hit
                                   else "metadata field: " + hits[0]["field"])
                item["matched_fields"] = sorted({hit["field"] for hit in hits})
                item["locators"], item["locators_count"] = locators[:10], len(locators)
                item["score"] = -sum(hit["rank"] for hit in hits)
                item["index_status"] = {"complete": health["complete"], "missing_files": health["missing_files"]}
                item["_source_content"] = {"content": item["content"], "metadata": meta}
                del item["content"]
                item["metadata"] = {key: meta[key] for key in
                                    ("id", "version", "type", "title", "domain", "project", "question", "stage",
                                     "preference_key", "scope", "scope_id", "preference_status")
                                    if key in meta}
                item["conditions_available"] = bool(meta["conditions"])
                item["sources"] = [{key: source[key] for key in ("uri", "locator")} for source in meta["sources"][:3]]
                item["sources_count"] = len(meta["sources"])
                if item["type"] == "preference":
                    item["superseded"] = (item["id"], item["version"]) in superseded
                    key = (meta["preference_key"], meta["scope"], meta["scope_id"])
                    group = conflicts.get(key, []) if meta["preference_status"] == "confirmed" and not item["superseded"] else []
                    if len({other["value"] for _, other in group}) > 1:
                        item["conflict"] = "applicable confirmed preferences disagree; review before applying"
                        item["conflict_count"] = len(group)
                        item["conflict_refs"] = [
                            {key: other[key] for key in ("id", "version", "path", "content_hash")}
                            for other, _ in group[:10]]
                        item["conflict_refs_complete"] = len(group) <= 10
                results.append(item)

            results.sort(key=lambda item: (route_order.get(item["type"], len(route_order)),
                                           -item["score"], item["id"], item["version"]))
            results = results[:limit]
            for item in results:
                verified.extend(item.get("conflict_refs", []))
        self._verify_returned([*results, *verified])
        for item in results:
            item.pop("_source_content", None)
        return results

    @staticmethod
    def knowledge_route(question: str | None = None, stage: str | None = None) -> dict[str, Any]:
        """Select a small knowledge slice; this never falls back to the whole library."""
        if question is not None and question not in KNOWLEDGE_QUESTIONS:
            raise KnowledgeError(f"unsupported knowledge question: {question}")
        if stage is not None and stage not in KNOWLEDGE_STAGES:
            raise KnowledgeError(f"unsupported knowledge stage: {stage}")
        by_question = {
            "design": ["design", "feedback"],
            "method-selection": ["method", "feedback"],
            "experiment-design": ["experiment", "method"],
            "result-interpretation": ["feedback", "method"],
            "cad-modeling": ["design", "preference", "feedback"],
            "drawing": ["preference", "design", "feedback"],
            "delivery": ["preference", "feedback", "design"],
        }
        by_stage = {
            "discussion": ["design", "method"],
            "planning": ["experiment", "method"],
            "execution": ["preference", "design"],
            "interpretation": ["feedback", "method"],
            "delivery": ["preference", "feedback"],
        }
        selected = by_question.get(question) if question else (by_stage.get(stage) if stage else None)
        return {"question": question, "stage": stage, "primary_types": selected[:1] if selected else [],
                "selected_types": selected, "fallback": "none",
                "note": "Search each selected type explicitly; related units expand only on request."}


def knowledge_route(question: str | None = None, stage: str | None = None) -> dict[str, Any]:
    """Module-level route for CLI and integrations."""
    return KnowledgeBase.knowledge_route(question=question, stage=stage)
