"""JSON CLI for Codex's deterministic engineering helpers."""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import sqlite3
import sys
from pathlib import Path

from . import __version__
from .assets import check_assets, fingerprint
from .backends import check_binding, load_binding, normalize_status, prepare_call
from .install import REPO_ROOT, install_skills
from .execution import readiness
from .knowledge import KnowledgeBase, knowledge_route
from .presets import PresetStore, validate_snapshot
from .study import StudyStore


def read_json(path):
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8-sig")
    return json.loads(text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"nonfinite JSON: {value}")))


def parser():
    app = argparse.ArgumentParser(prog="python -m eds", description="Codex engineering record and knowledge tools; no model or MCP execution loop")
    app.add_argument("--version", action="version", version=__version__)
    commands = app.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check local Python, SQLite FTS5 and skill sources")
    install = commands.add_parser("install-skills", help="Install this repository's Codex skills")
    install.add_argument("--check", action="store_true")
    install.add_argument("--update", action="store_true")
    install.add_argument("--execution", choices=("auto", "cad", "cae", "none"), default="auto",
                         help="Apply/check repository-owned execution submodule patches")
    study = commands.add_parser("study", help="Versioned engineering study records")
    study.add_argument("root", help="Study workspace, separate from the skill package")
    actions = study.add_subparsers(dest="action", required=True)
    init = actions.add_parser("init")
    init.add_argument("--goal", required=True)
    init.add_argument("--mode", choices=("cad", "cae", "coupled"), required=True)
    init.add_argument("--context", help="JSON object with constraints/assets/facts/assumptions/gaps")
    add = actions.add_parser("add")
    add.add_argument("kind")
    add.add_argument("--data", required=True, help="JSON payload file; - reads stdin")
    add.add_argument("--ref", help="Stable logical identity when creating a new revision")
    show = actions.add_parser("show")
    show.add_argument("--ref")
    show.add_argument("--kind")
    show.add_argument("--run")
    resume = actions.add_parser("resume")
    resume.add_argument("--full", action="store_true")
    actions.add_parser("report")
    impact = actions.add_parser("impact")
    impact.add_argument("ref")
    run = actions.add_parser("run")
    run.add_argument("--data", required=True, help="JSON with experiment_ref/input_refs/backend/capability/input_snapshot/idempotency_key")
    run.add_argument("--preset-task", help="Pinned task preset JSON; no knowledge search or preference write")
    transition = actions.add_parser("transition")
    transition.add_argument("run_id")
    transition.add_argument("status")
    transition.add_argument("--data", help="JSON observed output, task_id and observed_at")
    preferences = actions.add_parser("preferences")
    preferences.add_argument("extraction", choices=("once", "auto", "later", "skip"))
    summary = actions.add_parser("summary")
    summary.add_argument("--data", required=True)
    for name in ("context", "metrics", "extraction"):
        action = actions.add_parser(name)
        action.add_argument("--data", required=True)
    kb = commands.add_parser("kb", help="Explicit Markdown knowledge registration and retrieval")
    kb.add_argument("root", help="Independent knowledge workspace")
    actions = kb.add_subparsers(dest="action", required=True)
    for name in ("status", "sync", "rebuild"):
        actions.add_parser(name)
    for name in ("register", "unregister"):
        item = actions.add_parser(name)
        item.add_argument("path", help="Markdown path relative to knowledge root")
    search = actions.add_parser("search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--type")
    search.add_argument("--domain")
    search.add_argument("--project")
    search.add_argument("--question", help="Purpose route; explicit question takes priority over stage")
    search.add_argument("--stage", help="Fallback route when the question is not specified")
    search.add_argument("--user", help="User identity for scoped engineering preferences")
    search.add_argument("--team", help="Team identity for scoped engineering preferences")
    search.add_argument("--preference-status", choices=("candidate", "confirmed", "retired"),
                        help="Explicit preference review; normal retrieval uses confirmed preferences")
    route = actions.add_parser("route", help="Show a local knowledge route without searching or writing")
    route.add_argument("--question")
    route.add_argument("--stage")
    read = actions.add_parser("read")
    read.add_argument("unit_id")
    read.add_argument("--version")
    read.add_argument("--depth", type=int, default=0, help="Explicit related-unit expansion depth; default 0")
    read.add_argument("--relation", action="append", help="Expand only this relation type; repeat to select more")
    read.add_argument("--max-units", type=int, default=20, help="Bound explicit expansion")
    preset = commands.add_parser("preset", help="Active execution presets in a user-selected knowledge workspace")
    preset.add_argument("root", help="Knowledge workspace; never a distributable skill directory")
    actions = preset.add_subparsers(dest="action", required=True)
    for name in ("activate", "current", "task", "save-default"):
        action = actions.add_parser(name)
        action.add_argument("--context", required=True, help="JSON domain/question and actual user/team/project identities")
        if name == "activate":
            action.add_argument("name", help="Named preset to select")
            action.add_argument("--refs", help="JSON array of explicit {id, version} preference references; [] starts empty")
        if name in ("task", "save-default"):
            action.add_argument("--overrides", required=name == "save-default", help="JSON preference_key -> nonempty text; task changes are temporary")
        if name == "task":
            action.add_argument("--output", help="Pin a task snapshot file; a different existing snapshot is never overwritten")
        if name == "save-default":
            action.add_argument("--source", required=True, help="Source locator for the user's explicit reusable preference")
            action.add_argument("--scope", choices=("user", "team", "project"), default="user")
    backend = commands.add_parser("backend", help="Validate local binding descriptions; does not call MCP")
    backend.add_argument("binding", help="User-authored eds-backend/v1 JSON file")
    actions = backend.add_subparsers(dest="action", required=True)
    check = actions.add_parser("check")
    check.add_argument("--tools", help="JSON array of actually discovered tool names")
    prepare = actions.add_parser("prepare")
    prepare.add_argument("capability")
    prepare.add_argument("--data", required=True)
    status = actions.add_parser("status")
    status.add_argument("capability")
    status.add_argument("raw_status")
    asset = commands.add_parser("asset", help="Fingerprint explicitly selected local engineering assets")
    actions = asset.add_subparsers(dest="action", required=True)
    capture = actions.add_parser("inspect")
    capture.add_argument("path")
    compare = actions.add_parser("check")
    compare.add_argument("--data", required=True, help="JSON array of earlier fingerprints")
    execution = commands.add_parser("execution", help="Read-only readiness for an optional execution Skill")
    execution.add_argument("domain", choices=("cad", "cae"))
    execution.add_argument("--backend", required=True)
    execution.add_argument("--tools", required=True)
    execution.add_argument("--capability", help="Check only the capability needed for the current operation")
    execution.add_argument("--maintenance", action="store_true", help="Explicitly check selected local source and patches")
    execution.add_argument("--full", action="store_true", help="Show detailed output without changing the check scope")
    return app


def dispatch(args):
    if args.command == "doctor":
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE VIRTUAL TABLE smoke USING fts5(content)")
        return {"eds_version": __version__, "python": platform.python_version(), "python_supported": sys.version_info >= (3, 11),
                "sqlite": sqlite3.sqlite_version, "fts5": True, "codex_cli_present": bool(shutil.which("codex")),
                "skill_installation": install_skills(check=True), "real_backend_validation": "not_checked_by_doctor"}
    if args.command == "install-skills":
        return install_skills(check=args.check, update=args.update, execution=args.execution)
    if args.command == "study":
        if args.action == "init":
            context = read_json(args.context) if args.context else {}
            return StudyStore.create(args.root, args.goal, mode=args.mode, **context).read()
        store = StudyStore(args.root)
        if args.action == "add":
            return store.add(args.kind, read_json(args.data), ref=args.ref)
        if args.action == "show":
            if args.run is not None:
                if args.ref is not None or args.kind is not None:
                    raise ValueError("--run cannot be combined with --ref or --kind")
                return store.get_run(args.run)
            return store.get(kind=args.kind, ref=args.ref) if args.ref or args.kind else store.read()
        if args.action in ("resume", "report"):
            return store.resume(full=args.full) if args.action == "resume" else store.render_report()
        if args.action == "impact":
            return store.impact(args.ref)
        if args.action == "run":
            data = read_json(args.data)
            if args.preset_task:
                if "execution_preset" in data or "execution_preset" in data.get("input_snapshot", {}):
                    raise ValueError("preset supplied twice; choose --preset-task or the Run payload")
                data["execution_preset"] = read_json(args.preset_task)
            return store.add_run(**data)
        if args.action == "transition":
            return store.transition_run(args.run_id, args.status, **(read_json(args.data) if args.data else {}))
        if args.action == "preferences":
            return store.set_preferences(args.extraction)
        if args.action == "summary":
            return store.set_summary(**read_json(args.data))
        if args.action == "context":
            return store.update_context(**read_json(args.data))
        if args.action == "metrics":
            return store.set_metrics(**read_json(args.data))
        if args.action == "extraction":
            return store.record_extraction(**read_json(args.data))
    if args.command == "kb":
        if args.action == "route":
            return knowledge_route(question=args.question, stage=args.stage)
        kb = KnowledgeBase(args.root)
        if args.action in ("status", "sync", "rebuild"):
            return getattr(kb, args.action)()
        if args.action in ("register", "unregister"):
            return getattr(kb, args.action)(args.path)
        if args.action == "search":
            filters = {key: getattr(args, key) for key in
                       ("type", "domain", "project", "question", "stage", "user", "team", "preference_status")
                       if getattr(args, key) is not None}
            matches = kb.search(args.query, limit=args.limit, **filters)
            route = knowledge_route(question=args.question, stage=args.stage)
            if args.type is not None:
                route = {**route, "selected_types": [args.type], "primary_types": [args.type],
                         "selection": "explicit_type"}
            return {"retrieval": "matched" if matches else "no_match",
                    "route": route, "matches": matches}
        return kb.read(args.unit_id, version=args.version, depth=args.depth,
                       relation_types=args.relation, max_units=args.max_units)
    if args.command == "preset":
        presets = PresetStore(args.root)
        context = read_json(args.context)
        if args.action == "activate":
            return presets.activate(args.name, context=context, refs=read_json(args.refs) if args.refs else None)
        if args.action == "current":
            return presets.current(context=context)
        if args.action == "save-default":
            return presets.save_default(context=context, overrides=read_json(args.overrides),
                                        source=args.source, scope=args.scope)
        snapshot = presets.for_task(context=context, overrides=read_json(args.overrides) if args.overrides else None)
        if args.output:
            # Task snapshots are immutable batch inputs, not preference memories.
            target = Path(args.output)
            if target.exists():
                existing = read_json(str(target))
                validate_snapshot(existing)
                if existing != snapshot:
                    raise ValueError("task preset output already pins a different snapshot; use a new output path")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("x", encoding="utf-8") as stream:
                    json.dump(snapshot, stream, ensure_ascii=False, indent=2, allow_nan=False)
                    stream.write("\n")
        return snapshot
    if args.command == "backend":
        binding = load_binding(args.binding)
        if args.action == "check":
            return check_binding(binding, read_json(args.tools) if args.tools else None)
        if args.action == "prepare":
            return prepare_call(binding, args.capability, read_json(args.data))
        return normalize_status(binding, args.capability, args.raw_status)
    if args.command == "asset":
        return fingerprint(args.path) if args.action == "inspect" else check_assets(read_json(args.data))
    if args.command == "execution":
        return readiness(args.domain, args.backend, args.tools, full=args.full,
                         capability=args.capability, maintenance=args.maintenance)
    raise ValueError("unsupported command")


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        result = dispatch(args)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        if args.command == "install-skills" and args.check and (
                not result["in_sync"] or any(not report.get("ready", False)
                                             for report in result.get("execution_patches", []))):
            return 1
        if args.command == "execution" and not result.get("ready", False):
            return 1
        return 0
    except (ValueError, TypeError, KeyError, OSError, sqlite3.DatabaseError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
