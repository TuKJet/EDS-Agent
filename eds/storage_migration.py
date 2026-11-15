"""Explicit representation migration from historical snapshots to a small ledger.

This is an offline maintenance operation. It changes storage, not experiment
versions or conclusions. One verified compressed archive enables exact rollback;
normal publication never invokes it or silently rewrites an existing version.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .knowledge import KnowledgeBase
from .study import StudyStore, ARTIFACT_SCHEMA, INLINE_LIMIT


class StorageMigrationError(ValueError):
    """A migration cannot safely preserve or restore the recorded evidence."""


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _hash_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _hash_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="migration.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _science(record):
    """Fields whose meaning must survive a representation-only conversion."""
    science = {key: record.get(key) for key in (
        "id", "version", "study_id", "assessment_ref", "title", "context",
        "observations", "analysis", "guidance", "method_evaluations", "relations", "reuse")}
    science["analysis"] = {key: value for key, value in record.get("analysis", {}).items() if key != "assessment"}
    return science


def _run_science(record):
    actions = record.get("actions", {})
    return {"entity_refs": actions.get("entity_refs", []),
            "run_ids": actions.get("run_ids", []), "run_statuses": actions.get("run_statuses", []),
            "runs": [{key: run.get(key) for key in (
                "run_id", "status", "experiment_ref", "input_refs", "backend", "capability", "task_id",
                "created_at", "updated_at", "temporal_status")}
                for run in actions.get("runs", [])]}


def _assert_science(old, new):
    if _science(old) != _science(new) or _run_science(old) != _run_science(new):
        raise StorageMigrationError("experience conversion changed scientific facts, temporal status or references")
    assessment = old.get("analysis", {}).get("assessment")
    retained = next((item for item in new.get("observations", {}).get("entities", [])
                     if item.get("ref") == old.get("assessment_ref") and item.get("kind") == "assessment"), None)
    if assessment is not None and (retained is None or retained.get("payload") != assessment):
        raise StorageMigrationError("experience conversion lost the original Assessment entity")


def _payload_digest(value):
    if isinstance(value, dict) and value.get("schema") == ARTIFACT_SCHEMA:
        return value["sha256"]
    return _hash_bytes(_bytes(value)[:-1])


def _assert_runs_retained(record, retained_runs, store, checked_artifacts):
    """Only discard Run payload copies that remain reachable in the Study.

    Historical publications may have an earlier status and an ordered subset of
    observations. Derived ledger dates/statuses need not match the latest Run.
    """
    def digest(value):
        if isinstance(value, dict) and value.get("schema") == ARTIFACT_SCHEMA:
            artifact = _destination(store.root, value["uri"])
            key = (str(artifact), value["sha256"], value["bytes"])
            if key not in checked_artifacts:
                if not artifact.is_file() or artifact.stat().st_size != value["bytes"] or _hash_file(artifact) != value["sha256"]:
                    raise StorageMigrationError("retained Study artifact is missing or corrupt")
                checked_artifacts.add(key)
        return _payload_digest(value)

    observation_indices = {}
    for old in record.get("actions", {}).get("runs", []):
        if not any(key in old for key in ("input_snapshot", "history", "output")):
            continue
        run_id = old.get("run_id")
        current = retained_runs.get(run_id)
        if current is None:
            raise StorageMigrationError(f"Run {run_id} is not retained in the Study")
        for key, value in old.get("input_snapshot", {}).items():
            if key == "arguments_sha256":
                continue
            snapshot = current.get("input_snapshot", {})
            if key not in snapshot or _payload_digest(value) != digest(snapshot[key]):
                raise StorageMigrationError(f"Run {run_id} input_snapshot.{key} is not retained in the Study")
        history = current.get("history", [])
        cursor = 0
        for observation in old.get("history", []):
            for index in range(cursor, len(history)):
                candidate = history[index]
                if all(key in candidate and _payload_digest(value) == digest(candidate[key])
                       for key, value in observation.items() if key not in {"temporal_status", "source"}):
                    cursor = index + 1
                    break
            else:
                raise StorageMigrationError(f"Run {run_id} history observation is not retained in the Study")
        if "history" in old:
            observation_indices[run_id] = cursor - 1 if cursor else None
        if old.get("output") is not None:
            expected = _payload_digest(old["output"])
            if not any(expected == digest(item.get("output")) for item in history):
                raise StorageMigrationError(f"Run {run_id} output is not retained in the Study history")
    return observation_indices


def _map_observation_sources(record, observation_indices):
    for run in record.get("actions", {}).get("runs", []):
        if run["run_id"] in observation_indices:
            run["source"]["observation_index"] = observation_indices[run["run_id"]]


def _run_digests(state):
    """Compare logical inputs and every status observation without duplicating payloads."""
    result = {}
    for run in state["runs"]:
        snapshot = dict(run["input_snapshot"])
        snapshot.pop("arguments_sha256", None)  # Derived representation metadata.
        if "arguments" in snapshot:
            snapshot["arguments"] = {"payload_sha256": _payload_digest(snapshot["arguments"])}
        logical = {**run, "input_snapshot": snapshot,
                   "output": {"payload_sha256": _payload_digest(run.get("output"))},
                   "history": [{**item, "output": {"payload_sha256": _payload_digest(item.get("output"))}}
                               for item in run["history"]]}
        result[run["run_id"]] = _hash_bytes(_bytes(logical))
    return result


def _needs_run_compaction(state):
    for run in state["runs"]:
        snapshot = run["input_snapshot"]
        if "arguments" in snapshot and "arguments_sha256" not in snapshot:
            return True
        values = [snapshot["arguments"]] if "arguments" in snapshot else []
        values.extend(item.get("output") for item in run["history"])
        for value in values:
            if not (isinstance(value, dict) and value.get("schema") == ARTIFACT_SCHEMA):
                if len(_bytes(value)) - 1 > INLINE_LIMIT:
                    return True
    return False


def _destination(root, relative):
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise StorageMigrationError(f"migration path escapes its root: {relative}")
    return path


def _prepare(store, kb):
    from .experience import compact_iteration, validate_iteration, _markdown

    state = store._read()
    retained_runs = {run["run_id"]: run for run in state["runs"]}
    checked_artifacts = set()
    entities_digest = _hash_bytes(_bytes(state["entities"]))
    run_ids = [run["run_id"] for run in state["runs"]]
    updates = {}
    records = {}
    conversions = []
    for path in sorted((kb.root / "iterations").glob("*/v*.json")):
        path = _destination(kb.root, path.relative_to(kb.root))
        original_bytes = path.read_bytes()
        old = json.loads(original_bytes)
        if old.get("study_id") != state["study_id"]:
            continue
        old = validate_iteration(old)
        records[(old["study_id"], old["assessment_ref"])] = old
        if old["schema"] == "eds-experience/v2":
            continue
        observation_indices = _assert_runs_retained(old, retained_runs, store, checked_artifacts)
        new = compact_iteration(old)
        _map_observation_sources(new, observation_indices)
        _assert_science(old, new)
        relative = path.relative_to(kb.root).as_posix()
        new["provenance"] = {**new["provenance"], "published_path": relative}
        new_bytes = _bytes(new)
        markdown_path = path.with_suffix(".md")
        markdown = _markdown(new, relative, _hash_bytes(new_bytes)).encode()
        updates[path] = new_bytes
        updates[markdown_path] = markdown
        conversions.append({"assessment_ref": old["assessment_ref"], "id": old["id"], "version": old["version"],
                            "path": relative, "before_sha256": _hash_bytes(original_bytes),
                            "after_sha256": _hash_bytes(new_bytes), "before_bytes": len(original_bytes),
                            "after_bytes": len(new_bytes), "scientific_fields_unchanged": True})

    removed = []
    retained_pending = []
    compacted_pending = []
    removed_assessment_snapshots = []
    publication_mappings = []
    for event in state["events"]:
        if event.get("type") != "experience_publication":
            continue
        record = event.get("record")
        if isinstance(record, dict):
            observation_indices = _assert_runs_retained(record, retained_runs, store, checked_artifacts)
            _assert_science(record, record)
            identity = (state["study_id"], event["assessment_ref"])
            central = records.get(identity)
            exact_science = central is not None and _science(record) == _science(central) and _run_science(record) == _run_science(central)
            publication_mappings.append({"event_id": event["event_id"], "publication_id": event["publication_id"],
                                         "assessment_ref": event["assessment_ref"],
                                         "legacy_record_sha256": _hash_bytes(_bytes(record)),
                                         "central_id": central.get("id") if central else None,
                                         "central_version": central.get("version") if central else None,
                                         "scientific_fields_match": exact_science})
            if exact_science:
                del event["record"]
                removed.append(event["event_id"])
            else:
                compact = compact_iteration(record)
                _map_observation_sources(compact, observation_indices)
                _assert_science(record, compact)
                if compact != record:
                    compacted_pending.append(event["event_id"])
                event["record"] = compact
                retained_pending.append(event["event_id"])
        # The entity remains immutable in state.entities; no second copy needed.
        if "assessment_snapshot" in event:
            event.pop("assessment_snapshot")
            removed_assessment_snapshots.append(event["event_id"])

    # Reconciliation is a source-preserving interpretation, not a rewritten
    # success event. In particular, rejected alias publications remain failed.
    aliases = {}
    for event in state["events"]:
        if event.get("type") == "experience_publication":
            key = event["assessment_ref"]
            aliases.setdefault(key, set()).add(event["publication_id"])
    aliases = {key: sorted(ids) for key, ids in aliases.items() if len(ids) > 1}
    report = {"schema": "eds-storage-migration/v1", "study_id": state["study_id"],
              "study_root": str(store.root), "knowledge_root": str(kb.root),
              "knowledge_records_to_migrate": len(conversions), "knowledge_conversions": conversions,
              "publication_record_copies_removed": len(removed), "removed_snapshot_event_ids": removed,
              "compact_unpublished_legacy_records_retained": retained_pending,
              "legacy_records_compacted": compacted_pending,
              "assessment_snapshot_copies_removed": removed_assessment_snapshots,
              "publication_identity_audit": publication_mappings,
              "publication_alias_groups_preserved": aliases,
              "study_bytes_before": store.path.stat().st_size,
              "entities_sha256": entities_digest, "run_ids": run_ids, "run_semantic_sha256": _run_digests(state),
              "semantics": "Representation only; scientific versions, evidence, Run states and rejected publication history are preserved."}
    return state, updates, report


def _disk_bytes(state):
    disk = {**state, "run_output_storage": "history",
            "runs": [{key: value for key, value in run.items() if key != "output"} for run in state["runs"]]}
    return (json.dumps(disk, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _backup(path, roots, files):
    if path.exists():
        raise StorageMigrationError("backup already exists; inspect its migration report or roll it back before retrying")
    path.parent.mkdir(parents=True, exist_ok=True)
    members = []
    for file in files:
        group = "study" if file.is_relative_to(roots["study"]) else "knowledge"
        relative = file.relative_to(roots[group]).as_posix()
        members.append({"member": group + "/" + relative, "group": group, "relative": relative,
                        "bytes": file.stat().st_size, "sha256": _hash_file(file)})
    manifest = {"schema": "eds-storage-backup/v1", "roots": {k: str(v) for k, v in roots.items()}, "files": members}
    fd, temporary_name = tempfile.mkstemp(prefix="backup.", suffix=".tar.gz", dir=path.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with tarfile.open(temporary, "w:gz", compresslevel=6) as archive:
            for item in members:
                file = roots[item["group"]] / item["relative"]
                archive.add(file, arcname=item["member"], recursive=False)
            encoded = _bytes(manifest)
            info = tarfile.TarInfo("manifest.json")
            info.size = len(encoded)
            archive.addfile(info, io.BytesIO(encoded))
        _verify_backup(temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


def _verify_backup(path):
    with tarfile.open(path, "r:gz") as archive:
        manifest_file = archive.extractfile("manifest.json")
        if manifest_file is None:
            raise StorageMigrationError("backup manifest is missing")
        manifest = json.load(manifest_file)
        if manifest.get("schema") != "eds-storage-backup/v1":
            raise StorageMigrationError("unsupported backup schema")
        expected = {item["member"] for item in manifest["files"]} | {"manifest.json"}
        if set(archive.getnames()) != expected or len(archive.getnames()) != len(expected):
            raise StorageMigrationError("backup has unexpected or duplicate members")
        for item in manifest["files"]:
            member = archive.getmember(item["member"])
            if not member.isfile() or member.size != item["bytes"]:
                raise StorageMigrationError("backup member is not the expected regular file")
            stream = archive.extractfile(member)
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
            if digest.hexdigest() != item["sha256"]:
                raise StorageMigrationError("backup member checksum mismatch")
    return manifest


def _rebuild_index(knowledge_root):
    return KnowledgeBase(knowledge_root).rebuild()


def _restore(path, manifest):
    with tarfile.open(path, "r:gz") as archive:
        for item in manifest["files"]:
            root = Path(manifest["roots"][item["group"]]).resolve()
            destination = _destination(root, item["relative"])
            with archive.extractfile(item["member"]) as source:
                fd, temporary_name = tempfile.mkstemp(prefix="restore.", suffix=".tmp", dir=destination.parent)
                try:
                    with os.fdopen(fd, "wb") as target:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            target.write(chunk)
                        target.flush()
                        os.fsync(target.fileno())
                    os.replace(temporary_name, destination)
                finally:
                    Path(temporary_name).unlink(missing_ok=True)


def rollback_storage_migration(backup_path):
    """Restore exact pre-migration sources; refuse to overwrite later edits."""
    path = Path(backup_path).resolve()
    report_path = path.with_name(path.name + ".report.json")
    report = json.loads(report_path.read_text())
    if _hash_file(path) != report["backup_sha256"]:
        raise StorageMigrationError("backup archive checksum mismatch")
    manifest = _verify_backup(path)
    store = StudyStore(manifest["roots"]["study"])
    kb = KnowledgeBase(manifest["roots"]["knowledge"])
    with store._lock(), KnowledgeBase(kb.cache_root / ".experience-publication")._lock():
        for item in report["source_changes"]:
            current = Path(item["path"])
            if not current.exists() or _hash_file(current) not in {item["before_sha256"], item["after_sha256"]}:
                raise StorageMigrationError(f"source changed after migration; refusing rollback: {current}")
        _restore(path, manifest)
        _rebuild_index(kb.root)
        report["status"] = "rolled_back"
        _atomic(report_path, _bytes(report))
    return report


def migrate_storage(study_root, knowledge_root, *, apply=False, backup_path=None):
    """Plan or apply an explicit migration; never deletes original evidence files.

    Interrupted applications leave a report with exact old/new source checksums.
    Call rollback_storage_migration on that archive, then rerun with a new backup
    path. Repeating an already completed migration is a no-op.
    """
    store = StudyStore(study_root)
    kb = KnowledgeBase(knowledge_root)
    with store._lock(), KnowledgeBase(kb.cache_root / ".experience-publication")._lock():
        state, updates, report = _prepare(store, kb)
        report["status"] = "dry_run"
        changed = bool(updates or report["publication_record_copies_removed"] or
                       report["legacy_records_compacted"] or report["assessment_snapshot_copies_removed"] or
                       state.get("run_output_storage") != "history" or _needs_run_compaction(state))
        if not apply:
            report["run_storage"] = store.compact_storage(state, write_artifacts=False)
            report["estimated_study_bytes_after"] = len(_disk_bytes(state))
            report["estimated_knowledge_bytes_saved"] = sum(x["before_bytes"] - x["after_bytes"] for x in report["knowledge_conversions"])
            return report
        if not changed:
            return {**report, "status": "already_compact"}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = Path(backup_path).resolve() if backup_path else store.root.parent / f"storage-before-ledger-{stamp}.tar.gz"
        if backup.is_relative_to(kb.root) or backup.is_relative_to(store.root):
            raise StorageMigrationError("backup must be outside the migrated Study and knowledge roots")
        files = sorted({store.path, *updates})
        roots = {"study": store.root, "knowledge": kb.root}
        manifest = _backup(backup, roots, files)
        report.update(backup_path=str(backup), backup_sha256=_hash_file(backup), backup_bytes=backup.stat().st_size,
                      status="preparing", source_changes=[
                          {"path": str(roots[item["group"]] / item["relative"]),
                           "before_sha256": item["sha256"], "after_sha256": item["sha256"],
                           "after_bytes": item["bytes"]} for item in manifest["files"]])
        report_path = backup.with_name(backup.name + ".report.json")
        _atomic(report_path, _bytes(report))
        try:
            report["run_storage"] = store.compact_storage(state, write_artifacts=True)
            store._validate_state(state)
            if _hash_bytes(_bytes(state["entities"])) != report["entities_sha256"] or [run["run_id"] for run in state["runs"]] != report["run_ids"]:
                raise StorageMigrationError("Study entity or Run identity changed during migration")
            updates[store.path] = _disk_bytes(state)
            report["source_changes"] = []
            for path, content in updates.items():
                report["source_changes"].append({"path": str(path), "before_sha256": _hash_file(path),
                                                  "after_sha256": _hash_bytes(content), "after_bytes": len(content)})
            report["status"] = "applying"
            _atomic(report_path, _bytes(report))
            for path, content in updates.items():
                _atomic(path, content)
            report["index"] = _rebuild_index(kb.root)
            verified = store._read()
            if (_hash_bytes(_bytes(verified["entities"])) != report["entities_sha256"] or
                    _run_digests(verified) != report["run_semantic_sha256"]):
                raise StorageMigrationError("post-migration Study entity or logical Run verification failed")
            for receipt in report["run_storage"]["artifacts"]:
                artifact = _destination(store.root, receipt["uri"])
                if artifact.stat().st_size != receipt["bytes"] or _hash_file(artifact) != receipt["sha256"]:
                    raise StorageMigrationError("post-migration artifact verification failed")
            report["study_bytes_after"] = store.path.stat().st_size
            report["knowledge_bytes_saved"] = sum(x["before_bytes"] - x["after_bytes"] for x in report["knowledge_conversions"])
            report["status"] = "applied"
            _atomic(report_path, _bytes(report))
            return report
        except BaseException as exc:
            _restore(backup, manifest)
            try:
                _rebuild_index(kb.root)
            except Exception as index_error:
                report["index_restore_error"] = repr(index_error)
            report.update(status="rolled_back_after_error", error=repr(exc))
            _atomic(report_path, _bytes(report))
            raise
