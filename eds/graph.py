"""Bounded GraphQLite projection for the explicit EDS knowledge index.

The graph is a disposable projection.  Markdown and central experience JSON
remain the source of truth; this module never writes either of them.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from collections import deque
from pathlib import Path
from typing import Any

from .experience import ExperienceError, validate_iteration
from .knowledge import KnowledgeBase, KnowledgeError, knowledge_route

try:  # Optional by design: normal knowledge operation does not need it.
    import graphqlite  # type: ignore
except ImportError:  # pragma: no cover - exercised by dependency-free hosts
    graphqlite = None


class GraphError(KnowledgeError):
    """Graph projection is unavailable, invalid, or stale."""


GRAPH_SCHEMA = "eds-graph/v1"


def runtime_status(probe: bool = False) -> dict[str, Any]:
    backend = graphqlite
    result: dict[str, Any] = {"backend": "graphqlite", "package": "graphqlite", "available": backend is not None}
    if backend is None:
        result["reason"] = "GraphQLite is not installed; install requirements-graph.txt"
    else:
        result["version"] = getattr(graphqlite, "__version__", "unknown")
        if probe:
            try:
                with closing(sqlite3.connect(":memory:")) as connection:
                    backend.load(connection)
                    rows = _cypher(connection, "RETURN 1 AS ok")
                    result["probe"] = rows == [{"ok": 1}]
                    if not result["probe"]:
                        result["available"] = False
                        result["error"] = "GraphQLite smoke query returned an unexpected result"
            except Exception as exc:  # pragma: no cover - version/platform dependent
                result["available"] = False
                result["probe"] = False
                result["error"] = str(exc)
    return result


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _cypher(connection: sqlite3.Connection, statement: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    raw = connection.execute("SELECT cypher(?, ?)", (statement, _json(params or {}))).fetchone()[0]
    value = json.loads(raw)
    return value if isinstance(value, list) else []


def _load(connection: sqlite3.Connection) -> None:
    try:
        graphqlite.load(connection)
    except (AttributeError, OSError, RuntimeError, sqlite3.Error) as exc:
        raise GraphError(f"GraphQLite could not load: {exc}; run doctor --graph") from exc


def _key(uid: str, version: str) -> str:
    return "unit:" + hashlib.sha256(_json([uid, version]).encode("utf-8")).hexdigest()


def _read_stable(path: Path) -> tuple[bytes, list[int]]:
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    stat = [after.st_size, after.st_mtime_ns]
    if [before.st_size, before.st_mtime_ns] != stat:
        raise GraphError(f"source changed while reading: {path}; retry graph-sync")
    return raw, stat


class KnowledgeGraph:
    def __init__(self, root_or_kb: str | os.PathLike[str] | KnowledgeBase):
        self.kb = root_or_kb if isinstance(root_or_kb, KnowledgeBase) else KnowledgeBase(root_or_kb)
        self.path = self.kb.cache_root / "graph.sqlite3"

    def _require_runtime(self) -> None:
        if not runtime_status().get("available"):
            raise GraphError("GraphQLite is not installed; install requirements-graph.txt")

    def _source_snapshot(self, paths: list[str], docs: dict[str, dict[str, Any]], *, full=True) -> dict[str, Any]:
        units = []
        for path in paths:
            doc = docs.get(path)
            if doc is None:
                units.append({"path": path, "missing": True})
                continue
            meta = doc["metadata"]
            if meta["type"] == "preference":
                continue
            units.append({"path": path, "id": meta["id"], "version": str(meta["version"]),
                          "content_hash": doc["content_hash"], "source_stat": doc["source_stat"]})
        experience_sources = []
        for doc in docs.values():
            meta = doc["metadata"]
            if meta["type"] == "preference" or meta.get("data_schema") != "eds-experience/v1":
                continue
            source = (meta.get("sources") or [{}])[0]
            uri = source.get("uri")
            if not isinstance(uri, str) or not uri.strip() or Path(uri).is_absolute():
                raise GraphError(f"experience source URI is not safe: {uri!r}")
            target = (self.kb.root / uri).resolve()
            if not target.is_relative_to(self.kb.root.resolve()):
                raise GraphError(f"experience source escapes knowledge root: {uri}")
            try:
                if full:
                    raw, stat = _read_stable(target)
                    digest = hashlib.sha256(raw).hexdigest()
                else:
                    current = target.stat()
                    stat = [current.st_size, current.st_mtime_ns]
                    digest = source.get("sha256")
            except OSError as exc:
                raise GraphError(f"experience source is missing: {uri}") from exc
            experience_sources.append({"uri": uri, "sha256": digest, "stat": stat})
        return {"schema": GRAPH_SCHEMA, "units": units, "experience_sources": sorted(experience_sources, key=lambda x: x["uri"])}

    def _experience(self, doc: dict[str, Any]) -> dict[str, Any] | None:
        meta = doc["metadata"]
        if meta.get("data_schema") != "eds-experience/v1":
            return None
        sources = meta.get("sources") or []
        source = sources[0] if sources else {}
        uri = source.get("uri")
        if not isinstance(uri, str) or not uri.strip() or Path(uri).is_absolute():
            raise GraphError(f"experience source URI is not a safe relative path: {uri!r}")
        target = (self.kb.root / uri).resolve()
        if not target.is_relative_to(self.kb.root.resolve()):
            raise GraphError(f"experience source escapes knowledge root: {uri}")
        try:
            raw, stat = _read_stable(target)
        except OSError as exc:
            raise GraphError(f"experience source is missing: {uri}") from exc
        digest = hashlib.sha256(raw).hexdigest()
        if source.get("sha256") != digest:
            raise GraphError(f"experience source hash mismatch: {uri}; sync required")
        try:
            record = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GraphError(f"experience source is not valid JSON: {uri}") from exc
        try:
            record = validate_iteration(record)
        except ExperienceError as exc:
            raise GraphError(f"invalid experience source {uri}: {exc}") from exc
        if str(record.get("id")) != str(meta["id"]) or str(record.get("version")) != str(meta["version"]):
            raise GraphError(f"experience source identity mismatch: {uri}")
        return {"record": record, "uri": uri, "sha256": digest, "stat": stat}

    @staticmethod
    def _node(connection: sqlite3.Connection, label: str, props: dict[str, Any]) -> None:
        names = ", ".join(f"{key}: ${key}" for key in props)
        _cypher(connection, f"CREATE (n:{label} {{{names}}})", props)

    @staticmethod
    def _edge(connection: sqlite3.Connection, source: str, target: str, label: str, props: dict[str, Any]) -> None:
        props = {"edge_from": source, "edge_to": target, **props}
        _cypher(connection, f"MATCH (a:EDSNode {{key:$source}}), (b:EDSNode {{key:$target}}) "
                 f"CREATE (a)-[:{label} {{{', '.join(f'{k}: ${k}' for k in props)}}}]->(b)",
                 {"source": source, "target": target, **props})

    def _build(self, paths: list[str], docs: dict[str, dict[str, Any]], temporary: Path) -> dict[str, Any]:
        snapshot = self._source_snapshot(paths, docs)
        excluded = {_key(d["metadata"]["id"], d["metadata"]["version"])
                    for d in docs.values() if d["metadata"]["type"] == "preference"}
        units = {(_key(str(d["metadata"]["id"]), str(d["metadata"]["version"]))): d
                 for d in docs.values() if d["metadata"].get("type") != "preference"}
        marker_keys: set[str] = set()
        with closing(sqlite3.connect(temporary)) as connection:
            _load(connection)
            _cypher(connection, "RETURN 1 AS ok")  # initialize GraphQLite schema
            connection.execute("CREATE TABLE graph_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            for key, doc in units.items():
                meta = doc["metadata"]
                self._node(connection, "EDSNode", {"key": key, "kind": "unit", "id": str(meta["id"]),
                    "version": str(meta["version"]), "type": meta["type"], "title": meta["title"],
                    "path": doc["path"], "content_hash": doc["content_hash"], "owner_key": key})
            for key, doc in units.items():
                meta = doc["metadata"]
                for relation in meta.get("relations", []):
                    target = _key(str(relation["id"]), str(relation["version"]))
                    if target in excluded:
                        continue
                    if target not in units:
                        target = "ref:" + key + ":" + target
                        if target not in marker_keys:
                            self._node(connection, "EDSNode", {"key": target, "kind": "missing_ref",
                                "id": str(relation["id"]), "version": str(relation["version"]), "type": "missing_ref",
                                "title": target, "path": "", "content_hash": "", "owner_key": key})
                            marker_keys.add(target)
                    self._edge(connection, key, target, "EDSLink", {"relation": relation["type"],
                        "relation_type": relation["type"], "target_id": str(relation["id"]),
                        "target_version": str(relation["version"])})
                experience = self._experience(doc)
                if experience is None:
                    continue
                record = experience["record"]
                for index, evaluation in enumerate(record.get("method_evaluations", [])):
                    ev_key = f"evaluation:{key}:{index}"
                    ev_props = {"key": ev_key, "kind": "evaluation", "id": record["id"],
                                "version": str(record["version"]), "index": str(index),
                                "knowledge_ref": evaluation["knowledge_ref"], "effect": evaluation["effect"],
                                "evidence_origin": evaluation["evidence_origin"],
                                "owner_key": key, "evaluation_json": _json(evaluation)}
                    self._node(connection, "EDSNode", ev_props)
                    self._edge(connection, key, ev_key, "EDSLink", {"relation": "has_evaluation", "relation_type": "has_evaluation"})
                    ref = evaluation["knowledge_ref"]
                    rid, rver = ref.rsplit("@", 1)
                    method_key = _key(rid, rver)
                    if method_key in excluded:
                        continue
                    if method_key not in units:
                        method_key = "ref:" + key + ":" + method_key
                        if method_key not in marker_keys:
                            self._node(connection, "EDSNode", {"key": method_key, "kind": "missing_ref", "id": rid,
                                "version": rver, "type": "missing_ref", "title": method_key, "path": "", "content_hash": "",
                                "owner_key": key})
                            marker_keys.add(method_key)
                    self._edge(connection, ev_key, method_key, "EDSLink", {"relation": "evaluates_method", "relation_type": "evaluates_method"})
            if self._source_snapshot(paths, docs) != snapshot:
                raise GraphError("experience source changed during graph build; retry graph-sync")
            connection.executemany("INSERT INTO graph_meta VALUES (?, ?)", [("schema", GRAPH_SCHEMA), ("snapshot", _json(snapshot))])
            connection.commit()
            nodes = connection.execute("SELECT count(*) FROM nodes").fetchone()[0]
            edges = connection.execute("SELECT count(*) FROM edges").fetchone()[0]
            connection.execute("INSERT INTO graph_meta VALUES ('counts', ?)", (_json({"nodes": nodes, "edges": edges}),))
            connection.commit()
        return {"backend": "graphqlite", "path": str(self.path), "indexed": len(units), "nodes": nodes, "edges": edges, "rebuilt": True}

    def sync(self, force: bool = False, *, _sqlite_ready=False) -> dict[str, Any]:
        self._require_runtime()
        # Keep the normal SQLite index authoritative before taking the shared
        # publication lock for the graph replacement.
        if not _sqlite_ready:
            self.kb.sync()
        with self.kb._lock():
            if self.path.is_file() and not force:
                current = self.status()
                if current.get("indexed") and not current.get("stale"):
                    return {**current, "rebuilt": False}
            self.kb._light_health(check_sources=True)
            paths = self.kb._read_registry()
            docs, missing = self.kb._documents(paths)
            if missing:
                raise GraphError(f"knowledge sources missing; sync required: {missing}")
            self.kb.cache_root.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix="graph.", suffix=".sqlite3", dir=self.kb.cache_root)
            os.close(fd)
            temporary = Path(name)
            try:
                result = self._build(paths, docs, temporary)
                self.kb._light_health(check_sources=True)
                os.replace(temporary, self.path)
                return result
            finally:
                temporary.unlink(missing_ok=True)

    def _read_meta(self) -> dict[str, Any]:
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as connection:
            _load(connection)
            connection.execute("PRAGMA query_only=ON")
            rows = connection.execute("SELECT key,value FROM graph_meta").fetchall()
            metadata = {key: value for key, value in rows}
            if metadata.get("schema") != GRAPH_SCHEMA:
                raise GraphError("unsupported graph schema; run graph-sync --force")
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise GraphError("corrupt graph cache; run graph-sync --force")
            counts = {name: connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
                      for name in ("nodes", "edges")}
            if counts != json.loads(metadata.get("counts", "null")):
                raise GraphError("graph projection is incomplete; run graph-sync --force")
        return metadata

    def status(self) -> dict[str, Any]:
        return self._health(full=True)[0]

    def _health(self, *, full=False) -> tuple[dict[str, Any], dict[str, Any]]:
        result = {**runtime_status(), "path": str(self.path), "exists": self.path.is_file(), "indexed": False, "stale": False}
        docs = {}
        if graphqlite is None or not self.path.is_file():
            if graphqlite is None:
                result["reason"] = runtime_status()["reason"]
            result.setdefault("reason", "graph index missing; run graph-sync")
            return result, docs
        try:
            meta = self._read_meta()
            self.kb._light_health(check_sources=True)
            result.update(indexed=True, schema=meta.get("schema"), **json.loads(meta["counts"]))
            paths = self.kb._read_registry()
            docs, missing = self.kb._documents(paths)
            current = self._source_snapshot(paths, docs, full=full)
            recorded = json.loads(meta.get("snapshot", "{}"))
            result["source_fingerprint"] = hashlib.sha256(meta["snapshot"].encode("utf-8")).hexdigest()
            result["stale"] = bool(missing) or current != recorded
            result["missing_files"] = missing
            if result["stale"]:
                result["reason"] = "graph source changed; run graph-sync"
        except (OSError, ValueError, sqlite3.DatabaseError, KnowledgeError) as exc:
            result["error"] = str(exc)
            result["stale"] = True
        return result, docs

    def _candidate_filter(self, meta: dict[str, Any], filters: dict[str, Any]) -> bool:
        if meta.get("type") == "preference":
            return False
        route = knowledge_route(filters.get("question"), filters.get("stage"))
        selected = [filters["type"]] if filters.get("type") else route["selected_types"]
        if selected is not None and meta["type"] not in selected:
            return False
        for field in ("domain", "project"):
            if filters.get(field) is not None and meta.get(field) != filters[field]:
                return False
        return True

    def search(self, query: str, limit: int = 10, depth: int = 2, max_nodes: int = 100,
               relation_types: list[str] | set[str] | None = None, **filters: Any) -> dict[str, Any]:
        self._require_runtime()
        if filters.get("type") == "preference" or filters.get("preference_status") is not None:
            raise GraphError("graph search excludes preferences; use kb search or an active preset")
        if (type(limit) is not int or not 1 <= limit <= 100 or type(depth) is not int or not 0 <= depth <= 3
                or type(max_nodes) is not int or not 1 <= max_nodes <= 100):
            raise GraphError("limit must be 1..100, depth 0..3, max_nodes 1..100 integers")
        if relation_types is not None and (not isinstance(relation_types, (list, tuple, set))
                or any(not isinstance(value, str) or not value.strip() for value in relation_types)):
            raise GraphError("relation_types must contain nonempty relation names")
        state, docs = self._health()
        if not state["indexed"] or state["stale"]:
            raise GraphError(state.get("error") or state.get("reason") or "graph index unavailable; run graph-sync")
        # Reuse the same routing/filter contract as FTS. Preferences are excluded
        # before choosing seeds, so private style records cannot consume the seed budget.
        candidates = self.kb.search(query, limit=1000, **filters)
        by_key = {_key(d["metadata"]["id"], d["metadata"]["version"]): d for d in docs.values()
                  if self._candidate_filter(d["metadata"], filters)}
        seeds = [item for item in candidates if _key(item["id"], item["version"]) in by_key][:min(5, limit, max_nodes)]
        queue = deque()
        nodes, paths, levels = {}, {}, {}
        for seed in seeds:
            key = _key(seed["id"], seed["version"])
            nodes[key] = {"key": key, "kind": "unit", "id": seed["id"], "version": seed["version"], "owner_key": key}
            paths[key], levels[key] = [], 0
            queue.append(key)
        truncated = False
        edges = {}
        edge_budget = max_nodes * 4
        allowed = list(by_key)
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as connection:
            _load(connection)
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            captured = connection.execute("SELECT value FROM graph_meta WHERE key='snapshot'").fetchone()
            if captured is None or hashlib.sha256(captured[0].encode("utf-8")).hexdigest() != state["source_fingerprint"]:
                raise GraphError("graph changed during query; retry graph-search")
            while queue:
                current = queue.popleft()
                if levels[current] >= depth or nodes[current]["kind"] == "missing_ref":
                    continue
                where = "b.owner_key IN $allowed"
                params = {"key": current, "allowed": allowed}
                if relation_types is not None:
                    where += " AND r.relation_type IN $relations"
                    params["relations"] = sorted(set(relation_types))
                # Both the node budget and a proportional edge budget are enforced;
                # high-degree nodes cannot materialize an unbounded neighbor list.
                remaining = edge_budget - len(edges)
                rows = _cypher(connection, "MATCH (a:EDSNode {key:$key})-[r:EDSLink]-(b:EDSNode) WHERE " + where +
                    " RETURN b.key AS key, b.kind AS kind, b.id AS id, b.version AS version, "
                    "b.owner_key AS owner_key, b.index AS evaluation_index, b.evaluation_json AS evaluation_json, "
                    "r.relation_type AS relation_type, r.edge_from AS edge_from, r.edge_to AS edge_to "
                    f"ORDER BY key, relation_type LIMIT {remaining + 1}", params)
                if len(rows) > remaining:
                    truncated = True
                    rows = rows[:remaining]
                for row in rows:
                    target = row["key"]
                    if row["owner_key"] not in by_key:
                        continue
                    if target not in nodes:
                        if len(nodes) >= max_nodes:
                            truncated = True
                            continue
                        nodes[target] = row
                        paths[target], levels[target] = [], levels[current] + 1
                        queue.append(target)
                    edge = {"from": row["edge_from"], "to": row["edge_to"], "relation": row["relation_type"]}
                    identity = (edge["from"], edge["to"], edge["relation"])
                    edges[identity] = edge
                    # Record parallel/incoming edges with their original direction.
                    # Avoid cyclic and exponentially duplicated path combinations.
                    if levels[target] >= levels[current] and target != current:
                        prior = paths[current][0] if levels[current] > 0 and paths[current] else []
                        if any(target in (step["from"], step["to"]) for step in prior):
                            continue
                        next_path = prior + [{**edge, "via": current}]
                        if next_path not in paths[target] and len(paths[target]) < 4:
                            paths[target].append(next_path)
                if len(edges) >= edge_budget:
                    truncated = truncated or bool(queue)
                    break
        verified = {}
        experiences = {}
        # Every path owner, including an Evaluation whose feedback is outside the
        # hop limit, must pass the normal fixed-version source verification.
        for owner in {node["owner_key"] for node in nodes.values()}:
            doc = by_key[owner]
            meta = doc["metadata"]
            item = self.kb.read(meta["id"], version=meta["version"])
            if item is None or item["content_hash"] != doc["content_hash"]:
                raise GraphError("source changed during graph query; run graph-sync")
            verified[owner] = {name: item[name] for name in ("id", "version", "type", "title", "path", "content_hash")}
            experience = self._experience(doc)
            if experience is not None:
                experiences[owner] = experience["record"]["method_evaluations"]
        matches, evaluations, unresolved = [], [], []
        node_refs = {}
        for key, node in nodes.items():
            node_refs[key] = {"id": node["id"], "version": node["version"], "kind": node["kind"]}
            if node["kind"] == "unit":
                item = {**verified[key], "paths": paths[key]}
                if key in experiences:
                    item["evaluations"] = experiences[key]
                matches.append(item)
            elif node["kind"] == "evaluation":
                index = int(node["evaluation_index"])
                original = experiences.get(node["owner_key"], [])
                projected = node["evaluation_json"]
                if isinstance(projected, str):
                    projected = json.loads(projected)
                if index >= len(original) or original[index] != projected:
                    raise GraphError("evaluation projection differs from source; run graph-sync --force")
                node_refs[key]["evaluation_index"] = index
                evaluations.append({"source": verified[node["owner_key"]], "index": index,
                                    "evaluation": original[index], "paths": paths[key]})
            else:
                unresolved.append({"id": node["id"], "version": node["version"], "missing": True, "paths": paths[key]})
        return {"backend": "graphqlite", "status": state, "route": knowledge_route(filters.get("question"), filters.get("stage")),
                "matches": matches[:limit], "evaluations": evaluations, "unresolved_refs": unresolved,
                "seeds": [{key: seed[key] for key in ("id", "version", "path")} for seed in seeds],
                "nodes": node_refs, "edges": list(edges.values()), "visited_nodes": len(nodes),
                "truncated": truncated or len(matches) > limit}
