"""Immutable product baselines built on top of :mod:`eds.study`."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .assets import check_assets, fingerprint
from .experience import _write_atomic
from .knowledge import KnowledgeBase, KnowledgeError
from .personal_data import managed_data_root, resolve_alias
from .study import StudyError, StudyStore

SCHEMA = "eds-product-baseline/v1"
SNAPSHOT_SCHEMA = "eds-product-design-snapshot/v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_ROLES = {"drawing", "cad", "bom", "cae", "document", "text", "other"}
_ATTRIBUTION = {"document", "user", "codex"}
_VALIDATION = {"unverified", "verified"}


class ProductError(ValueError):
    """Malformed product, stale revision, or unsafe asset operation."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProductError(f"{field} must be nonempty text")
    return value.strip()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _private(path: Path) -> Path:
    repo = Path(__file__).resolve().parent.parent
    if any(path.is_relative_to((repo / name).resolve())
           for name in ("skills", ".agents/skills", "execution-skills")):
        raise ProductError("product data must stay outside distributable Skill directories")
    return path


def _contained(base: Path, relative: str) -> Path:
    relative = _text(relative, "relative location")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or ":" in relative or "\\" in relative:
        raise ProductError("asset location must be a contained relative path")
    target = (base / path).resolve()
    if not target.is_relative_to(base.resolve()):
        raise ProductError("asset location escapes its root")
    return target


def _copy_asset(source: Path, target: Path, expected: dict[str, Any]) -> None:
    """Publish verified bytes without replacing an existing content-addressed file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        if not target.exists():
            fd, name = tempfile.mkstemp(prefix="asset.", suffix=".tmp", dir=target.parent)
            temporary = Path(name)
            with os.fdopen(fd, "wb") as output, source.open("rb") as stream:
                shutil.copyfileobj(stream, output)
                output.flush()
                os.fsync(output.fileno())
            copied = fingerprint(temporary)
            if (copied["sha256"], copied["size_bytes"]) != (expected["sha256"], expected["size_bytes"]):
                raise ProductError("source asset changed during copying; no baseline was created")
            try:
                if os.name == "nt":
                    os.rename(temporary, target)
                else:
                    os.link(temporary, target)
            except FileExistsError:
                pass
        actual = fingerprint(target)
        if (actual["sha256"], actual["size_bytes"]) != (expected["sha256"], expected["size_bytes"]):
            raise ProductError("pinned asset conflicts with existing content")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _validate_statement(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProductError("statement must be an object")
    for key in ("id", "subject", "topic", "text", "attribution", "sources"):
        if key not in value:
            raise ProductError(f"statement requires {key}")
    result = copy.deepcopy(value)
    for key in ("id", "subject", "topic", "text", "attribution"):
        result[key] = _text(result[key], f"statement.{key}")
    if result["attribution"] not in _ATTRIBUTION:
        raise ProductError("statement.attribution is unsupported")
    if not isinstance(result["sources"], list) or (not result["sources"] and result["attribution"] != "codex"):
        raise ProductError("document and user statements require source locators")
    for source in result["sources"]:
        if not isinstance(source, dict) or not isinstance(source.get("locator"), str) or not source["locator"].strip():
            raise ProductError("each statement source requires locator")
        if not (isinstance(source.get("uri"), str) and source["uri"].strip()) and not (isinstance(source.get("asset_id"), str) and source["asset_id"].strip()):
            raise ProductError("each statement source requires uri or asset_id")
    result.setdefault("validation", "unverified")
    if result["validation"] not in _VALIDATION:
        raise ProductError("statement.validation is unsupported")
    if result["validation"] == "verified":
        evidence = result.get("verification_sources")
        if result["attribution"] == "codex" or not isinstance(evidence, list) or not evidence:
            raise ProductError("verified statement requires explicit verification_sources")
        for source in evidence:
            if not isinstance(source, dict) or not all(isinstance(source.get(k), str) and source[k].strip() for k in ("uri", "locator")):
                raise ProductError("verification_sources require uri and locator")
    if "unit" in result:
        _text(result["unit"], "statement.unit")
    return result


def _validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ProductError("unsupported product baseline schema")
    _text(payload.get("product_id"), "product_id")
    _text(payload.get("name"), "name")
    if not _SAFE_ID.fullmatch(payload["product_id"]):
        raise ProductError("product_id is unsafe")
    for field in ("assets", "statements", "gaps"):
        if not isinstance(payload.get(field), list):
            raise ProductError(f"{field} must be a list")
    asset_ids = set()
    for item in payload["assets"]:
        if not isinstance(item, dict) or not _SAFE_ID.fullmatch(_text(item.get("id"), "asset.id")):
            raise ProductError("asset.id is unsafe")
        if item["id"] in asset_ids or item.get("role") not in _ROLES:
            raise ProductError("asset ids must be unique and roles supported")
        asset_ids.add(item["id"])
        if not re.fullmatch(r"[0-9a-f]{64}", _text(item.get("sha256"), "asset.sha256")):
            raise ProductError("asset hash is invalid")
        if type(item.get("size")) is not int or item["size"] < 0:
            raise ProductError("asset.size must be nonnegative")
        _text(item.get("location"), "asset.location")
        if item.get("location_base") not in {"data/product", "product"}:
            raise ProductError("asset location base is invalid")
    ids = set()
    for item in payload["statements"]:
        statement = _validate_statement(item)
        if statement["id"] in ids:
            raise ProductError("statement ids must be unique")
        ids.add(statement["id"])
    for gap in payload["gaps"]:
        _text(gap, "gap")
    return copy.deepcopy(payload)


class ProductStore:
    def __init__(self, root: str | os.PathLike[str]):
        self.root = _private(Path(resolve_alias(root)).resolve())
        self.study = StudyStore(self.root)

    @classmethod
    def create(cls, root: str | os.PathLike[str], product_id: str, name: str) -> "ProductStore":
        product_id = _text(product_id, "product_id")
        name = _text(name, "name")
        if not _SAFE_ID.fullmatch(product_id):
            raise ProductError("product_id is unsafe")
        store = cls(root)
        if store.study.path.exists():
            raise ProductError("product root already exists")
        StudyStore.create(store.root, name, mode="coupled")
        # Keep an interrupted initial Study for reconciliation; never delete records
        # after an uncertain write or while another writer may have accessed them.
        store.study.add("design", {"schema": SCHEMA, "product_id": product_id, "name": name,
                                   "assets": [], "statements": [], "gaps": []}, ref="product-baseline", create_only=True)
        return store

    def _baseline(self, ref: str | None = None) -> dict[str, Any]:
        entity = self.study.get(kind="design", ref=ref or "product-baseline")
        if entity is None:
            raise ProductError("product baseline not found")
        if entity["logical_ref"] != "product-baseline":
            raise ProductError("reference is not product-baseline")
        _validate_payload(entity["payload"])
        original = self.study.get(kind="design", ref="product-baseline@1")
        if original["payload"].get("product_id") != entity["payload"]["product_id"]:
            raise ProductError("a product revision cannot change the product identity")
        return entity

    @staticmethod
    def _pinned(ref: str) -> str:
        if not isinstance(ref, str) or not re.fullmatch(r"product-baseline@[1-9][0-9]*", ref):
            raise ProductError("a pinned baseline reference product-baseline@N is required")
        return ref

    def show(self, ref: str | None = None) -> dict[str, Any]:
        return self._baseline(ref)

    def resume(self) -> dict[str, Any]:
        entity = self._baseline()
        payload = entity["payload"]
        stale = self._stale_sources(payload)
        return {"product_id": payload["product_id"], "name": payload["name"], "baseline_ref": entity["ref"],
                "assets": [{k: item.get(k) for k in ("id", "role", "sha256", "size", "revision")} for item in payload["assets"]],
                "statements": [{"id": item["id"], "subject": item["subject"], "topic": item["topic"], "attribution": item["attribution"],
                                "validation": item.get("validation", "unverified")} for item in payload["statements"]],
                "statement_count": len(payload["statements"]), "gaps": copy.deepcopy(payload["gaps"]), "stale_sources": stale}

    def _asset_root(self) -> tuple[Path, str]:
        managed = managed_data_root(self.root)
        if managed is not None:
            study_id = self.study.read()["study_id"] if self.study.path.exists() else self.root.name
            if not _SAFE_ID.fullmatch(study_id):
                raise ProductError("unsafe source Study identity")
            return _contained(managed / "assets", "products/" + study_id), "data/product"
        return _contained(self.root, "assets"), "product"

    def _asset_path(self, asset: dict[str, Any]) -> Path:
        owned, location_base = self._asset_root()
        if asset["location_base"] != location_base:
            raise ProductError("asset root changed; explicit rebinding is required")
        target = _contained(managed_data_root(self.root) or self.root, asset["location"])
        if not target.is_relative_to(owned):
            raise ProductError("asset location escapes product asset directory")
        return target

    def _editable(self, ref: str) -> dict[str, Any]:
        baseline = self._baseline(self._pinned(ref))
        if self._baseline()["ref"] != baseline["ref"]:
            raise ProductError("revision conflict: requested base is not the current revision")
        return baseline

    def attach(self, path: str | os.PathLike[str], *, asset_id: str, role: str, base_ref: str,
               revision: str | None = None) -> dict[str, Any]:
        asset_id, role = _text(asset_id, "asset_id"), _text(role, "role")
        if not _SAFE_ID.fullmatch(asset_id) or role not in _ROLES:
            raise ProductError("unsafe asset id or unsupported role")
        if revision is not None:
            revision = _text(revision, "revision")
        baseline = self._editable(base_ref)
        source = Path(path).expanduser().resolve(strict=True)
        inspected = fingerprint(source)
        payload = copy.deepcopy(baseline["payload"])
        digest = inspected["sha256"]
        target_root, location_base = self._asset_root()
        target = _contained(target_root, digest + "/" + source.name)
        _copy_asset(source, target, inspected)
        asset = {"id": asset_id, "role": role, "sha256": digest, "size": inspected["size_bytes"],
                 "location": target.relative_to(managed_data_root(self.root) or self.root).as_posix(),
                 "location_base": location_base}
        if revision is not None:
            asset["revision"] = _text(revision, "revision")
        payload["assets"] = [item for item in payload["assets"] if item.get("id") != asset_id]
        payload["assets"].append(asset)
        return self._commit(payload, baseline["ref"])

    def update(self, data: dict[str, Any], *, base_ref: str) -> dict[str, Any]:
        baseline = self._editable(base_ref)
        payload = copy.deepcopy(baseline["payload"])
        if not isinstance(data, dict):
            raise ProductError("update data must be an object")
        if set(data) - {"name", "statements", "remove_statement_ids", "gaps"}:
            raise ProductError("unsupported product update field")
        if "name" in data:
            payload["name"] = _text(data["name"], "name")
        if "statements" in data:
            incoming = data["statements"]
            if not isinstance(incoming, list):
                raise ProductError("statements must be a list")
            by_id = {item["id"]: item for item in payload["statements"]}
            incoming_ids = set()
            for item in incoming:
                normalized = _validate_statement(item)
                if normalized["id"] in incoming_ids:
                    raise ProductError("duplicate statement id in update")
                incoming_ids.add(normalized["id"])
                for source in normalized["sources"]:
                    if "asset_id" in source:
                        asset = next((a for a in payload["assets"] if a["id"] == source["asset_id"]), None)
                        if asset is None or source.get("sha256", asset["sha256"]) != asset["sha256"]:
                            raise ProductError("new statement source must reference the selected current asset")
                        source.update(sha256=asset["sha256"], location=asset["location"], location_base=asset["location_base"])
                by_id[normalized["id"]] = normalized
            payload["statements"] = list(by_id.values())
        if "remove_statement_ids" in data:
            ids = data["remove_statement_ids"]
            if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids):
                raise ProductError("remove_statement_ids must be a list")
            payload["statements"] = [x for x in payload["statements"] if x["id"] not in ids]
        if "gaps" in data:
            if not isinstance(data["gaps"], list):
                raise ProductError("gaps must be a list")
            payload["gaps"] = [_text(x, "gap") for x in data["gaps"]]
        return self._commit(payload, baseline["ref"])

    def _commit(self, payload: dict[str, Any], base_ref: str) -> dict[str, Any]:
        payload = _validate_payload(payload)
        try:
            return self.study.add("design", payload, ref=f"product-baseline@{self._baseline(self._pinned(base_ref))['version']}")
        except StudyError as exc:
            raise ProductError(str(exc)) from exc

    def _stale_sources(self, payload: dict[str, Any]) -> list[str]:
        assets = {item.get("id"): item for item in payload.get("assets", [])}
        stale = []
        for statement in payload.get("statements", []):
            for source in statement.get("sources", []):
                if "asset_id" in source:
                    asset = assets.get(source["asset_id"])
                    if asset is None or asset["sha256"] != source.get("sha256"):
                        stale.append(statement["id"])
                        break
        return sorted(set(stale))

    def check_assets(self, ref: str | None = None) -> dict[str, Any]:
        baseline = self._baseline(ref)
        payload = baseline["payload"]
        checked = []
        selected = list(payload["assets"])
        seen = {(a["location"], a["sha256"]) for a in selected}
        for statement in payload["statements"]:
            for source in statement["sources"]:
                if "asset_id" not in source:
                    continue
                if not all(source.get(k) for k in ("sha256", "location", "location_base")):
                    raise ProductError("statement asset source is missing its fixed locator")
                key = (source["location"], source["sha256"])
                if key not in seen:
                    selected.append({"id": source["asset_id"], "location": source["location"],
                                     "location_base": source["location_base"], "sha256": source["sha256"],
                                     "statement_id": statement["id"]})
                    seen.add(key)
        for asset in selected:
            target = self._asset_path(asset)
            result = check_assets([{"path": str(target), "sha256": asset["sha256"]}])["assets"][0]
            current = result["current"]
            checked.append({"id": asset["id"], "expected": asset["sha256"],
                            "actual": current["sha256"] if current else None,
                            "status": result["status"],
                            "statement_id": asset.get("statement_id"),
                            "ok": result["status"] == "unchanged" and
                            ("size" not in asset or current["size_bytes"] == asset["size"])})
        return {"baseline_ref": baseline["ref"], "assets": checked, "ok": all(x["ok"] for x in checked)}

    def use(self, study_root: str | os.PathLike[str], *, baseline_ref: str) -> dict[str, Any]:
        target = _private(Path(resolve_alias(study_root)).resolve())
        if target == self.root:
            raise ProductError("product cannot be bound to itself")
        try:
            target_store = StudyStore(target)
            state = target_store.read()
        except (OSError, StudyError) as exc:
            raise ProductError("use requires an existing Study root") from exc
        if state.get("schema") != "eds-study/v1" or state.get("mode") not in {"cad", "cae", "coupled"}:
            raise ProductError("use requires an existing CAD, CAE, or coupled Study")
        if any(e["payload"].get("schema") == SCHEMA for e in state["entities"]):
            raise ProductError("target must be a task Study, not another product baseline")
        baseline_ref = self._pinned(baseline_ref)
        baseline = self._baseline(baseline_ref)
        if not self.check_assets(baseline_ref)["ok"]:
            raise ProductError("product assets are missing or tampered; review before reuse")
        source_data = managed_data_root(self.root)
        asset_context = ({"base": "data-root", "product_path": self.root.relative_to(source_data).as_posix()}
                         if source_data and managed_data_root(target) == source_data else
                         {"base": "external", "product_root": str(self.root),
                          "data_root": str(source_data) if source_data else None, "requires_rebind_on_move": True})
        payload = {"schema": SNAPSHOT_SCHEMA, "product_id": baseline["payload"]["product_id"],
                   "name": baseline["payload"]["name"], "asset_context": asset_context,
                   "stale_source_statements": self._stale_sources(baseline["payload"]),
                   "source_product_study_id": self.study.read()["study_id"], "baseline_ref": baseline["ref"],
                   "content_hash": hashlib.sha256(_canonical(baseline["payload"]).encode()).hexdigest(),
                   "baseline": copy.deepcopy(baseline["payload"]), "frozen": True}
        logical = f"product-{baseline['payload']['product_id']}"
        existing = target_store.get(kind="design", ref=logical)
        if existing:
            if existing["payload"] == payload:
                return existing
            old = existing["payload"]
            if old.get("schema") != SNAPSHOT_SCHEMA or old.get("source_product_study_id") != payload["source_product_study_id"]:
                raise ProductError("target already has a different design identity")
            try:
                return target_store.add("design", payload, ref=existing["ref"])
            except StudyError as exc:
                raise ProductError(str(exc)) from exc
        try:
            return target_store.add("design", payload, ref=logical, create_only=True)
        except StudyError as exc:
            raise ProductError(str(exc)) from exc

    def publish(self, *, baseline_ref: str, knowledge_root: str | os.PathLike[str] | None = None) -> dict[str, Any]:
        baseline_ref = self._pinned(baseline_ref)
        baseline = self._baseline(baseline_ref)
        managed = managed_data_root(self.root)
        if knowledge_root is None:
            if managed is None:
                raise ProductError("knowledge_root is required for an unmanaged product")
            knowledge_root = managed / "knowledge"
        kb = KnowledgeBase(knowledge_root)
        _private(kb.root)
        state = self.study.read()
        ident = "product-" + state["study_id"]
        version = str(baseline["version"])
        directory = _contained(kb.root, "products/" + hashlib.sha256(ident.encode()).hexdigest()[:24])
        json_path = _contained(kb.root, (directory / f"v{version}.json").relative_to(kb.root).as_posix())
        md_path = _contained(kb.root, (directory / f"v{version}.md").relative_to(kb.root).as_posix())
        snapshot = {"schema": SCHEMA, "id": ident, "version": baseline["version"], "study_id": state["study_id"],
                    "baseline_ref": baseline["ref"], "product": copy.deepcopy(baseline["payload"]),
                    "stale_source_statements": self._stale_sources(baseline["payload"])}
        raw = (_canonical(snapshot) + "\n").encode("utf-8")
        source_hash = hashlib.sha256(raw).hexdigest()
        meta = {"id": ident, "version": version, "type": "design", "title": baseline["payload"]["name"],
                "attribution": "product_baseline", "sources": [{"uri": json_path.relative_to(kb.root).as_posix(), "locator": "$", "sha256": source_hash}],
                "conditions": {"product_id": baseline["payload"]["product_id"]}, "relations": [], "data_schema": SCHEMA,
                "date": baseline["created_at"], "question": "design", "project": baseline["payload"]["product_id"]}
        md = "<!-- eds-knowledge: " + json.dumps(meta, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + " -->\n\n# " + baseline["payload"]["name"] + "\n\n```json\n" + json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n```\n"
        with KnowledgeBase(kb.cache_root / ".product-publication")._lock():
            files = ((json_path, raw), (md_path, md.encode("utf-8")))
            for path, content in files:
                if path.exists() and path.read_bytes() != content:
                    raise ProductError("published product revision conflicts with existing content")
            for path, content in files:
                if not path.exists():
                    _write_atomic(path, content)
            try:
                indexed = kb.register(md_path)
            except (KnowledgeError, OSError) as exc:
                raise ProductError(f"product saved but indexing is pending: {exc}") from exc
        return {"id": ident, "version": baseline["version"], "path": str(md_path), "snapshot_path": str(json_path),
                "hash": source_hash, "indexed": bool(indexed.get("indexed"))}


__all__ = ["ProductError", "ProductStore", "SCHEMA", "SNAPSHOT_SCHEMA"]
