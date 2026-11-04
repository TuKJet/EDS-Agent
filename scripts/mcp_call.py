"""Execute one Codex-directed operation using an existing official MCP SDK.

Use a Python environment containing mcp and httpx. There is no research loop
or automatic tool retry. Tokens are read only from the named environment variable.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit


class ExistingRunError(RuntimeError):
    """A recorded request already exists and must not be submitted again."""

    def __init__(self, run, message=None):
        self.run = run
        super().__init__(message or
                         "idempotent MCP run already exists with status " + run["status"])


def _action_snapshot(snapshot):
    """Exclude the local evidence destination from action identity."""
    return {key: value for key, value in snapshot.items() if key != "output_path"}


# The helper is normally launched as a file, so make the repository package
# available without requiring an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _call_data(args):
    if getattr(args, "_data", None) is not None:
        return args._data
    data = json.loads(Path(args.data).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("tool arguments must be a JSON object")
    return data


def _validate_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("use a plain HTTP(S) MCP URL without credentials, query or fragment")


def _prepare_run(args, tool_name, data, output_path):
    if not args.study_root or not args.experiment_ref:
        return None, None
    from eds import StudyStore

    binding = getattr(args, "_binding", None)
    backend = binding["id"] if binding else "mcp"
    capability = args.capability if binding else tool_name
    read_only = bool(binding and binding["capabilities"][args.capability].get("read_only", False))
    store = StudyStore(args.study_root)
    experiment_ref = store.get(ref=args.experiment_ref)["ref"]
    input_refs = [store.get(ref=ref)["ref"] for ref in args.input_ref]
    binding_snapshot = {}
    if binding:
        cap = binding["capabilities"][args.capability]
        binding_snapshot = {
            "binding_id": binding["id"], "codex_server": binding["codex_server"],
            "capability": args.capability, "async": cap.get("async", False),
            "query_tool": cap.get("query_tool"), "task_id_field": cap.get("task_id_field"),
            "read_only": read_only,
        }
    input_snapshot = {"tool": tool_name, "arguments": data,
                      "server_url": args.url, "expected_server": args.expected_server,
                      **binding_snapshot}
    canonical = json.dumps(
        {"backend": backend, "server": (binding or {}).get("expected_server") or
         args.expected_server or (binding or {}).get("codex_server") or args.url,
         "capability": capability, "tool": tool_name, "experiment_ref": experiment_ref,
         "input_refs": input_refs, "arguments": data},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    base_key = "mcp-" + hashlib.sha256(canonical).hexdigest()
    key = base_key
    current_server = args.expected_server or (binding or {}).get("expected_server") or args.url
    runs = store.read().get("runs", [])
    existing = next((prior for prior in runs if prior.get("idempotency_key") == key), None)
    if existing is not None:
        same_request = (
            existing.get("experiment_ref") == experiment_ref and
            existing.get("input_refs") == input_refs and
            existing.get("backend") == backend and
            existing.get("capability") == capability and
            {**_action_snapshot(existing.get("input_snapshot", {})),
             "read_only": existing.get("input_snapshot", {}).get("read_only", False)}
            == {**input_snapshot, "read_only": read_only}
        )
        if not same_request:
            raise ExistingRunError(existing, "idempotency key reused with a different request")
        if existing["status"] == "planned":
            return store, store.transition_run(existing["run_id"], "submitting")
        retry_runs = [prior for prior in runs
                      if isinstance(prior.get("idempotency_key"), str)
                      and prior["idempotency_key"].startswith(base_key + ":retry-")]
        latest = existing
        if retry_runs:
            latest = max(retry_runs, key=lambda prior: int(prior["idempotency_key"].rsplit("-", 1)[1]))
        if latest["status"] == "planned":
            return store, store.transition_run(latest["run_id"], "submitting")
        retryable_preflight = (latest["status"] == "failed" and
                               isinstance(latest.get("output"), dict) and
                               latest["output"].get("preflight_rejected") is True and
                               latest["output"].get("tool_sent") is False)
        if not (read_only and latest["status"] == "completed") and not retryable_preflight:
            raise ExistingRunError(latest)
        # A read-only observation is allowed to run again after a completed
        # observation; a local preflight rejection can be retried after repair.
        ordinal = 1
        while any(prior.get("idempotency_key") == f"{base_key}:retry-{ordinal}" for prior in runs):
            ordinal += 1
        key = f"{base_key}:retry-{ordinal}"
    for prior in store.read().get("runs", []):
        snapshot = prior.get("input_snapshot", {})
        prior_identity = ((prior.get("backend") == "mcp" and prior.get("capability") == tool_name) or
                          (binding and prior.get("backend") == binding["id"] and
                           prior.get("capability") == args.capability))
        server_match = ((snapshot.get("expected_server") and snapshot.get("expected_server") == current_server) or
                        (not snapshot.get("expected_server") and snapshot.get("server_url") == args.url))
        if (prior.get("idempotency_key") != key and prior_identity and
                prior.get("experiment_ref") == experiment_ref and prior.get("input_refs") == input_refs and
                snapshot.get("tool") == tool_name and snapshot.get("arguments") == data and
                server_match and
                prior.get("status") in {"submitting", "submitted", "running", "unknown"}):
            raise ExistingRunError(
                prior, "idempotent legacy MCP run already exists with status " + prior["status"])
    for prior in store.read().get("runs", []):
        snapshot = prior.get("input_snapshot", {})
        prior_server = snapshot.get("expected_server") or snapshot.get("server_url")
        if (prior.get("experiment_ref") == experiment_ref and
                snapshot.get("tool") == tool_name and
                prior_server == current_server and
                snapshot.get("arguments") == data and
                prior.get("status") in {"submitting", "submitted", "running", "unknown"}):
            raise ExistingRunError(prior, "matching MCP action is pending or uncertain; query the existing run before retrying")
    run = store.add_run(
        experiment_ref=experiment_ref,
        input_refs=input_refs,
        backend=binding["id"] if binding else "mcp",
        capability=capability,
        input_snapshot=input_snapshot,
        idempotency_key=key,
    )
    if run["status"] != "planned":
        raise ExistingRunError(run)
    run = store.transition_run(run["run_id"], "submitting")
    return store, run


def _operation_failed(result):
    """Detect an explicit backend operation failure without judging geometry."""
    for value in _decoded_operation_payloads(result):
        status = str(value.get("status", "")).lower()
        if (status in {"error", "failed", "failure", "fail", "blocked"}
                or value.get("success") is False or value.get("ok") is False):
            return True
    return False


def _decoded_operation_payloads(result):
    """Yield structured operation payloads or explicit Markdown failure status."""
    payload = result.get("result", {}) if isinstance(result, dict) else {}
    candidates = []
    structured = payload.get("structuredContent") if isinstance(payload, dict) else None
    if isinstance(structured, dict):
        candidates.extend((structured, structured.get("result")))
    for item in payload.get("content", []) if isinstance(payload, dict) else []:
        if isinstance(item, dict) and item.get("type") == "text":
            candidates.append(item.get("text"))
    for candidate in candidates:
        value = candidate
        if isinstance(candidate, str):
            try:
                value = json.loads(candidate)
            except (TypeError, ValueError):
                # Some tools render their operation status as a Markdown heading.
                # Only an exact leading status is a failure, not a quoted example
                # or an error mentioned later in an otherwise successful report.
                lines = candidate.strip().splitlines()
                heading = lines[0].strip().lower() if lines else ""
                if heading not in {"# error", "# failed", "# failure", "# fail", "# blocked"}:
                    continue
                value = {"status": heading[2:]}
        if isinstance(value, dict):
            yield value


def _task_ids(result, field):
    """Extract nonempty dotted-path task ids, retaining ambiguity information."""
    values = []
    for payload in _decoded_operation_payloads(result):
        value = payload
        for part in field.split("."):
            if not isinstance(value, dict) or part not in value:
                value = None
                break
            value = value[part]
        if isinstance(value, str) and value.strip():
            values.append(value)
        elif type(value) in (int, float) and math.isfinite(value):
            values.append(str(value))
    return sorted(set(values))


def _preflight(*, server_name, expected_server, tools, tool_name, arguments, query_tool=None):
    """Validate routing and exact MCP arguments before sending a tool call."""
    if expected_server and server_name != expected_server:
        return {"preflight_rejected": True, "preflight_error": "wrong_server",
                "expected_server": expected_server, "server_name": server_name,
                "tool_sent": False}
    tool = next((item for item in tools if item.get("name") == tool_name), None)
    if tool is None:
        return {"preflight_rejected": True, "preflight_error": "missing_tool",
                "server_name": server_name, "tool": tool_name, "tool_sent": False}
    if query_tool and not any(item.get("name") == query_tool for item in tools):
        return {"preflight_rejected": True, "preflight_error": "missing_query_tool",
                "server_name": server_name, "tool": tool_name, "query_tool": query_tool,
                "tool_sent": False}
    schema = tool.get("inputSchema")
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return {"preflight_rejected": True, "preflight_error": "invalid_tool_schema",
                "server_name": server_name, "tool": tool_name, "tool_sent": False}
    schema_sha256 = hashlib.sha256(json.dumps(schema, ensure_ascii=False, sort_keys=True,
                                              separators=(",", ":")).encode("utf-8")).hexdigest()
    try:
        import jsonschema
        jsonschema.Draft202012Validator.check_schema(schema)
        errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(arguments),
                        key=lambda error: repr(list(error.path)))
    except ImportError as exc:
        raise RuntimeError("MCP runtime is missing jsonschema for preflight validation") from exc
    except jsonschema.SchemaError:
        return {"preflight_rejected": True, "preflight_error": "invalid_tool_schema",
                "server_name": server_name, "tool": tool_name,
                "tool_schema_sha256": schema_sha256, "tool_sent": False}
    if errors:
        return {"preflight_rejected": True, "preflight_error": "invalid_arguments",
                "validation_error": errors[0].message[:500], "server_name": server_name,
                "tool": tool_name, "tool_schema_sha256": schema_sha256, "tool_sent": False}
    return {"preflight_rejected": False, "server_name": server_name, "tool": tool_name,
            "tool_schema_sha256": schema_sha256, "tool_sent": False}

async def invoke(args):
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    _validate_url(args.url)
    headers = {"Accept": "application/json, text/event-stream"}
    if token := os.environ.get(args.token_env):
        headers["Authorization"] = "Bearer " + token
    async with httpx.AsyncClient(headers=headers, timeout=args.timeout, trust_env=False) as client:
        async with streamable_http_client(args.url, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                initialize_dump = initialized.model_dump(mode="json", exclude_none=True)
                server_name = initialize_dump.get("serverInfo", {}).get("name")
                result = {"initialize": initialize_dump, "server_name": server_name}
                listed = await session.list_tools()
                tools = list(listed.tools)
                cursor = listed.nextCursor
                while cursor:
                    listed = await session.list_tools(cursor=cursor)
                    tools.extend(listed.tools)
                    cursor = listed.nextCursor
                tools_dump = [tool.model_dump(mode="json", exclude_none=True) for tool in tools]
                if args.action == "discover":
                    result["tools"] = tools_dump
                else:
                    data = _call_data(args)
                    query_tool = None
                    if getattr(args, "_binding", None) and args._binding["capabilities"][args.capability].get("async"):
                        query_tool = args._binding["capabilities"][args.capability]["query_tool"]
                    preflight = _preflight(server_name=server_name, expected_server=args.expected_server,
                                           tools=tools_dump, tool_name=args.tool, arguments=data,
                                           query_tool=query_tool)
                    result.update(preflight)
                    if preflight["preflight_rejected"]:
                        return result
                    response = await session.call_tool(args.tool, data,
                                                       read_timeout_seconds=timedelta(seconds=args.timeout))
                    result.update(tool=args.tool, result=response.model_dump(mode="json", exclude_none=True))
                    result["tool_sent"] = True
                return result


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--token-env", default="EDS_MCP_TOKEN")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--output", required=True)
    parser.add_argument("--study-root", type=Path, default=None)
    parser.add_argument("--experiment-ref", default=None)
    parser.add_argument("--input-ref", action="append", default=[])
    parser.add_argument("--expected-server", default=None)
    parser.add_argument("--binding", dest="binding_path", type=Path, default=None)
    parser.add_argument("--capability", default=None)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("discover")
    call = actions.add_parser("call")
    call.add_argument("tool")
    call.add_argument("--data", required=True)
    args = parser.parse_args()
    if bool(args.study_root) != bool(args.experiment_ref):
        parser.error("--study-root and --experiment-ref must be provided together")
    if bool(args.binding_path) != bool(args.capability):
        parser.error("--binding and --capability must be provided together")
    if args.binding_path and args.action != "call":
        parser.error("--binding and --capability are only valid for call")
    path = Path(args.output)
    if path.exists():
        parser.error("output exists; preserve earlier evidence and choose a new path")
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    run_store = run = None
    protocol_acknowledged = False
    invoke_started = False
    result = None
    try:
        _validate_url(args.url)
        if args.binding_path:
            from eds.backends import BindingError, load_binding
            args._binding = load_binding(args.binding_path)
            cap = args._binding["capabilities"].get(args.capability)
            if cap is None:
                raise BindingError("required capability not available: " + args.capability)
            if cap["tool"] != args.tool:
                raise BindingError("binding capability tool does not match CLI tool")
            binding_server = args._binding.get("expected_server")
            if "expected_server" in args._binding and (not isinstance(binding_server, str) or not binding_server.strip()):
                raise BindingError("binding expected_server must be nonempty text")
            task_id_field = cap.get("task_id_field")
            if task_id_field and any(not segment for segment in task_id_field.split(".")):
                raise BindingError("binding task_id_field must contain nonempty dotted segments")
            if binding_server and args.expected_server and binding_server != args.expected_server:
                raise BindingError("explicit expected_server does not match binding expected_server")
            if not args.expected_server and binding_server:
                args.expected_server = binding_server
        if args.action == "call":
            args._data = _call_data(args)
            run_store, run = _prepare_run(args, args.tool, args._data, path)
        invoke_started = True
        result = asyncio.run(asyncio.wait_for(invoke(args), timeout=args.timeout + 30))
        protocol_acknowledged = True
        tool_error = result.get("result", {}).get("isError", False)
        operation_failed = _operation_failed(result)
        preflight_rejected = result.get("preflight_rejected", False)
        bound_async = bool(getattr(args, "_binding", None) and
                           args._binding["capabilities"][args.capability].get("async", False))
        task_ids = _task_ids(result, args._binding["capabilities"][args.capability]["task_id_field"]) if bound_async else []
        if tool_error or operation_failed or preflight_rejected:
            run_status, task_id = "failed", task_ids[0] if len(task_ids) == 1 else None
        elif bound_async and len(task_ids) == 1:
            run_status, task_id = "submitted", task_ids[0]
        elif bound_async:
            run_status, task_id = "unknown", None
        else:
            run_status, task_id = "completed", None
        if run_store is not None:
            run = run_store.transition_run(run["run_id"], run_status, task_id=task_id, output=result)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        summary = {"evidence": str(path.resolve()), "protocol_completed": True,
                   "tool_error": tool_error, "operation_failed": operation_failed,
                   "preflight_rejected": preflight_rejected,
                   "tool_sent": bool(result.get("tool_sent", False)),
                   "current_call_not_executed": True if preflight_rejected else False,
                   "invoke_started": invoke_started,
                   "preflight_outcome": ("rejected" if preflight_rejected else
                                         ("passed" if args.action == "call" else "not_applicable")),
                   "recording": "recorded" if run_store is not None else "unrecorded",
                   "run_status": run_status, "requires_query": run_status in {"submitted", "unknown"},
                   "engineering_success": "requires_assessment"}
        if task_id is not None:
            summary["task_id"] = task_id
        if run is not None:
            summary["run_id"] = run["run_id"]
        if "tools" in result:
            summary["tools"] = [tool["name"] for tool in result["tools"]]
        print(json.dumps(summary, ensure_ascii=False))
        return 2 if tool_error or operation_failed or preflight_rejected or run_status == "unknown" else 0
    except ExistingRunError as exc:
        existing = exc.run
        status = existing["status"]
        failure = {
            "protocol_completed": False,
            "error": type(exc).__name__,
            "message": str(exc),
            "retry": ("query actual state before resubmission" if
                       status in {"submitting", "submitted", "running", "unknown"} else
                       "use a new fixed state/input ref for a new occurrence"),
            "run_id": existing["run_id"], "existing_run_id": existing["run_id"],
            "run_status": status, "existing_status": status,
            "requires_query": status in {"submitting", "submitted", "running", "unknown"},
            "tool_sent": False, "current_call_not_executed": True,
            "invoke_started": False, "preflight_outcome": "not_started", "recording": "recorded",
        }
        print(json.dumps(failure, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as exc:
        message = str(exc)
        if secret := os.environ.get(args.token_env):
            message = message.replace(secret, "[redacted]")
        if run_store is not None and run is not None and run["status"] == "submitting":
            run = run_store.transition_run(run["run_id"], "unknown", output={"error": type(exc).__name__, "message": message[:500]})
        if result is not None:
            tool_sent = result.get("tool_sent", False)
            preflight_rejected = result.get("preflight_rejected", False)
            preflight_outcome = "rejected" if preflight_rejected else (
                "passed" if tool_sent is True else "unknown")
            current_call_not_executed = True if preflight_rejected else (
                False if tool_sent is True else None)
        elif invoke_started:
            tool_sent = None
            current_call_not_executed = None
            preflight_outcome = "unknown"
        else:
            tool_sent = False
            current_call_not_executed = True
            preflight_outcome = "not_started"
        failure = {"protocol_completed": protocol_acknowledged, "error": type(exc).__name__,
                   "message": message[:500], "retry": "query actual state before resubmission",
                   "tool_sent": tool_sent,
                   "current_call_not_executed": current_call_not_executed,
                   "invoke_started": invoke_started, "preflight_outcome": preflight_outcome,
                   "recording": "recorded" if run_store is not None else "unrecorded"}
        if message.startswith("MCP attempt limit exhausted"):
            failure["preflight_error"] = "mcp_attempt_limit"
            failure["current_call_not_executed"] = True
            failure["tool_sent"] = False
            failure["preflight_outcome"] = "rejected"
        if run is not None:
            failure["run_id"] = run["run_id"]
            if run["status"] != "submitting":
                if protocol_acknowledged:
                    failure["protocol_completed"] = True
                failure.update(run_status=run["status"],
                               requires_query=run["status"] in {"submitted", "unknown"})
                if run.get("task_id") is not None:
                    failure["task_id"] = run["task_id"]
        print(json.dumps(failure,
                         ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
