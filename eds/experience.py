"""Model-independent publication of reusable engineering experience.

This module deliberately keeps the source Study snapshot separate from the
derived Markdown knowledge unit.  No model, embedding or endpoint selection is
performed here; downstream retrieval/training projections can be rebuilt.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .knowledge import KnowledgeBase, KnowledgeError


SCHEMA = "eds-experience/v1"
_REF_RE = re.compile(r"^(.+)@(\d+)$")
_KNOWLEDGE_REF_RE = re.compile(r"^[^@\s]+@[^@\s]+$")
_ENTITY_KINDS = {"design", "proposal", "realization", "experiment", "evidence", "assessment", "mapping", "decision"}
_ENTITY_REF_FIELDS = {f"{kind}_{suffix}" for kind in _ENTITY_KINDS for suffix in ("ref", "refs")} | {"refs", "input_refs", "candidate_refs"}
_STATUSES = {"planned", "submitting", "submitted", "running", "unknown", "completed", "failed", "cancelled"}
_BLOCKED_VERIFIED = {"planned", "submitting", "submitted", "running", "unknown"}


class ExperienceError(ValueError):
    """A malformed, unsafe or contradictory experience record."""


def _jsonable(value: Any) -> None:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ExperienceError("experience values must be finite JSON") from exc


def _canonical(value: Any) -> str:
    _jsonable(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExperienceError(f"{field} must be nonempty text")
    return value.strip()


def _ref(value: Any, field: str) -> str:
    value = _text(value, field)
    if not _REF_RE.fullmatch(value):
        raise ExperienceError(f"{field} must include an explicit @version")
    return value


def _time(value):
    try:
        timestamp = datetime.fromisoformat(value)
        return timestamp if timestamp.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _entity_map(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entities = state.get("entities")
    if not isinstance(entities, list):
        raise ExperienceError("Study entities must be a list")
    result = {}
    for entity in entities:
        if not isinstance(entity, dict) or not isinstance(entity.get("ref"), str):
            raise ExperienceError("Study contains an invalid entity")
        if entity["ref"] in result:
            raise ExperienceError(f"duplicate Study entity: {entity['ref']}")
        result[entity["ref"]] = entity
    return result


def _assessment(state: dict[str, Any], assessment_ref: str) -> dict[str, Any]:
    ref = _ref(assessment_ref, "assessment_ref")
    entity = _entity_map(state).get(ref)
    if entity is None or entity.get("kind") != "assessment":
        raise ExperienceError("assessment_ref must identify an existing assessment")
    return entity


def _entity_closure(state: dict[str, Any], root: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    entities = _entity_map(state)
    selected: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    pending = [root["ref"]]
    while pending:
        current_ref = pending.pop(0)
        if current_ref in selected:
            continue
        current = entities.get(current_ref)
        if current is None:
            missing.append(current_ref)
            continue
        selected[current_ref] = current
        payload = current.get("payload", {})
        if not isinstance(payload, dict):
            raise ExperienceError(f"{current_ref} payload must be an object")
        for key, value in payload.items():
            if key not in _ENTITY_REF_FIELDS:
                continue
            values = value if isinstance(value, list) else [value]
            for item in values:
                if isinstance(item, str) and _REF_RE.fullmatch(item) and item in entities:
                    pending.append(item)
                elif isinstance(item, str) and item:
                    missing.append(item)
    return [copy.deepcopy(selected[key]) for key in sorted(selected)], sorted(set(missing))


def _runs_for(state: dict[str, Any], closure: list[dict[str, Any]], assessment: dict[str, Any]) -> list[dict[str, Any]]:
    runs = state.get("runs", [])
    if not isinstance(runs, list):
        raise ExperienceError("Study runs must be a list")
    refs = {entity["ref"] for entity in closure}
    explicit_ids: set[str] = set()
    for entity in closure:
        payload = entity.get("payload", {})
        if not isinstance(payload, dict):
            continue
        for key in ("run_id", "run_ids"):
            values = payload.get(key, [])
            values = values if isinstance(values, list) else [values]
            explicit_ids.update(value for value in values if isinstance(value, str))
    cutoff = _time(assessment.get("created_at"))
    selected = []
    for run in runs:
        if not isinstance(run, dict):
            raise ExperienceError("Study contains an invalid Run")
        created = _time(run.get("created_at"))
        if cutoff and created and created > cutoff:
            continue
        linked = run.get("experiment_ref") in refs or run.get("run_id") in explicit_ids
        if linked:
            item = copy.deepcopy(run)
            if not cutoff or not created:
                item["temporal_status"] = "unknown"
            history = item.get("history")
            if cutoff and isinstance(history, list):
                dated = [(entry, _time(entry.get("at"))) for entry in history if isinstance(entry, dict)]
                item["history"] = [entry for entry, when in dated if when and when <= cutoff]
                undated = [entry for entry, when in dated if when is None]
                if undated:
                    item["unplaced_history"] = undated
                    item["temporal_status"] = "unknown"
                retained = item["history"]
                item["status"] = retained[-1]["status"] if retained else "unknown"
                item["task_id"] = retained[-1].get("task_id") if retained else None
                item["updated_at"] = retained[-1]["at"] if retained else None
                item["output"] = next((entry.get("output") for entry in reversed(retained)
                                       if entry.get("output") is not None), None)
                if not retained:
                    item["temporal_status"] = "unknown"
            elif cutoff:
                item.update(status="unknown", output=None, task_id=None, updated_at=None, temporal_status="unknown")
            selected.append(item)
    selected.sort(key=lambda item: (item.get("created_at", ""), item.get("run_id", "")))
    return selected


def _close_run_entities(state: dict[str, Any], closure: list[dict[str, Any]], runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entities = _entity_map(state)
    selected = {item["ref"]: item for item in closure}
    pending: list[str] = []
    for run in runs:
        for key in ("experiment_ref", "input_refs"):
            values = run.get(key, [])
            values = values if isinstance(values, list) else [values]
            pending.extend(value for value in values if isinstance(value, str))
    while pending:
        ref = pending.pop(0)
        if ref in selected:
            continue
        entity = entities.get(ref)
        if entity is None:
            continue
        selected[ref] = entity
        payload = entity.get("payload", {})
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key in _ENTITY_REF_FIELDS:
                    values = value if isinstance(value, list) else [value]
                    pending.extend(item for item in values if isinstance(item, str) and item in entities)
    return [copy.deepcopy(selected[key]) for key in sorted(selected)]


def _guidance(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("experience", {})
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ExperienceError("assessment.experience must be an object")
    allowed = {"status", "summary", "recommendation", "applicability", "non_applicability",
               "failure_modes", "repair_actions", "counterexamples", "validation_refs", "confidence"}
    result = {key: copy.deepcopy(value[key]) for key in value if key in allowed}
    status = result.get("status", "unverified")
    if status not in {"unverified", "verified", "invalidated"}:
        raise ExperienceError("experience.status must be unverified, verified or invalidated")
    result["status"] = status
    if status == "verified":
        refs = result.get("validation_refs")
        if not isinstance(refs, list) or not refs:
            raise ExperienceError("verified experience requires validation_refs")
    return result


def validate_iteration(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        raise ExperienceError("unsupported experience schema")
    for key in ("id", "version", "study_id", "assessment_ref", "title", "context", "actions",
                "observations", "analysis", "guidance", "reuse", "provenance"):
        if key not in record:
            raise ExperienceError(f"experience requires {key}")
    _text(record["id"], "experience.id")
    if isinstance(record["version"], bool) or not isinstance(record["version"], int) or record["version"] < 1:
        raise ExperienceError("experience.version must be a positive integer")
    _ref(record["assessment_ref"], "assessment_ref")
    for key in ("context", "actions", "observations", "analysis", "guidance", "reuse", "provenance"):
        if not isinstance(record[key], dict):
            raise ExperienceError(f"experience.{key} must be an object")
    guidance = record["guidance"]
    status = guidance.get("status", "unverified")
    if status not in {"unverified", "verified", "invalidated"}:
        raise ExperienceError("guidance.status is unsupported")
    evidence_refs = {item.get("ref") for item in record["observations"].get("entities", [])
                     if isinstance(item, dict) and item.get("kind") == "evidence"}
    if status == "verified":
        refs = guidance.get("validation_refs")
        if not isinstance(refs, list) or not refs or any(ref not in evidence_refs for ref in refs):
            raise ExperienceError("verified guidance requires validation_refs")
    statuses = record["actions"].get("run_statuses", [])
    runs = record["actions"].get("runs", [])
    actual_statuses = [run.get("status") for run in runs if isinstance(run, dict)]
    if statuses != actual_statuses:
        raise ExperienceError("actions.run_statuses must match actions.runs")
    if not isinstance(statuses, list) or any(status not in _STATUSES for status in statuses):
        raise ExperienceError("actions.run_statuses contains an unsupported status")
    if status == "verified" and any(item in _BLOCKED_VERIFIED for item in statuses):
        raise ExperienceError("experience with pending or unknown Runs cannot be verified")
    methods = record.get("method_evaluations", [])
    if not isinstance(methods, list):
        raise ExperienceError("experience.method_evaluations must be a list")
    effects = {"improved", "degraded", "mixed", "unchanged", "inconclusive", "not_tested"}
    origins = {"literature", "runtime", "inference"}
    for item in methods:
        if not isinstance(item, dict):
            raise ExperienceError("each method evaluation must be an object")
        for key in ("knowledge_ref", "product_features", "conditions", "parameter_changes", "comparison",
                    "effect", "evidence_origin", "evidence_refs", "limitations"):
            if key not in item:
                raise ExperienceError(f"method evaluation requires {key}")
        if not isinstance(item["knowledge_ref"], str) or not _KNOWLEDGE_REF_RE.fullmatch(item["knowledge_ref"]):
            raise ExperienceError("method evaluation requires a fixed knowledge reference")
        if item["effect"] not in effects or item["evidence_origin"] not in origins:
            raise ExperienceError("method evaluation effect or evidence_origin is unsupported")
        if not isinstance(item["evidence_refs"], list) or any(not isinstance(ref, str) for ref in item["evidence_refs"]):
            raise ExperienceError("method evaluation evidence_refs must be a list")
        if item["effect"] not in {"inconclusive", "not_tested"} and not item["evidence_refs"]:
            raise ExperienceError("non-inconclusive method evaluation requires evidence_refs")
        if any(ref not in evidence_refs for ref in item["evidence_refs"]):
            raise ExperienceError("method evaluation evidence_refs must identify evidence entities")
        if item["evidence_origin"] == "inference" and item["effect"] not in {"inconclusive", "not_tested"}:
            raise ExperienceError("inference cannot claim a tested method effect")
        for key in ("product_features", "conditions", "parameter_changes", "comparison"):
            if not isinstance(item[key], (dict, list, str)):
                raise ExperienceError(f"method_evaluation.{key} must be structured JSON")
    relations = record.get("relations", [])
    if not isinstance(relations, list) or any(
        not isinstance(item, dict) or not all(isinstance(item.get(key), str) and item[key].strip()
                                              for key in ("id", "version", "type"))
        for item in relations
    ):
        raise ExperienceError("experience relations must contain id, version and type")
    _jsonable(record)
    normalized = copy.deepcopy(record)
    normalized.setdefault("method_evaluations", [])
    return normalized


def _context_as_of(state, assessment):
    top_fields = {"goal", "mode", "constraints", "facts", "assumptions", "gaps", "assets"}
    values = {key: copy.deepcopy(state.get(key, [])) for key in top_fields}
    context = copy.deepcopy(state.get("context", {}))
    cutoff = _time(assessment.get("created_at"))
    for event in reversed(state.get("events", [])):
        when = _time(event.get("at"))
        if cutoff is None or when is None or when <= cutoff:
            continue
        if event.get("type") in {"context", "summary"}:
            for key, previous in event.get("previous", {}).items():
                destination = values if event["type"] == "context" and key in top_fields else context
                if previous is None and destination is context:
                    destination.pop(key, None)
                else:
                    destination[key] = copy.deepcopy(previous)
    return values, context


def build_iteration(state: dict[str, Any], assessment_ref: str) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise ExperienceError("Study state must be an object")
    assessment = _assessment(state, assessment_ref)
    closure, missing = _entity_closure(state, assessment)
    runs = _runs_for(state, closure, assessment)
    while True:
        previous = ({item["ref"] for item in closure}, {item["run_id"] for item in runs})
        closure = _close_run_entities(state, closure, runs)
        runs = _runs_for(state, closure, assessment)
        if previous == ({item["ref"] for item in closure}, {item["run_id"] for item in runs}):
            break
    payload = assessment.get("payload", {})
    guidance = _guidance(payload)
    status = assessment.get("payload", {}).get("status", "") if isinstance(assessment.get("payload"), dict) else ""
    context, state_context = _context_as_of(state, assessment)
    assessment_conditions = payload.get("conditions", {}) if isinstance(payload, dict) else {}
    context.update({"conditions": copy.deepcopy(state_context.get("conditions", "unknown")),
                    "environment": copy.deepcopy(state_context.get("environment", "unknown")),
                    "product_features": copy.deepcopy(state_context.get("product_features", "unknown")),
                    "assessment_conditions": copy.deepcopy(assessment_conditions)})
    methods = []
    raw_methods = payload.get("experience", {}).get("method_evaluations", []) if isinstance(payload.get("experience"), dict) else []
    if not isinstance(raw_methods, list):
        raise ExperienceError("assessment.experience.method_evaluations must be a list")
    entity_refs = {entity["ref"] for entity in closure}
    for item in raw_methods:
        if not isinstance(item, dict):
            raise ExperienceError("method evaluation must be an object")
        evaluation = copy.deepcopy(item)
        evaluation.setdefault("product_features", "unknown")
        evaluation.setdefault("conditions", "unknown")
        evaluation.setdefault("parameter_changes", "unknown")
        evaluation.setdefault("comparison", "unknown")
        evaluation.setdefault("effect", "inconclusive")
        evaluation.setdefault("evidence_origin", "inference")
        evaluation.setdefault("evidence_refs", [])
        evaluation.setdefault("limitations", "unknown")
        if any(ref not in entity_refs for ref in evaluation["evidence_refs"]):
            raise ExperienceError("method evaluation evidence_refs must point into the selected Study closure")
        methods.append(evaluation)
    methods.sort(key=lambda item: item["knowledge_ref"])
    knowledge_refs = sorted({ref for entity in closure for ref in entity.get("payload", {}).get("knowledge_refs", [])
                             if isinstance(entity.get("payload", {}), dict) and isinstance(ref, str) and _KNOWLEDGE_REF_RE.fullmatch(ref)})
    knowledge_refs.extend(item["knowledge_ref"] for item in methods if item["knowledge_ref"] not in knowledge_refs)
    for ref in guidance.get("validation_refs", []) if isinstance(guidance.get("validation_refs"), list) else []:
        if ref not in entity_refs:
            raise ExperienceError("guidance validation_refs must point into the selected Study closure")
    record = {
        "schema": SCHEMA,
        "id": "experience-" + hashlib.sha256(f"{state.get('study_id')}\0{assessment['logical_ref']}".encode()).hexdigest()[:24],
        "version": int(assessment["version"]),
        "study_id": _text(state.get("study_id"), "study_id"),
        "assessment_ref": assessment["ref"],
        "title": f"{context.get('goal', 'Engineering iteration')} — {assessment['logical_ref']}",
        "context": context,
        "actions": {"assessment_status": status or "recorded", "entity_refs": [entity["ref"] for entity in closure],
                    "run_ids": [run.get("run_id") for run in runs if run.get("run_id")],
                    "run_statuses": [run.get("status") for run in runs], "runs": runs},
        "observations": {"entities": closure, "missing_refs": missing},
        "analysis": {"assessment": copy.deepcopy(payload), "interpretation": copy.deepcopy(payload.get("interpretation")) if isinstance(payload, dict) else None,
                     "interpretation_type": "assessment_judgment",
                     "next_action": copy.deepcopy(payload.get("next_action")) if isinstance(payload, dict) else None},
        "guidance": guidance,
        "method_evaluations": methods,
        "relations": [{"id": ref.rsplit("@", 1)[0], "version": ref.rsplit("@", 1)[1], "type": "related_to"}
                      for ref in knowledge_refs],
        "reuse": {"knowledge_refs": knowledge_refs,
                   "decision": copy.deepcopy(payload.get("knowledge_use", payload.get("reuse", "unknown")))
                   if isinstance(payload, dict) else "unknown"},
        "provenance": {"source": "StudyStore", "study_id": state["study_id"], "assessment_ref": assessment["ref"],
                        "assessment_created_at": assessment.get("created_at", "unknown"), "missing_refs": missing,
                        "context_basis": "Study context restored through recorded change events; unrecorded conditions remain unknown"},
    }
    return validate_iteration(record)


def _safe_path(root: Path, path: Path) -> Path:
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(root.resolve()):
        raise ExperienceError("experience output escapes knowledge root")
    return resolved


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="experience.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _compact_entity(entity: dict[str, Any]) -> dict[str, Any]:
    payload = entity.get("payload", {}) if isinstance(entity.get("payload"), dict) else {}
    result = {"ref": entity.get("ref"), "kind": entity.get("kind")}
    keep = {"question", "observations", "decision_rule", "observation", "differences", "interpretation", "next_action",
            "evidence_refs", "experiment_ref", "proposal_ref", "method_ref", "conditions", "status", "metrics",
            "failure", "limitations"}
    result["details"] = {key: _brief(payload[key]) for key in sorted(keep) if key in payload}
    return result


def _brief(value):
    """Bound the search projection; full values are retained in its JSON source."""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    if len(encoded) <= 1800:
        return value
    return {"preview": encoded[:1800], "truncated": True,
            "characters": len(encoded), "sha256": hashlib.sha256(encoded.encode()).hexdigest(),
            "full_value": "central JSON snapshot"}


def _compact_run(run: dict[str, Any]) -> dict[str, Any]:
    snapshot = run.get("input_snapshot", {}) if isinstance(run.get("input_snapshot"), dict) else {}
    arguments = snapshot.get("arguments")
    if isinstance(arguments, dict):
        arguments = {key: arguments[key] for key in list(arguments)[:12]}
    output = run.get("output") if isinstance(run.get("output"), (str, int, float, bool, type(None), dict, list)) else None
    return {"run_id": run.get("run_id"), "status": run.get("status"), "created_at": run.get("created_at"),
            "experiment_ref": run.get("experiment_ref"), "tool": snapshot.get("tool"),
            "capability": run.get("capability", snapshot.get("capability")), "arguments": _brief(arguments),
            "output": _brief(output), "temporal_status": run.get("temporal_status")}


def _markdown(record: dict[str, Any], source: str, source_hash: str) -> str:
    meta = {"id": record["id"], "version": str(record["version"]), "type": "feedback",
            "title": record["title"], "domain": record["context"].get("mode", "engineering"),
            "date": record["provenance"].get("assessment_created_at", "unknown"), "attribution": "study_assessment",
            "sources": [{"uri": source, "locator": "$/" + record["assessment_ref"], "sha256": source_hash}],
            "conditions": record["context"], "relations": record.get("relations", []),
            "experience_status": record["guidance"].get("status", "unverified"), "data_schema": SCHEMA}
    compact = {"entities": [_compact_entity(item) for item in record["observations"].get("entities", [])],
               "missing_refs": record["observations"].get("missing_refs", []),
               "runs": [_compact_run(run) for run in record["actions"].get("runs", [])]}
    lines = ["<!-- eds-knowledge: " + json.dumps(meta, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + " -->",
             "", "# " + record["title"], "", "## Context", "", "```json", json.dumps(record["context"], ensure_ascii=False, indent=2, sort_keys=True), "```", "",
             "## Iteration and observations", "", "```json", json.dumps(compact, ensure_ascii=False, indent=2, sort_keys=True), "```", "",
             "## Assessment and guidance", "", "```json", json.dumps({"analysis": record["analysis"], "guidance": record["guidance"], "method_evaluations": record["method_evaluations"]}, ensure_ascii=False, indent=2, sort_keys=True), "```", "",
             "## Provenance", "", "`" + source + "`", ""]
    return "\n".join(lines)


def publish_iteration(knowledge_root: str | os.PathLike[str], record: dict[str, Any]) -> dict[str, Any]:
    record = validate_iteration(record)
    kb = experience_library(knowledge_root)
    root = kb.root
    digest_key = hashlib.sha256(record["id"].encode()).hexdigest()[:24]
    directory = _safe_path(root, root / "iterations" / digest_key)
    snapshot_path = _safe_path(root, directory / f"v{record['version']}.json")
    markdown_path = _safe_path(root, directory / f"v{record['version']}.md")
    snapshot = copy.deepcopy(record)
    snapshot["provenance"] = {**snapshot["provenance"], "published_path": snapshot_path.relative_to(root).as_posix()}
    snapshot_bytes = (_canonical(snapshot) + "\n").encode("utf-8")
    source_hash = hashlib.sha256(snapshot_bytes).hexdigest()
    markdown = _markdown(snapshot, snapshot_path.relative_to(root).as_posix(), source_hash).encode("utf-8")
    lock = KnowledgeBase(kb.cache_root / ".experience-publication")._lock()
    with lock:
        if snapshot_path.exists() and snapshot_path.read_bytes() != snapshot_bytes:
            raise ExperienceError("experience version already exists with different content")
        if markdown_path.exists() and markdown_path.read_bytes() != markdown:
            raise ExperienceError("experience Markdown already exists with different content")
        if not snapshot_path.exists():
            _write_atomic(snapshot_path, snapshot_bytes)
        if not markdown_path.exists():
            _write_atomic(markdown_path, markdown)
        try:
            indexed = kb.register_many([markdown_path])[0]
        except (KnowledgeError, OSError) as exc:
            raise ExperienceError(f"experience saved but indexing is pending: {exc}") from exc
    return {"id": snapshot["id"], "version": snapshot["version"], "path": str(markdown_path),
            "snapshot_path": str(snapshot_path), "indexed": bool(indexed.get("indexed")),
            "hash": source_hash}


def experience_library(knowledge_root):
    kb = KnowledgeBase(knowledge_root)
    repository = Path(__file__).resolve().parent.parent
    if any(kb.root.is_relative_to(repository / folder)
           for folder in ("skills", ".agents/skills", "execution-skills")):
        raise ExperienceError("personal experience must be outside distributable skill directories")
    return kb


__all__ = ["SCHEMA", "ExperienceError", "build_iteration", "validate_iteration", "publish_iteration"]
