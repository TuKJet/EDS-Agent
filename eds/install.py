"""Install repository-scoped skill copies without changing Codex user settings."""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from .patches import patch_status

SKILLS = ("eds-study", "eds-cad", "eds-cae", "eds-coupled")
REPO_ROOT = Path(__file__).resolve().parent.parent
EXECUTION_SKILL_ROOT = "execution-skills"
KNOWN_EXECUTION_SKILLS = (
    {"id": "solidworks-automation-skill", "domain": "cad", "expected_name": "solidworks-automation",
     "source_url": "https://github.com/TuKJet/solidworks-automation-skill.git",
     "branch": "vm-sw-automation-skill", "pinned_commit": "8a572ce6fa4d78e6ee75f03cc14547cf94830d8a",
     "patch_manifest": "patches/solidworks-automation-skill/manifest.json"},
)
KNOWN_EXECUTION_IMPLEMENTATIONS = (
    {"id": "cae-agent-hub", "domain": "cae",
     "source_url": "https://github.com/Cai-aa/CAE-Agent-Hub.git",
     "branch": "main", "pinned_commit": "56705e07ce6e99f0d5a0d0c7b5e28b6b2c0bc973",
     "documentation_path": "MCP/COMSOL/README.md", "entrypoint_path": "MCP/COMSOL/mcp_server.py",
     "task_skill_path": None,
     "task_skill_note": "The repository's motor NVH Skill is task-specific; no general CAE Skill is assumed."},
)


def execution_skill_status(repo_root=REPO_ROOT, *, patch_reports=None, domains=None,
                           check_patches=True):
    """Report optional maintained execution skills without copying or importing them."""
    root = Path(repo_root).resolve() / EXECUTION_SKILL_ROOT
    selected_domains = set(domains) if domains is not None else {"cad", "cae"}
    if not selected_domains <= {"cad", "cae"}:
        raise ValueError("domains must contain only cad or cae")
    entries = []
    for known in KNOWN_EXECUTION_SKILLS:
        if known["domain"] not in selected_domains:
            continue
        folder = root / known["id"]
        skill_file = folder / "SKILL.md"
        item = {**known, "path": str(folder), "skill_path": str(skill_file),
                "status": "not_initialized", "host_installation": "not_checked",
                "recommendation": "optional"}
        item["patch_manifest"] = known.get("patch_manifest")
        if skill_file.is_file():
            text = skill_file.read_text(encoding="utf-8-sig", errors="replace")
            name = next((line.split(":", 1)[1].strip().strip('"')
                         for line in text.splitlines() if line.startswith("name:")), None)
            item["name"] = name
            item["status"] = "available" if name == known["expected_name"] else "metadata_mismatch"
        else:
            item["name"] = None
        entries.append(item)
    implementations = []
    for known in KNOWN_EXECUTION_IMPLEMENTATIONS:
        if known["domain"] not in selected_domains:
            continue
        folder = root / known["id"]
        item = {**known, "path": str(folder), "status": "not_initialized",
                "host_installation": "not_checked", "recommendation": "optional"}
        documentation = folder / known["documentation_path"]
        entrypoint = folder / known["entrypoint_path"]
        item["documentation_path"] = str(documentation)
        item["entrypoint_path"] = str(entrypoint)
        if folder.exists():
            if documentation.is_file() and entrypoint.is_file() and (folder / ".git").is_file():
                item["status"] = "available"
            elif documentation.is_file() and entrypoint.is_file():
                item["status"] = "submodule_not_initialized"
            else:
                item["status"] = "missing_documentation_or_entrypoint"
        implementations.append(item)
    # Patch state is deliberately kept separate from the metadata check.  This
    # lets callers report a valid, initialized submodule which still needs the
    # repository-owned compatibility patch.
    patch_items = []
    known_reports = {report.get("id"): report for report in (patch_reports or [])}
    for item in [*entries, *implementations]:
        if item["domain"] not in selected_domains or not check_patches:
            report = {"id": item["id"], "status": "not_checked", "ready": None,
                      "expected_dirty": False, "reasons": []}
        else:
            report = known_reports.get(item["id"]) or patch_status(Path(repo_root).resolve(), item, apply=False)
        item["patch_status"] = report
        patch_items.append(report)
    all_sources = [item for item in [*entries, *implementations] if item["domain"] in selected_domains]
    overall_status = ("not_checked" if not selected_domains
                      else "metadata_mismatch" if any(item["status"] == "metadata_mismatch" for item in all_sources)
                      else "available" if all(item["status"] == "available" for item in all_sources)
                      else "not_initialized")
    return {
        "root": str(root),
        "skills": entries,
        "implementations": implementations,
        "execution_patches": patch_items,
        "status": overall_status,
        "install_hint": "git submodule update --init --recursive" if any(item["status"] != "available" for item in all_sources) else None,
        "pending": [],
        "scope": "optional_submodule_only",
        "note": "Execution skills are maintained in their source repositories; EDS records methods, state and evidence.",
    }


def install_skills(repo_root=REPO_ROOT, *, check=False, update=False, source_root=None,
                   execution="auto"):
    if execution not in {"auto", "cad", "cae", "none"}:
        raise ValueError("execution must be auto, cad, cae, or none")
    root = Path(repo_root).resolve()
    source = Path(source_root).resolve() if source_root else root / "skills"
    destination = root / ".agents" / "skills"
    pairs, changes = [], []
    for name in SKILLS:
        folder = source / name
        if not (folder / "SKILL.md").is_file():
            raise ValueError(f"missing source skill: {name}")
        for src in sorted(folder.rglob("*")):
            if not src.is_file():
                continue
            dest = destination / name / src.relative_to(folder)
            if not dest.resolve().is_relative_to(root):
                raise ValueError("skill destination resolves outside repository")
            for part in (dest, *dest.parents):
                if part == root:
                    break
                if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
                    raise ValueError(f"skill destination uses a linked path: {part}")
            same = dest.is_file() and hashlib.sha256(src.read_bytes()).digest() == hashlib.sha256(dest.read_bytes()).digest()
            if not same:
                changes.append(str(dest.relative_to(root)))
                if not check and dest.exists() and not update:
                    raise ValueError(f"skill differs: {dest}; review it then use --update")
                pairs.append((src, dest))
    # Complete the copy conflict preflight before applying any vendor patch.
    # A local EDS edit must never be left half-installed because a patch then
    # fails (and a patch must never overwrite an unrelated vendor edit).
    selected = [] if execution == "none" else ([execution] if execution in {"cad", "cae"} else ["cad", "cae"])
    known_sources = {item["domain"]: item for item in
                     [*KNOWN_EXECUTION_SKILLS, *KNOWN_EXECUTION_IMPLEMENTATIONS]}
    patch_reports = []
    for domain in selected:
        known = known_sources[domain]
        report = patch_status(root, known, apply=False)
        patch_reports.append(report)
        if report.get("status") in {"not_initialized", "not_required"}:
            if execution != "auto":
                folder = root / EXECUTION_SKILL_ROOT / known["id"]
                if report.get("status") == "not_initialized" or not (folder / ".git").is_file():
                    raise ValueError(f"execution submodule is not initialized: {domain}")
            continue
        if report.get("status") != "ready_to_apply" and not report.get("ready", False):
            raise ValueError(f"execution patch preflight blocked for {domain}: " +
                             "; ".join(report.get("reasons", [])))
    if not check:
        for report, domain in zip(patch_reports, selected):
            if report.get("status") == "ready_to_apply":
                report = patch_status(root, known_sources[domain], apply=True)
                if not report.get("ready", False):
                    raise ValueError(f"execution patch application failed for {domain}: " +
                                     "; ".join(report.get("reasons", [])))
                patch_reports[selected.index(domain)] = report
        for src, dest in pairs:
            dest.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".eds-", dir=dest.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(src.read_bytes())
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, dest)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    patch_ready = all(report.get("ready", False)
                      or (execution == "auto" and report.get("status") == "not_initialized")
                      for report in patch_reports)
    return {"root": str(root), "skills": list(SKILLS), "mode": "check" if check else "install",
            "changed_or_missing": changes, "in_sync": (not changes and patch_ready) if check else patch_ready,
            "scope": "repository", "host_discovery": "requires_Codex_observation",
            "execution_patches": patch_reports,
            # ``execution=none`` is an explicit request to install/check only
            # the core EDS skills.  Do not re-scan vendor patch state while
            # assembling the summary (that scan used to make a no-execution
            # check unexpectedly touch both optional submodules).
            "execution_skills": execution_skill_status(
                root, patch_reports=patch_reports,
                domains=selected,
                check_patches=bool(selected))}
