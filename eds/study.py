"""Atomic engineering records for Codex; no planner or backend transport.

Entities are immutable revisions. Runs retain append-only observation histories.
Mutations hold an OS lock, validate the records, then atomically replace JSON.
"""
from __future__ import annotations

import copy
import errno
import hashlib
import json
import math
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .presets import validate_snapshot


class StudyError(ValueError):
    """A malformed record, missing reference, or invalid state transition."""


def _validate_run_preset(snapshot: dict[str, Any], mode: str) -> None:
    if "execution_preset" not in snapshot:
        return
    preset = snapshot["execution_preset"]
    try:
        validate_snapshot(preset)
    except (ValueError, TypeError) as exc:
        raise StudyError(f"invalid execution preset: {exc}") from exc
    if preset.get("format") != "eds-task-preset/v1":
        raise StudyError("Run requires a pinned task preset, not a mutable active selection")
    if mode != "coupled" and preset["context"]["domain"] != mode:
        raise StudyError("execution preset domain differs from the Study mode")


KINDS = {"design", "proposal", "realization", "experiment", "evidence", "assessment", "mapping", "decision"}
MODES = {"cad", "cae", "coupled"}
EXTRACTION = {"once", "auto", "later", "skip"}
TERMINAL = {"completed", "failed", "cancelled"}
TRANSITIONS = {
    "planned": {"submitting", "cancelled"},
    "submitting": {"submitted", "running", "completed", "unknown", "failed", "cancelled"},
    "submitted": {"running", "completed", "failed", "unknown", "cancelled"},
    "running": {"completed", "failed", "unknown", "cancelled"},
    "unknown": {"submitted", "running", "completed", "failed", "cancelled"},
    "completed": set(), "failed": set(), "cancelled": set(),
}
STATUSES = set(TRANSITIONS)
# Only these top-level keys are internal entity relationships. Source, artifact
# and knowledge references are external and must not be reinterpreted.
ENTITY_RELATIONS = {f"{kind}_ref": kind for kind in KINDS}
ENTITY_RELATIONS.update({f"{kind}_refs": kind for kind in KINDS})
ENTITY_RELATIONS.update({"refs": None, "input_refs": None, "candidate_refs": None})
CONTEXT_FIELDS = {"goal", "mode", "constraints", "facts", "assumptions", "gaps", "assets"}
METRIC_FIELDS = {"elapsed_seconds", "human_inputs", "model_cost"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StudyError(f"{field} must be nonempty text")
    return value


def _json_value(value: Any) -> None:
    """Reject non-JSON values instead of silently coercing types or NaN."""
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, list):
        for item in value:
            _json_value(item)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _json_value(item)
        return
    raise StudyError("records require finite JSON values and string object keys")


def _canonical(value: Any) -> str:
    _json_value(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StudyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise StudyError(f"nonfinite JSON value: {value}")


def _timestamp(value: Any, field: str) -> str:
    _text(value, field)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise StudyError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise StudyError(f"{field} must include a timezone")
    return value


def _allowed_transition(previous: str, current: str) -> bool:
    return current in TRANSITIONS[previous] or (previous == current and current in {"submitted", "running", "unknown"})


class StudyStore:
    """One Study in root/study.json. The persistent .study.lock file is a
    sentinel; its OS lock is released even after abrupt process termination.
    """

    def __init__(self, root: str | os.PathLike[str], *, lock_timeout: float = 10.0):
        self.root = Path(root).resolve()
        self.path = self.root / "study.json"
        self.lock_path = self.root / ".study.lock"
        if type(lock_timeout) not in (int, float) or not math.isfinite(lock_timeout) or lock_timeout <= 0:
            raise StudyError("lock_timeout must be positive and finite")
        self.lock_timeout = lock_timeout

    @classmethod
    def create(cls, root: str | os.PathLike[str], goal: str, mode: str = "coupled", *,
               constraints: list[Any] | None = None, assets: list[dict[str, Any]] | None = None,
               facts: list[Any] | None = None, assumptions: list[Any] | None = None,
               gaps: list[Any] | None = None) -> "StudyStore":
        store = cls(root)
        mode = "coupled" if mode == "joint" else mode
        now = _now()
        state = {
            "schema": "eds-study/v1", "study_id": _uid("study"), "created_at": now, "updated_at": now,
            "goal": goal, "mode": mode, "constraints": constraints if constraints is not None else [],
            "facts": facts if facts is not None else [], "assumptions": assumptions if assumptions is not None else [],
            "gaps": gaps if gaps is not None else [], "assets": assets if assets is not None else [],
            "entities": [], "runs": [], "events": [], "preferences": {"extraction": "later"},
            "context": {}, "metrics": {"elapsed_seconds": None, "human_inputs": None, "model_cost": None},
        }
        store._validate_state(state)
        with store._lock():
            if store.path.exists():
                raise StudyError(f"study already exists: {store.path}")
            store._write(state)
        return store

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            deadline = time.monotonic() + self.lock_timeout
            locked = False
            try:
                while not locked:
                    try:
                        handle.seek(0)
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        locked = True
                    except OSError as exc:
                        if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                            raise
                        if time.monotonic() >= deadline:
                            raise StudyError("timed out acquiring study lock") from exc
                        time.sleep(0.01)
                yield
            finally:
                if locked:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _write(self, state: dict[str, Any]) -> None:
        state["updated_at"] = _now()
        self._validate_state(state)
        encoded = json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
        fd, temporary = tempfile.mkstemp(prefix="study.", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _read(self) -> dict[str, Any]:
        try:
            state = json.loads(self.path.read_text(encoding="utf-8-sig"),
                               parse_constant=_reject_constant, object_pairs_hook=_unique_object)
        except (OSError, json.JSONDecodeError, UnicodeError) as exc:
            raise StudyError(f"cannot read study: {exc}") from exc
        self._validate_state(state)
        return state

    @staticmethod
    def _split_ref(ref: str) -> tuple[str, int | None]:
        _text(ref, "reference")
        if "@" not in ref:
            if any(character.isspace() for character in ref):
                raise StudyError("logical references must not contain whitespace")
            return ref, None
        logical, version = ref.rsplit("@", 1)
        if not logical or "@" in logical or not version.isdigit() or int(version) < 1:
            raise StudyError("entity reference must be logical-id or logical-id@positive-version")
        if any(character.isspace() for character in logical):
            raise StudyError("logical references must not contain whitespace")
        return logical, int(version)

    @classmethod
    def _resolve(cls, state: dict[str, Any], ref: str, expected_kind: str | None = None) -> dict[str, Any]:
        logical, version = cls._split_ref(ref)
        entity = next((item for item in reversed(state["entities"])
                       if item["logical_ref"] == logical and (version is None or item["version"] == version)), None)
        if entity is None:
            raise StudyError(f"unknown entity reference: {ref}")
        if expected_kind is not None and entity["kind"] != expected_kind:
            raise StudyError(f"{ref} must reference {expected_kind}, not {entity['kind']}")
        return entity

    @staticmethod
    def _validate_payload(kind: str, payload: Any) -> None:
        if not isinstance(kind, str) or kind not in KINDS or not isinstance(payload, dict) or not payload:
            raise StudyError("supported kind and nonempty object payload are required")
        _json_value(payload)
        text_fields = {
            "proposal": ("purpose",), "experiment": ("question", "decision_rule"),
            "assessment": ("interpretation", "next_action"),
        }.get(kind, ())
        for field in text_fields:
            _text(payload.get(field), f"{kind}.{field}")
        if kind == "proposal" and not isinstance(payload.get("assumptions"), list):
            raise StudyError("proposal.assumptions must be a list; retain missing assumptions explicitly")
        if kind == "experiment" and (not isinstance(payload.get("observations"), list) or not payload["observations"]):
            raise StudyError("experiment.observations must be a nonempty list")
        if kind == "experiment" and "budget" in payload:
            budget = payload["budget"]
            if not isinstance(budget, dict):
                raise StudyError("experiment.budget must be an object")
            limits = budget.get("mcp_call_limits")
            if limits is not None:
                if not isinstance(limits, dict) or any(
                    not isinstance(tool, str) or not tool.strip() or
                    type(limit) is not int or limit < 0
                    for tool, limit in limits.items()
                ):
                    raise StudyError("experiment.budget.mcp_call_limits must map tool names to nonnegative integers")
        if kind == "realization":
            _text(payload.get("proposal_ref"), "realization.proposal_ref")
            if "observation" not in payload or payload["observation"] is None or not isinstance(payload.get("differences"), list):
                raise StudyError("realization requires observation and a differences list")
        if kind == "evidence":
            if not isinstance(payload.get("source"), (str, dict)) or not payload["source"]:
                raise StudyError("evidence.source must locate the observation or source material")
            if isinstance(payload["source"], str):
                _text(payload["source"], "evidence.source")
            if "observation" not in payload or payload["observation"] is None:
                raise StudyError("evidence.observation is required")
        if kind == "assessment" and (not isinstance(payload.get("evidence_refs"), list) or not payload["evidence_refs"]):
            raise StudyError("assessment.evidence_refs must contain supporting evidence")
        for key in ENTITY_RELATIONS:
            if key not in payload:
                continue
            values = payload[key] if key.endswith("_refs") or key == "refs" else [payload[key]]
            if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
                raise StudyError(f"{key} must contain entity references")
        if "run_id" in payload:
            _text(payload["run_id"], "run_id")
        if "run_ids" in payload and (not isinstance(payload["run_ids"], list) or any(not isinstance(value, str) or not value for value in payload["run_ids"])):
            raise StudyError("run_ids must be a list of run identifiers")

    @classmethod
    def _freeze_payload(cls, state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        frozen = copy.deepcopy(payload)
        for key, expected_kind in ENTITY_RELATIONS.items():
            if key not in frozen:
                continue
            if key.endswith("_refs") or key == "refs":
                frozen[key] = [cls._resolve(state, ref, expected_kind)["ref"] for ref in frozen[key]]
            else:
                frozen[key] = cls._resolve(state, frozen[key], expected_kind)["ref"]
        return frozen

    @staticmethod
    def _validate_metrics(metrics: Any) -> None:
        if not isinstance(metrics, dict) or set(metrics) != METRIC_FIELDS:
            raise StudyError("metrics must contain elapsed_seconds, human_inputs and model_cost")
        elapsed = metrics["elapsed_seconds"]
        if elapsed is not None and (type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0):
            raise StudyError("elapsed_seconds must be nonnegative or null")
        count = metrics["human_inputs"]
        if count is not None and (type(count) is not int or count < 0):
            raise StudyError("human_inputs must be a nonnegative integer or null")
        cost = metrics["model_cost"]
        if cost is not None and (not isinstance(cost, dict) or not cost):
            raise StudyError("model_cost must be a sourced cost object or null")
        _json_value(metrics)

    @classmethod
    def _validate_state(cls, state: Any) -> None:
        if not isinstance(state, dict) or state.get("schema") != "eds-study/v1":
            raise StudyError("invalid study schema")
        _json_value(state)
        _text(state.get("study_id"), "study_id")
        _text(state.get("goal"), "goal")
        if not isinstance(state.get("mode"), str) or state["mode"] not in MODES:
            raise StudyError("mode must be cad, cae, or coupled")
        for field in ("created_at", "updated_at"):
            _timestamp(state.get(field), field)
        for field in ("constraints", "facts", "assumptions", "gaps", "assets", "entities", "runs", "events"):
            if not isinstance(state.get(field), list):
                raise StudyError(f"{field} must be a list")
        if any(not isinstance(asset, dict) for asset in state["assets"]):
            raise StudyError("assets must contain objects with externally meaningful locations and versions")
        if not isinstance(state.get("context"), dict):
            raise StudyError("context must be an object")
        preferences = state.get("preferences")
        if not isinstance(preferences, dict) or not isinstance(preferences.get("extraction"), str) or preferences["extraction"] not in EXTRACTION:
            raise StudyError("invalid extraction preference")
        cls._validate_metrics(state.get("metrics"))

        entities: dict[str, dict[str, Any]] = {}
        logical: dict[str, tuple[int, str]] = {}
        entity_ids: set[str] = set()
        for entity in state["entities"]:
            if not isinstance(entity, dict):
                raise StudyError("entity must be an object")
            identity = _text(entity.get("id"), "entity.id")
            ref = _text(entity.get("ref"), "entity.ref")
            name, version = cls._split_ref(ref)
            if version is None or ref != f"{name}@{version}" or entity.get("logical_ref") != name or type(entity.get("version")) is not int or entity["version"] != version:
                raise StudyError(f"invalid pinned entity identity: {ref}")
            if ref in entities or identity in entity_ids:
                raise StudyError(f"duplicate entity identity: {ref}")
            kind = entity.get("kind")
            cls._validate_payload(kind, entity.get("payload"))
            previous_version, previous_kind = logical.get(name, (0, kind))
            if version != previous_version + 1 or kind != previous_kind:
                raise StudyError(f"noncontiguous revision or changed kind: {ref}")
            _timestamp(entity.get("created_at"), "entity.created_at")
            logical[name] = (version, kind)
            entities[ref] = entity
            entity_ids.add(identity)

        runs: dict[str, dict[str, Any]] = {}
        request_keys: set[str] = set()
        task_keys: set[tuple[str, str]] = set()
        for run in state["runs"]:
            if not isinstance(run, dict):
                raise StudyError("run must be an object")
            for field in ("run_id", "backend", "capability", "idempotency_key"):
                _text(run.get(field), f"run.{field}")
            if run["run_id"] in runs or run["idempotency_key"] in request_keys:
                raise StudyError("duplicate run or idempotency key")
            for field in ("task_id", "initial_task_id"):
                if field not in run:
                    raise StudyError(f"run.{field} is required, possibly null")
                if run[field] is not None:
                    _text(run[field], f"run.{field}")
            if run["initial_task_id"] is not None and run["initial_task_id"] != run["task_id"]:
                raise StudyError("initial task identity changed")
            if run["task_id"] is not None:
                task_key = (run["backend"], run["task_id"])
                if task_key in task_keys:
                    raise StudyError("one backend task cannot belong to multiple runs")
                task_keys.add(task_key)
            experiment_ref = run.get("experiment_ref")
            if not isinstance(experiment_ref, str) or experiment_ref not in entities or entities[experiment_ref]["kind"] != "experiment":
                raise StudyError("run experiment must reference a pinned experiment")
            if not isinstance(run.get("input_refs"), list) or any(not isinstance(ref, str) or ref not in entities for ref in run["input_refs"]):
                raise StudyError("run input_refs must reference pinned entities")
            if not isinstance(run.get("input_snapshot"), dict):
                raise StudyError("run input_snapshot must be an object")
            _validate_run_preset(run["input_snapshot"], state["mode"])
            for field in ("created_at", "updated_at"):
                _timestamp(run.get(field), f"run.{field}")
            cls._validate_history(run)
            runs[run["run_id"]] = run
            request_keys.add(run["idempotency_key"])

        for entity in entities.values():
            payload = entity["payload"]
            for key, expected_kind in ENTITY_RELATIONS.items():
                if key not in payload:
                    continue
                values = payload[key] if key.endswith("_refs") or key == "refs" else [payload[key]]
                for ref in values:
                    if ref not in entities or (expected_kind is not None and entities[ref]["kind"] != expected_kind):
                        raise StudyError(f"invalid pinned {key}: {ref}")
            linked_runs = payload.get("run_ids", []) + ([payload["run_id"]] if "run_id" in payload else [])
            if any(run_id not in runs for run_id in linked_runs):
                raise StudyError("entity references a nonexistent run")

        event_ids: set[str] = set()
        extraction_keys: set[str] = set()
        for event in state["events"]:
            if not isinstance(event, dict):
                raise StudyError("event must be an object")
            identity = _text(event.get("event_id"), "event.event_id")
            _text(event.get("type"), "event.type")
            _timestamp(event.get("at"), "event.at")
            if identity in event_ids:
                raise StudyError("duplicate event identity")
            event_ids.add(identity)
            if event["type"] == "extraction":
                key = _text(event.get("event_key"), "extraction.event_key")
                if key in extraction_keys:
                    raise StudyError("duplicate extraction event key")
                cls._unit_refs(event.get("unit_refs"))
                extraction_keys.add(key)

    @staticmethod
    def _validate_history(run: dict[str, Any]) -> None:
        history = run.get("history")
        if not isinstance(history, list) or not history:
            raise StudyError("run requires an observation history")
        previous = None
        assigned = run["initial_task_id"]
        latest_output = None
        for observation in history:
            if not isinstance(observation, dict) or not isinstance(observation.get("status"), str) or observation["status"] not in STATUSES:
                raise StudyError("invalid run observation")
            status = observation["status"]
            if previous is None:
                initial_status = "unknown" if run["initial_task_id"] is not None else "planned"
                if status != initial_status:
                    raise StudyError("run history must start at unknown for an existing task, otherwise planned")
                if observation.get("task_id") != run["initial_task_id"]:
                    raise StudyError("initial task identity disagrees with first observation")
            elif not _allowed_transition(previous, status):
                raise StudyError("invalid transition in stored run history")
            _timestamp(observation.get("at"), "run observation timestamp")
            if "task_id" not in observation or "output" not in observation:
                raise StudyError("each observation must preserve task_id and raw output")
            task_id = observation["task_id"]
            if task_id is not None:
                _text(task_id, "observed task_id")
                if assigned is not None and assigned != task_id:
                    raise StudyError("task identity changed in history")
                assigned = task_id
            elif assigned is not None:
                raise StudyError("known task identity disappeared from history")
            if status == "completed" and observation["output"] is None:
                raise StudyError("completed run requires actual output")
            if observation["output"] is not None:
                latest_output = observation["output"]
            previous = status
        if previous != run.get("status") or assigned != run["task_id"]:
            raise StudyError("run summary disagrees with observation history")
        if run["created_at"] != history[0]["at"] or run["updated_at"] != history[-1]["at"]:
            raise StudyError("run timestamps disagree with observation history")
        if _canonical(latest_output) != _canonical(run.get("output")):
            raise StudyError("run output disagrees with observation history")

    def read(self) -> dict[str, Any]:
        return copy.deepcopy(self._read())

    def get(self, kind: str | None = None, ref: str | None = None) -> Any:
        entities = self._read()["entities"]
        if kind is not None:
            if not isinstance(kind, str) or kind not in KINDS:
                raise StudyError("unsupported entity kind")
            entities = [item for item in entities if item["kind"] == kind]
        if ref is not None:
            logical, version = self._split_ref(ref)
            matches = [item for item in entities if item["logical_ref"] == logical and (version is None or item["version"] == version)]
            return copy.deepcopy(matches[-1] if matches else None)
        return copy.deepcopy(entities)

    def add(self, kind: str, payload: dict[str, Any], *, ref: str | None = None) -> dict[str, Any]:
        self._validate_payload(kind, payload)
        with self._lock():
            state = self._read()
            logical, expected_version = self._split_ref(ref or payload.get("ref") or _uid(kind))
            prior = [item for item in state["entities"] if item["logical_ref"] == logical]
            if prior and prior[-1]["kind"] != kind:
                raise StudyError("a logical reference cannot change entity kind")
            version = prior[-1]["version"] if prior else 0
            if expected_version is not None and expected_version != version:
                raise StudyError("revision conflict: requested base is not the current revision")
            entity = {"id": _uid(kind), "ref": f"{logical}@{version + 1}", "logical_ref": logical,
                      "version": version + 1, "kind": kind, "created_at": _now(),
                      "payload": self._freeze_payload(state, payload)}
            state["entities"].append(entity)
            self._write(state)
            return copy.deepcopy(entity)

    def add_run(self, *, experiment_ref: str, input_refs: list[str], backend: str,
                capability: str, input_snapshot: dict[str, Any], idempotency_key: str,
                task_id: str | None = None,
                execution_preset: dict[str, Any] | None = None) -> dict[str, Any]:
        for field, value in (("backend", backend), ("capability", capability), ("idempotency_key", idempotency_key)):
            _text(value, field)
        if task_id is not None:
            _text(task_id, "task_id")
        if not isinstance(input_refs, list) or not isinstance(input_snapshot, dict):
            raise StudyError("input_refs must be a list and input_snapshot an object")
        input_snapshot = copy.deepcopy(input_snapshot)
        if execution_preset is not None:
            if "execution_preset" in input_snapshot:
                raise StudyError("execution preset supplied twice")
            input_snapshot["execution_preset"] = copy.deepcopy(execution_preset)
        _json_value(input_snapshot)
        with self._lock():
            state = self._read()
            _validate_run_preset(input_snapshot, state["mode"])
            request = {"experiment_ref": self._resolve(state, experiment_ref, "experiment")["ref"],
                       "input_refs": [self._resolve(state, item)["ref"] for item in input_refs],
                       "backend": backend, "capability": capability, "input_snapshot": copy.deepcopy(input_snapshot),
                       "initial_task_id": task_id}
            old = next((run for run in state["runs"] if run["idempotency_key"] == idempotency_key), None)
            if old is not None:
                if _canonical({key: old[key] for key in request}) != _canonical(request):
                    raise StudyError("idempotency key reused with a different request")
                return copy.deepcopy(old)
            experiment = self._resolve(state, experiment_ref, "experiment")
            snapshot_tool = input_snapshot.get("tool")
            budget = experiment.get("payload", {}).get("budget", {})
            limits = budget.get("mcp_call_limits") if isinstance(budget, dict) else None
            if limits is not None and snapshot_tool in limits:
                used = sum(
                    1 for prior in state["runs"]
                    if prior.get("experiment_ref") == experiment["ref"]
                    and prior.get("input_snapshot", {}).get("tool") == snapshot_tool
                    and not (
                        prior.get("status") == "cancelled"
                        and prior.get("initial_task_id") is None
                        and not any(item.get("status") == "submitting" for item in prior.get("history", []))
                    )
                    and not (
                        prior.get("status") == "failed"
                        and isinstance(prior.get("output"), dict)
                        and prior["output"].get("preflight_rejected") is True
                        and prior["output"].get("tool_sent") is False
                    )
                )
                if used >= limits[snapshot_tool]:
                    raise StudyError(f"MCP attempt limit exhausted for tool {snapshot_tool}")

            # A changed decision/method reference is not a new physical action.
            # A repeated terminal action must cite a previously unused fixed
            # evidence/realization reference to make the state change explicit.
            current_server = input_snapshot.get("expected_server") or input_snapshot.get("server_url")
            read_only = input_snapshot.get("read_only") is True
            current_action_refs = set(request["input_refs"])
            current_observation_refs = {
                ref for ref in current_action_refs
                if self._resolve(state, ref)["kind"] in {"evidence", "realization"}
            }
            prior_observation_refs_all = set()
            matching_terminal = False
            for prior in state["runs"] if isinstance(snapshot_tool, str) and "arguments" in input_snapshot else ():
                prior_snapshot = prior.get("input_snapshot", {})
                prior_server = prior_snapshot.get("expected_server") or prior_snapshot.get("server_url")
                if (prior.get("experiment_ref") != experiment["ref"] or
                        prior_snapshot.get("tool") != snapshot_tool or
                        prior_server != current_server or
                        prior_snapshot.get("arguments") != input_snapshot.get("arguments") or
                        prior.get("idempotency_key") == idempotency_key or
                        prior.get("status") == "cancelled" and
                        not any(item.get("status") == "submitting" for item in prior.get("history", []))):
                    continue
                if prior.get("status") in {"submitting", "submitted", "running", "unknown"}:
                    raise StudyError("matching MCP action is pending or uncertain; query the existing run before retrying")
                if (prior.get("status") == "failed" and isinstance(prior.get("output"), dict)
                        and prior["output"].get("preflight_rejected") is True
                        and prior["output"].get("tool_sent") is False):
                    continue
                prior_refs = set(prior.get("input_refs", []))
                prior_observation_refs = {
                    ref for ref in prior_refs
                    if self._resolve(state, ref)["kind"] in {"evidence", "realization"}
                }
                matching_terminal = True
                prior_observation_refs_all.update(prior_observation_refs)
            if matching_terminal and not read_only and not current_observation_refs - prior_observation_refs_all:
                raise StudyError("repeated MCP action requires a new fixed evidence or realization reference")
            now = _now()
            initial_status = "unknown" if task_id is not None else "planned"
            run = {**request, "run_id": _uid("run"), "idempotency_key": idempotency_key, "task_id": task_id,
                   "status": initial_status, "output": None, "created_at": now, "updated_at": now,
                   "history": [{"status": initial_status, "at": now, "task_id": task_id, "output": None}]}
            state["runs"].append(run)
            self._write(state)
            return copy.deepcopy(run)

    def transition_run(self, run_id: str, status: str, *, output: Any = None,
                       task_id: str | None = None, observed_at: str | None = None) -> dict[str, Any]:
        if not isinstance(status, str) or status not in STATUSES:
            raise StudyError("unknown run status")
        _json_value(output)
        if task_id is not None:
            _text(task_id, "task_id")
        at = _timestamp(observed_at, "observed_at") if observed_at is not None else _now()
        with self._lock():
            state = self._read()
            run = next((item for item in state["runs"] if item["run_id"] == run_id), None)
            if run is None or not _allowed_transition(run["status"], status):
                raise StudyError("invalid run transition")
            if task_id is not None and run["task_id"] not in (None, task_id):
                raise StudyError("task_id cannot change")
            if status == "completed" and output is None:
                raise StudyError("completed run requires actual output")
            if task_id is not None:
                run["task_id"] = task_id
            run["history"].append({"status": status, "at": at, "task_id": run["task_id"], "output": copy.deepcopy(output)})
            run["status"] = status
            run["updated_at"] = at
            if output is not None:
                run["output"] = copy.deepcopy(output)
            self._write(state)
            return copy.deepcopy(run)

    @staticmethod
    def _event(state: dict[str, Any], kind: str, **values: Any) -> dict[str, Any]:
        event = {"event_id": _uid("event"), "type": kind, "at": _now(), **copy.deepcopy(values)}
        state["events"].append(event)
        return event

    def set_preferences(self, extraction: str) -> dict[str, Any]:
        if not isinstance(extraction, str) or extraction not in EXTRACTION:
            raise StudyError("extraction must be once, auto, later, or skip")
        with self._lock():
            state = self._read()
            previous = copy.deepcopy(state["preferences"])
            state["preferences"]["extraction"] = extraction
            self._event(state, "preferences", previous=previous, current=state["preferences"])
            self._write(state)
            return copy.deepcopy(state["preferences"])

    @staticmethod
    def _unit_refs(unit_refs: Any) -> list[str]:
        if not isinstance(unit_refs, list) or not unit_refs:
            raise StudyError("unit_refs must be a nonempty list of versioned knowledge identities")
        for ref in unit_refs:
            _text(ref, "knowledge reference")
            if "@" not in ref or not all(ref.rsplit("@", 1)):
                raise StudyError("knowledge references must include an explicit @version")
        return sorted(set(unit_refs))

    def record_extraction(self, unit_refs: list[str], *, event_key: str | None = None,
                          explicit: bool = False) -> dict[str, Any]:
        refs = self._unit_refs(unit_refs)
        if type(explicit) is not bool:
            raise StudyError("explicit must be boolean")
        key = event_key or hashlib.sha256(_canonical(refs).encode("utf-8")).hexdigest()
        _text(key, "event_key")
        with self._lock():
            state = self._read()
            old = next((event for event in state["events"] if event["type"] == "extraction" and event["event_key"] == key), None)
            if old is not None:
                if old["unit_refs"] != refs:
                    raise StudyError("extraction key reused for different unit versions")
                return copy.deepcopy(old)
            preference = state["preferences"]["extraction"]
            if preference in {"later", "skip"} and not explicit:
                raise StudyError("extraction is deferred or skipped; explicit=True records requested backfill")
            event = self._event(state, "extraction", event_key=key, unit_refs=refs,
                                explicit=explicit, preference=preference)
            if preference == "once":
                state["preferences"]["extraction"] = "later"
            self._write(state)
            return copy.deepcopy(event)

    def set_summary(self, **values: Any) -> dict[str, Any]:
        _json_value(values)
        with self._lock():
            state = self._read()
            previous = {key: copy.deepcopy(state["context"].get(key)) for key in values}
            state["context"].update(copy.deepcopy(values))
            self._event(state, "summary", previous=previous, changes=values)
            self._write(state)
            return copy.deepcopy(state["context"])

    def update_context(self, **values: Any) -> dict[str, Any]:
        _json_value(values)
        with self._lock():
            state = self._read()
            previous = {}
            for key, value in values.items():
                destination = state if key in CONTEXT_FIELDS else state["context"]
                previous[key] = copy.deepcopy(destination.get(key))
                destination[key] = copy.deepcopy(value)
            self._event(state, "context", previous=previous, changes=values)
            self._write(state)
            return {key: copy.deepcopy(state[key] if key in CONTEXT_FIELDS else state["context"][key]) for key in values}

    def set_metrics(self, **values: Any) -> dict[str, Any]:
        if set(values) - METRIC_FIELDS:
            raise StudyError("metrics accept only elapsed_seconds, human_inputs and model_cost")
        with self._lock():
            state = self._read()
            previous = copy.deepcopy(state["metrics"])
            state["metrics"].update(copy.deepcopy(values))
            self._validate_metrics(state["metrics"])
            self._event(state, "metrics", previous=previous, changes=values)
            self._write(state)
            return self._metrics(state)

    @staticmethod
    def _metrics(state: dict[str, Any]) -> dict[str, Any]:
        experiments = [entity for entity in state["entities"] if entity["kind"] == "experiment"]
        return {**copy.deepcopy(state["metrics"]), "experiment_count": len({entity["logical_ref"] for entity in experiments}),
                "experiment_revision_count": len(experiments), "run_count": len(state["runs"]),
                "completed_runs": sum(run["status"] == "completed" for run in state["runs"]),
                "failed_runs": sum(run["status"] == "failed" for run in state["runs"]),
                "unknown_runs": sum(run["status"] == "unknown" for run in state["runs"])}

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Return one complete persisted run, or None when it is unknown."""
        _text(run_id, "run_id")
        return copy.deepcopy(next((run for run in self._read()["runs"] if run["run_id"] == run_id), None))

    @staticmethod
    def _entity_descriptor(entity: dict[str, Any]) -> dict[str, Any]:
        # Keep the resume index deliberately payload-free. Callers can fetch the
        # authored entity through get/show when its details are needed.
        return {key: copy.deepcopy(entity[key]) for key in
                ("ref", "logical_ref", "version", "kind", "created_at")}

    @staticmethod
    def _run_summary(run: dict[str, Any]) -> dict[str, Any]:
        return {key: copy.deepcopy(run[key]) for key in
                ("run_id", "backend", "capability", "status", "task_id", "idempotency_key",
                 "experiment_ref", "input_refs", "created_at", "updated_at")} | {
                     "output_available": run.get("output") is not None}

    def resume(self, *, full: bool = False) -> dict[str, Any]:
        state = self._read()
        if full:
            current = {entity["logical_ref"]: copy.deepcopy(entity) for entity in state["entities"]}
            pending = [copy.deepcopy(run) for run in state["runs"] if run["status"] not in TERMINAL]
            query = [run["run_id"] for run in pending if run["status"] != "planned"]
            return {**{key: copy.deepcopy(state[key]) for key in ("study_id", "goal", "mode", "constraints", "facts", "assumptions", "assets", "gaps", "preferences")},
                    "current": current, "context": copy.deepcopy(state["context"]),
                    "latest_assessment": next((copy.deepcopy(entity) for entity in reversed(state["entities"]) if entity["kind"] == "assessment"), None),
                    "latest_decision": next((copy.deepcopy(entity) for entity in reversed(state["entities"]) if entity["kind"] == "decision"), None),
                    "pending_runs": pending, "query_before_submit": query, "query_before_resubmit": query,
                    "ready_to_submit": [run["run_id"] for run in pending if run["status"] == "planned"],
                    "next_step": state["context"].get("next_step"), "metrics": self._metrics(state)}

        current = {entity["logical_ref"]: self._entity_descriptor(entity) for entity in state["entities"]}
        pending = [self._run_summary(run) for run in state["runs"] if run["status"] not in TERMINAL]
        failed = [self._run_summary(run) for run in state["runs"] if run["status"] == "failed"]
        query = [run["run_id"] for run in pending if run["status"] != "planned"]
        summary_keys = ("current_question", "conclusion", "conditions", "next_step", "stop_reason", "budget")
        context = {key: copy.deepcopy(state["context"][key]) for key in summary_keys if key in state["context"]}
        omitted = sorted(set(state["context"]) - set(summary_keys))
        latest_assessment = next((self._entity_descriptor(entity) for entity in reversed(state["entities"]) if entity["kind"] == "assessment"), None)
        latest_decision = next((self._entity_descriptor(entity) for entity in reversed(state["entities"]) if entity["kind"] == "decision"), None)
        return {**{key: copy.deepcopy(state[key]) for key in ("study_id", "goal", "mode", "constraints", "facts", "assumptions", "assets", "gaps", "preferences")},
                "detail": "summary", "full_details_available": True, "current": current, "context": context,
                "omitted_context_keys": omitted, "latest_assessment": latest_assessment, "latest_decision": latest_decision,
                "pending_runs": pending, "query_before_submit": query, "query_before_resubmit": query,
                "ready_to_submit": [run["run_id"] for run in pending if run["status"] == "planned"],
                "failed_runs": failed, "next_step": state["context"].get("next_step"), "metrics": self._metrics(state)}

    @staticmethod
    def _dependencies(payload: dict[str, Any]) -> set[str]:
        dependencies = set(payload.get("run_ids", []))
        if "run_id" in payload:
            dependencies.add(payload["run_id"])
        for key in ENTITY_RELATIONS:
            if key in payload:
                dependencies.update(payload[key] if key.endswith("_refs") or key == "refs" else [payload[key]])
        return dependencies

    def impact(self, ref: str) -> dict[str, Any]:
        state = self._read()
        run_ids = {run["run_id"] for run in state["runs"]}
        root = ref if ref in run_ids else self._resolve(state, ref)["ref"]
        graph = {entity["ref"]: self._dependencies(entity["payload"]) for entity in state["entities"]}
        graph.update({run["run_id"]: {run["experiment_ref"], *run["input_refs"]} for run in state["runs"]})
        affected = {root}
        changed = True
        while changed:
            changed = False
            for identity, dependencies in graph.items():
                if identity not in affected and dependencies & affected:
                    affected.add(identity)
                    changed = True
        return {"ref": root, "found": True, "affected": sorted(affected - {root} - run_ids),
                "affected_runs": sorted(affected & run_ids), "missing": [],
                "old_results_require_review": sorted(affected & run_ids),
                "reuse_decision": "requires_agent_assessment_of_actual_change"}

    def render_report(self) -> dict[str, Any]:
        state = self._read()
        latest = {entity["logical_ref"]: entity for entity in state["entities"]}
        evidence = [entity for entity in state["entities"] if entity["kind"] == "evidence"]
        return {"study_id": state["study_id"], "goal": state["goal"], "mode": state["mode"],
                "context": copy.deepcopy(state["context"]), "metrics": self._metrics(state),
                "cost": copy.deepcopy(state["metrics"]["model_cost"]),
                "current_objects": [copy.deepcopy(entity) for entity in latest.values() if entity["kind"] in {"design", "proposal", "realization", "mapping"}],
                "artifacts": copy.deepcopy(state["context"].get("artifacts", [])),
                "evidence_basis": [entity["ref"] for entity in evidence], "evidence": copy.deepcopy(evidence),
                "assessments": [copy.deepcopy(entity) for entity in latest.values() if entity["kind"] == "assessment"],
                "conditions": copy.deepcopy(state["context"].get("conditions", [])),
                "open_questions": copy.deepcopy(state["gaps"]),
                "pending_runs": [run["run_id"] for run in state["runs"] if run["status"] not in TERMINAL],
                "next_step": state["context"].get("next_step"), "stop_reason": state["context"].get("stop_reason")}
