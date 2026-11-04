"""Read-only readiness checks for optional CAD/CAE execution submodules."""
from __future__ import annotations

import subprocess
import json
from pathlib import Path

from .backends import BindingError, check_binding, load_binding
from .install import execution_skill_status
from .patches import patch_status


def _git_head(path: Path):
    if not (path / ".git").is_file():
        return None, "submodule_git_marker_missing"
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path,
                                capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, type(exc).__name__
    if result.returncode:
        return None, "git_rev_parse_failed"
    return result.stdout.strip(), None


def _git_dirty(path: Path):
    try:
        result = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=path,
                                capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, type(exc).__name__
    if result.returncode:
        return None, "git_status_failed"
    return bool(result.stdout.strip()), None


def readiness(domain: str, backend_path, tools_path, *, repo_root=None, full=False,
              capability=None, maintenance=False):
    """Return local readiness; include patch/file diagnostics only when requested."""
    if domain not in {"cad", "cae"}:
        return {"status": "blocked", "ready": False, "reasons": ["domain must be cad or cae"]}
    root = Path(repo_root or Path(__file__).resolve().parent.parent).resolve()
    # ``full`` controls response detail only.  Repository-wide cleanliness,
    # pinned commits, and patch replay are maintenance diagnostics and must be
    # explicitly requested so an ordinary readiness probe stays lightweight.
    status = execution_skill_status(root, domains={domain}, check_patches=maintenance)
    reasons = []
    is_cae = domain == "cae"
    source_list = status["implementations"] if is_cae else status["skills"]
    source = next((item for item in source_list if item.get("domain") == domain), None)
    if source is None:
        reasons.append(f"no execution source registered for domain {domain}")
        source = {"path": str(root / "execution-skills" / domain), "status": "not_initialized",
                  "pinned_commit": None, "skill_path": None}
    if source["status"] != "available":
        reasons.append(f"execution {'implementation' if is_cae else 'Skill'} status is {source['status']}")
    source_path = Path(source["path"])
    head, git_error = ((None, "not_checked") if not maintenance
                       else _git_head(source_path))
    source["actual_commit"] = head
    dirty, dirty_error = ((None, "not_checked") if not maintenance
                          else (_git_dirty(source_path) if not git_error else (None, git_error)))
    source["dirty"] = dirty
    source["metadata_status"] = "available" if source["status"] == "available" else source["status"]
    source["pin_status"] = "matched" if head == source.get("pinned_commit") else ("not_verified" if git_error else "mismatch")
    patch_report = source.get("patch_status") or {"status": "not_checked", "ready": None,
                                                   "expected_dirty": False, "reasons": []}
    if maintenance:
        patch_report = source.get("patch_status") or patch_status(root, source, apply=False)
    source["patch_status"] = patch_report
    if dirty is False:
        source["clean_status"] = "clean"
    elif dirty_error:
        source["clean_status"] = "not_verified"
    elif patch_report.get("ready") and patch_report.get("expected_dirty"):
        source["clean_status"] = "controlled_patch_changes"
    else:
        source["clean_status"] = "dirty"
    if maintenance and source["pin_status"] != "matched":
        reasons.append(f"submodule commit {source['pin_status']}; expected {source.get('pinned_commit')} ({git_error or 'actual commit differs'})")
    if maintenance and source["clean_status"] not in {"clean", "controlled_patch_changes"}:
        reasons.append(f"submodule working tree {source['clean_status']} ({dirty_error or 'tracked changes detected'})")
    if maintenance and not patch_report.get("ready", False):
        patch_reasons = patch_report.get("reasons", []) or [
            f"patch state is {patch_report.get('status', 'unknown')}"]
        reasons.extend(f"execution patch: {reason}" for reason in patch_reasons)
    if is_cae:
        for field, label in (("documentation_path", "CAE MCP documentation"), ("entrypoint_path", "CAE MCP entrypoint")):
            if not Path(source.get(field, "")).is_file():
                reasons.append(f"{label} is missing")
    binding = None
    result = None
    try:
        binding = load_binding(backend_path)
        if binding.get("fixture"):
            reasons.append("fixture backend bindings are not eligible for execution readiness")
        if binding.get("domain") != domain:
            reasons.append(f"backend domain is {binding.get('domain')}, expected {domain}")
        inventory = json.loads(Path(tools_path).read_text(encoding="utf-8-sig"))
        if not isinstance(inventory, list) or any(not isinstance(name, str) for name in inventory):
            raise BindingError("tool inventory must be a JSON array of discovered names, not null")
        if capability is None:
            result = check_binding(binding, inventory, required_capabilities=())
        else:
            cap = binding.get("capabilities", {}).get(capability)
            if cap is None:
                raise BindingError(f"required capability not available: {capability}")
            names = set(inventory)
            missing_tools = [cap["tool"]] if cap.get("tool") not in names else []
            if cap.get("async") and cap.get("query_tool") not in names:
                missing_tools.append(cap["query_tool"])
            result = {"backend": binding["id"], "domain": binding["domain"],
                      "configuration_valid": True, "missing_capabilities": [],
                      "missing_tools": sorted(set(missing_tools)),
                      "discovery": "checked_against_supplied_inventory",
                      "live_execution": "not_verified", "fixture": bool(binding.get("fixture", False)),
                      "ready_for_binding_review": not missing_tools}
        if result["missing_capabilities"]:
            reasons.append("missing required capabilities: " + ", ".join(result["missing_capabilities"]))
        if result["missing_tools"]:
            reasons.append("missing concrete MCP tools: " + ", ".join(result["missing_tools"]))
    except (BindingError, OSError, ValueError, TypeError) as exc:
        result = None
        reasons.append(f"backend readiness input invalid: {exc}")
    ready = not reasons
    capability_tools = {name: cap["tool"] for name, cap in (binding.get("capabilities", {}).items() if binding else [])
                        if capability is None or name == capability}
    source_summary = {key: source.get(key) for key in
                      ("id", "domain", "status", "pinned_commit", "actual_commit",
                       "pin_status", "clean_status", "metadata_status")}
    if full:
        source_summary = source
    response = {"status": ("ready_for_mcp_docs_and_binding_review" if is_cae else "ready_for_skill_load_and_binding_review") if ready else "blocked", "ready": ready,
            "domain": domain, "backend": result,
            "codex_server": binding.get("codex_server") if binding and result else None,
            "capability_tools": capability_tools,
            "capabilities_path": (str(Path(source["path"]) / "capabilities.yaml")
                                  if not is_cae or (Path(source["path"]) / "capabilities.yaml").is_file() else None),
            "tools_inventory": str(tools_path), "skill_path": source.get("skill_path"),
            "reasons": reasons, "live_mcp": "not_verified", "host_discovery": "not_verified",
            "diagnostic_detail": "full" if full else "compact",
            "maintenance": bool(maintenance),
            "capability": capability,
            "engineering_validity": "not_verified"}
    if is_cae:
        response["implementation"] = source_summary
        response["documentation_path"] = source.get("documentation_path")
        response["skill_path"] = None
    else:
        response["skill"] = source_summary
    return response
