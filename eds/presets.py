"""Context-scoped execution snapshots over existing preference knowledge units.

Only explicit activation from references and save-default access knowledge.
Current/task read derived state, never retrieve history or create preferences.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from .knowledge import (KnowledgeBase, KnowledgeError, KNOWLEDGE_QUESTIONS,
                        KNOWLEDGE_STAGES, PREFERENCE_SCOPES, _metadata)

FORMAT = "eds-preset/v1"
TASK_FORMAT = "eds-task-preset/v1"
STATE_FORMAT = "eds-presets/v1"
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeError(f"{label} must be nonempty text")
    return value


def _context(context):
    allowed = {"domain", "question", "stage", "user", "team", "project"}
    if not isinstance(context, dict) or set(context) - allowed:
        raise KnowledgeError("context must contain only domain/question/stage/user/team/project")
    result = {key: _text(value, f"context.{key}") for key, value in context.items()}
    if not result.get("domain") or result.get("question") not in KNOWLEDGE_QUESTIONS:
        raise KnowledgeError("context requires domain and a supported question")
    if "stage" in result and result["stage"] not in KNOWLEDGE_STAGES:
        raise KnowledgeError("unsupported context.stage")
    if not any(result.get(key) for key in PREFERENCE_SCOPES):
        raise KnowledgeError("context requires an actual user, team, or project identity")
    return result


def _values(values, label="values"):
    if not isinstance(values, dict):
        raise KnowledgeError(f"{label} must be an object")
    for key, value in values.items():
        _text(key, f"{label} key")
        _text(value, f"{label}.{key}")
    return dict(sorted(values.items()))


def _conditions(conditions, context, name):
    if not isinstance(conditions, (dict, list)):
        raise KnowledgeError("preference conditions must be an object or list")
    if isinstance(conditions, dict):
        process_routes = {"2d-drawing": "drawing", "3d-modeling": "cad-modeling", "delivery": "delivery"}
        route = process_routes.get(conditions.get("process")) if isinstance(conditions.get("process"), str) else None
        if route is not None and route != context["question"]:
            raise KnowledgeError("preference process does not match the task question")
        if conditions.get("execution_preset", name) != name:
            raise KnowledgeError("preference belongs to a different named preset")


def _stable_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _seal(body):
    result = copy.deepcopy(body)
    result["revision"] = _stable_hash(body)
    result["hash"] = result["revision"]
    return result


def _read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise KnowledgeError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise KnowledgeError(f"nonfinite JSON value: {value}")

    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=pairs,
                      parse_constant=constant)


def validate_snapshot(snapshot):
    """Verify provenance and effective values without knowledge I/O."""
    if not isinstance(snapshot, dict) or snapshot.get("format") not in {FORMAT, TASK_FORMAT}:
        raise KnowledgeError("unsupported preset snapshot format")
    common = {"format", "name", "context", "values", "revision", "hash"}
    expected = common | ({"sources"} if snapshot["format"] == FORMAT else {"base", "overrides"})
    if set(snapshot) != expected:
        raise KnowledgeError("snapshot fields are missing or unsupported")
    _text(snapshot["name"], "snapshot.name")
    context = _context(snapshot["context"])
    values = _values(snapshot["values"])
    body = {key: value for key, value in snapshot.items() if key not in {"revision", "hash"}}
    if snapshot["revision"] != _stable_hash(body) or snapshot["hash"] != snapshot["revision"]:
        raise KnowledgeError("preset snapshot hash mismatch")
    if snapshot["format"] == TASK_FORMAT:
        base = snapshot["base"]
        if not isinstance(base, dict) or base.get("format") != FORMAT:
            raise KnowledgeError("task requires a fixed base preset")
        validate_snapshot(base)
        if base["context"] != context or base["name"] != snapshot["name"]:
            raise KnowledgeError("task and base preset context/name differ")
        merged = {**base["values"], **_values(snapshot["overrides"], "overrides")}
        if merged != values:
            raise KnowledgeError("task values differ from base plus overrides")
    else:
        if not isinstance(snapshot["sources"], list):
            raise KnowledgeError("snapshot sources must be an array")
        sourced = {}
        for ref in snapshot["sources"]:
            if not isinstance(ref, dict) or set(ref) != {"id", "version", "content_hash", "key", "value", "scope", "scope_id", "conditions"}:
                raise KnowledgeError("invalid preset source reference")
            for key, value in ref.items():
                if key != "conditions":
                    _text(value, f"source.{key}")
            _conditions(ref["conditions"], context, snapshot["name"])
            if not _HASH.fullmatch(ref["content_hash"]):
                raise KnowledgeError("source content_hash is invalid")
            if ref["scope"] not in PREFERENCE_SCOPES or context.get(ref["scope"]) != ref["scope_id"]:
                raise KnowledgeError("source is outside preset scope")
            if ref["key"] in sourced:
                raise KnowledgeError("duplicate preset source key")
            sourced[ref["key"]] = ref["value"]
        if sourced != values:
            raise KnowledgeError("preset values differ from source references")
    return copy.deepcopy(snapshot)


class PresetStore:
    def __init__(self, root, kb=None):
        self.root = Path(root).resolve()
        repository = Path(__file__).resolve().parent.parent
        if any(self.root.is_relative_to(repository / folder)
               for folder in ("skills", ".agents/skills", "execution-skills")):
            raise KnowledgeError("personal presets must be outside distributable skill directories")
        self.kb = kb or KnowledgeBase(self.root)
        if self.kb.root != self.root:
            raise KnowledgeError("preset and knowledge roots differ")
        self.directory = self.root / ".eds-presets"
        self.state_path = self.directory / "state.json"

    def _lock(self):
        # Reuse the OS-owned lock in a separate directory; no second index/store.
        return KnowledgeBase(self.directory)._lock()

    def _check_paths(self):
        if not self.state_path.resolve().is_relative_to(self.root):
            raise KnowledgeError("preset state escapes the knowledge workspace")

    def _read_state(self):
        self._check_paths()
        if not self.state_path.exists():
            return {"schema": STATE_FORMAT, "presets": {}, "active": {}}
        state = _read_json(self.state_path)
        if (not isinstance(state, dict) or set(state) != {"schema", "presets", "active"}
                or state["schema"] != STATE_FORMAT or not isinstance(state["presets"], dict)
                or not isinstance(state["active"], dict)):
            raise KnowledgeError("invalid preset state")
        for key, snapshot in state["presets"].items():
            validate_snapshot(snapshot)
            if snapshot["format"] != FORMAT or key != self._preset_key(snapshot["name"], snapshot["context"]):
                raise KnowledgeError("invalid named preset identity")
        for key, selected in state["active"].items():
            snapshot = state["presets"].get(selected) if isinstance(selected, str) else None
            if snapshot is None or key != _stable_hash(snapshot["context"]):
                raise KnowledgeError("invalid active preset context")
        return state

    def _write_state(self, state):
        self._check_paths()
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="state.", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.state_path)
        finally:
            Path(name).unlink(missing_ok=True)

    @staticmethod
    def _preset_key(name, context):
        return _stable_hash({"name": name, "context": context})

    @staticmethod
    def _source(unit, context, name):
        meta = unit["metadata"]
        if (meta.get("type") != "preference" or meta.get("preference_status") != "confirmed"
                or meta.get("origin") != "explicit" or unit.get("superseded")):
            raise KnowledgeError("preference must be confirmed explicit and not superseded")
        if not KnowledgeBase._preference_scope_matches(meta, context):
            raise KnowledgeError("preference is outside the selected scope/domain/project/question")
        _conditions(meta["conditions"], context, name)
        return {"id": unit["id"], "version": unit["version"], "content_hash": unit["content_hash"],
                "key": meta["preference_key"], "value": meta["value"],
                "scope": meta["scope"], "scope_id": meta["scope_id"], "conditions": copy.deepcopy(meta["conditions"])}

    @staticmethod
    def _snapshot(name, context, sources):
        sources = sorted(sources, key=lambda ref: ref["key"])
        snapshot = _seal({"format": FORMAT, "name": name, "context": context, "sources": sources,
                          "values": {ref["key"]: ref["value"] for ref in sources}})
        return validate_snapshot(snapshot)

    def activate(self, name, *, context, refs=None):
        name, context = _text(name, "name"), _context(context)
        self._check_paths()
        with self._lock():
            state = self._read_state()
            key = self._preset_key(name, context)
            if refs is None:
                if key not in state["presets"]:
                    raise KnowledgeError("preset is not compiled for this context; supply explicit refs ([] starts empty)")
                snapshot = state["presets"][key]
            else:
                if not isinstance(refs, list):
                    raise KnowledgeError("refs must be an array")
                catalog = {(unit["id"], unit["version"]): unit for unit in self.kb.preference_catalog()} if refs else {}
                sources, seen = [], set()
                for ref in refs:
                    if not isinstance(ref, dict) or set(ref) != {"id", "version"}:
                        raise KnowledgeError("each reference requires only id and version")
                    identity = (_text(ref["id"], "ref.id"), _text(ref["version"], "ref.version"))
                    if identity not in catalog:
                        raise KnowledgeError(f"preference not found: {identity}")
                    source = self._source(catalog[identity], context, name)
                    if source["key"] in seen:
                        raise KnowledgeError(f"conflicting preference key: {source['key']}")
                    seen.add(source["key"])
                    sources.append(source)
                snapshot = self._snapshot(name, context, sources)
            if state["presets"].get(key) != snapshot or state["active"].get(_stable_hash(context)) != key:
                state["presets"][key] = snapshot
                state["active"][_stable_hash(context)] = key
                self._write_state(state)
            return copy.deepcopy(snapshot)

    def current(self, *, context):
        context = _context(context)
        state = self._read_state()
        key = state["active"].get(_stable_hash(context))
        return copy.deepcopy(state["presets"][key]) if key is not None else None

    def for_task(self, *, context, overrides=None):
        overlay = _values({} if overrides is None else overrides, "overrides")
        base = self.current(context=context)
        if base is None:
            raise KnowledgeError("no active preset for this context")
        return validate_snapshot(_seal({"format": TASK_FORMAT, "name": base["name"],
                                       "context": base["context"], "base": base, "overrides": overlay,
                                       "values": {**base["values"], **overlay}}))

    def save_default(self, *, context, overrides, source, scope="user"):
        context, overrides = _context(context), _values(overrides, "overrides")
        _text(source, "source")
        if scope not in PREFERENCE_SCOPES or not context.get(scope):
            raise KnowledgeError("save scope requires its actual identity in context")
        self._check_paths()
        with self._lock():
            state = self._read_state()
            selected = state["active"].get(_stable_hash(context))
            if selected is None:
                raise KnowledgeError("activate a preset before saving a default")
            base = state["presets"][selected]
            changes = {key: value for key, value in overrides.items() if base["values"].get(key) != value}
            if not changes:
                return copy.deepcopy(base)
            sources = {ref["key"]: ref for ref in base["sources"]}
            pending = []
            for key, value in changes.items():
                identity = {"scope": scope, "scope_id": context[scope], "key": key, "name": base["name"],
                            **{field: context[field] for field in ("domain", "question", "stage", "project") if field in context}}
                uid = "preset-" + _stable_hash(identity)
                old = sources.get(key)
                own = old is not None and old["id"] == uid
                version = str(int(old["version"]) + 1) if own else "1"
                relations = ([{"type": "supersedes" if own else "derived_from", "id": old["id"],
                               "version": old["version"]}] if old else [])
                metadata = {"id": uid, "version": version, "type": "preference", "title": key,
                            "sources": [{"uri": "user:explicit-preference", "locator": source}],
                            "conditions": {"execution_preset": base["name"]}, "relations": relations,
                            "preference_key": key, "value": value, "scope": scope, "scope_id": context[scope],
                            "preference_status": "confirmed", "origin": "explicit",
                            **{field: context[field] for field in ("domain", "question", "stage", "project") if field in context}}
                content = "<!-- eds-knowledge: " + json.dumps(metadata, ensure_ascii=False) + " -->\n\n" + value + "\n"
                _metadata(content)
                raw = content.encode("utf-8")
                path = self.directory / "preferences" / f"{uid}@{version}.md"
                if not path.resolve().is_relative_to(self.root):
                    raise KnowledgeError("preference path escapes the knowledge workspace")
                if path.exists() and path.read_bytes() != raw:
                    raise KnowledgeError("preference revision already exists with different content; reactivate current refs before saving")
                pending.append((path, raw))
                sources[key] = {"id": uid, "version": version, "content_hash": hashlib.sha256(raw).hexdigest(),
                                "key": key, "value": value, "scope": scope, "scope_id": context[scope],
                                "conditions": metadata["conditions"]}
            snapshot = self._snapshot(base["name"], context, list(sources.values()))
            for path, raw in pending:
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    with path.open("xb") as handle:
                        handle.write(raw)
                        handle.flush()
                        os.fsync(handle.fileno())
            try:
                registered = self.kb.register_many([path for path, _ in pending])
                if any(not item["indexed"] for item in registered):
                    raise KnowledgeError("preference index is incomplete")
                state["presets"][selected] = snapshot
                self._write_state(state)
            except (OSError, ValueError) as exc:
                raise KnowledgeError("defaults were not activated; saved source files may remain. Retry the same save/source to reconcile: " + str(exc)) from exc
            return snapshot


__all__ = ["PresetStore", "validate_snapshot", "FORMAT", "TASK_FORMAT"]
