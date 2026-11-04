"""Validate user-supplied MCP capability bindings without executing tools.

Codex owns MCP discovery and transport. These helpers only check the recorded
inventory and make explicit, bounded input/status translations.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path


class BindingError(ValueError):
    pass


REQUIRED = {
    "cad": {"inspect", "edit", "measure", "export"},
    "cae": {"inspect", "configure", "solve", "results"},
}
STATUSES = {"submitted", "running", "completed", "failed", "unknown", "cancelled"}


def load_binding(path):
    def reject_constant(value):
        raise BindingError(f"nonfinite JSON value: {value}")
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=reject_constant)
    validate_binding(data)
    return data


def validate_binding(data):
    try:
        json.dumps(data, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise BindingError("binding must contain only finite JSON values") from exc
    if not isinstance(data, dict) or data.get("schema") != "eds-backend/v1":
        raise BindingError("expected eds-backend/v1 object")
    for key in ("id", "codex_server"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise BindingError(f"{key} must be nonempty text")
    if data.get("domain") not in REQUIRED:
        raise BindingError("domain must be cad or cae")
    caps = data.get("capabilities")
    if not isinstance(caps, dict) or not caps:
        raise BindingError("capabilities must be a nonempty object")
    for name, cap in caps.items():
        if not isinstance(cap, dict) or not isinstance(cap.get("tool"), str) or not cap["tool"]:
            raise BindingError(f"{name}: missing concrete MCP tool name")
        if not isinstance(cap.get("description"), str) or not cap["description"]:
            raise BindingError(f"{name}: explain actual operation semantics")
        if not isinstance(cap.get("async", False), bool):
            raise BindingError(f"{name}: async must be boolean")
        if "read_only" in cap and not isinstance(cap["read_only"], bool):
            raise BindingError(f"{name}: read_only must be boolean")
        if cap.get("async", False) and not all(cap.get(k) for k in ("query_tool", "task_id_field")):
            raise BindingError(f"{name}: asynchronous capability needs query_tool and task_id_field")
        for key in ("query_tool", "task_id_field"):
            if key in cap and (not isinstance(cap[key], str) or not cap[key].strip()):
                raise BindingError(f"{name}: {key} must be nonempty text")
        fields = cap.get("inputs", {})
        if not isinstance(fields, dict):
            raise BindingError(f"{name}: inputs must be an object")
        targets = set()
        for field, spec in fields.items():
            if not isinstance(spec, dict):
                raise BindingError(f"{name}.{field}: input definition must be an object")
            target = spec.get("target", field)
            if not isinstance(target, str) or not target or target in targets:
                raise BindingError(f"{name}: input targets must be unique nonempty strings")
            targets.add(target)
            if spec.get("type", "any") not in {"any", "number", "string", "boolean", "object", "array"}:
                raise BindingError(f"{name}.{field}: unknown input type")
            if not isinstance(spec.get("required", True), bool):
                raise BindingError(f"{name}.{field}: required must be boolean")
            if "unit" in spec:
                if (spec.get("type") != "number" or not isinstance(spec["unit"], str) or not spec["unit"]
                        or not isinstance(spec.get("backend_unit"), str) or not spec["backend_unit"]):
                    raise BindingError(f"{name}.{field}: unit conversion needs numeric type and backend_unit")
                if spec["unit"] != spec["backend_unit"] and "scale" not in spec:
                    raise BindingError(f"{name}.{field}: unit conversion needs an explicit scale")
            for factor in ("scale", "offset", "minimum", "maximum"):
                if factor in spec and (type(spec[factor]) not in (int, float) or not math.isfinite(spec[factor])):
                    raise BindingError(f"{name}.{field}: {factor} must be finite")
                if factor in spec and spec.get("type") != "number":
                    raise BindingError(f"{name}.{field}: {factor} requires numeric type")
            if spec.get("scale") == 0:
                raise BindingError(f"{name}.{field}: scale must not be zero")
            if "minimum" in spec and "maximum" in spec and spec["minimum"] > spec["maximum"]:
                raise BindingError(f"{name}.{field}: minimum exceeds maximum")
        statuses = cap.get("status_map", {})
        if not isinstance(statuses, dict) or any(v not in STATUSES for v in statuses.values()):
            raise BindingError(f"{name}: invalid status_map")
    return data


def check_binding(binding, available_tools=None, *, required_capabilities=None):
    validate_binding(binding)
    if available_tools is not None and (not isinstance(available_tools, list) or
                                        any(not isinstance(tool, str) for tool in available_tools)):
        raise BindingError("tool inventory must be a JSON array of names")
    required = REQUIRED[binding["domain"]] if required_capabilities is None else set(required_capabilities)
    missing = sorted(required - set(binding["capabilities"]))
    tools = set(available_tools) if available_tools is not None else None
    absent = []
    if tools is not None:
        for cap in binding["capabilities"].values():
            for key in ("tool", "query_tool"):
                if cap.get(key) and cap[key] not in tools:
                    absent.append(cap[key])
    return {"backend": binding["id"], "domain": binding["domain"],
            "configuration_valid": True, "missing_capabilities": missing,
            "missing_tools": sorted(set(absent)),
            "discovery": "not_checked" if tools is None else "checked_against_supplied_inventory",
            "live_execution": "not_verified", "fixture": bool(binding.get("fixture", False)),
            "ready_for_binding_review": not missing and not absent}


def prepare_call(binding, capability, inputs):
    """Return a call description for Codex; never send a network request."""
    validate_binding(binding)
    cap = binding["capabilities"].get(capability)
    if cap is None:
        raise BindingError(f"required capability not available: {capability}")
    if not isinstance(inputs, dict):
        raise BindingError("inputs must be an object")
    specs = cap.get("inputs", {})
    unknown = set(inputs) - set(specs)
    if unknown:
        raise BindingError(f"unmapped inputs: {', '.join(sorted(unknown))}; extend the binding from actual tool schema")
    arguments, conversions = {}, []
    for field, spec in specs.items():
        if field not in inputs:
            if spec.get("required", True):
                raise BindingError(f"missing input: {field}")
            continue
        value = inputs[field]
        if "unit" in spec:
            if not isinstance(value, dict) or value.get("unit") != spec["unit"] or "value" not in value:
                raise BindingError(f"{field}: expected {{value, unit: {spec['unit']}}}")
            value = value["value"]
        expected = spec.get("type", "any")
        types = {"number": (int, float), "string": (str,), "boolean": (bool,), "object": (dict,), "array": (list,)}
        if expected != "any" and type(value) not in types[expected]:
            raise BindingError(f"{field}: expected {expected}")
        if expected == "number":
            if not math.isfinite(value):
                raise BindingError(f"{field}: nonfinite number")
            if (("minimum" in spec and value < spec["minimum"])
                    or ("maximum" in spec and value > spec["maximum"])):
                raise BindingError(f"{field}: value outside declared range")
            original = value
            value = value * spec.get("scale", 1) + spec.get("offset", 0)
            if not math.isfinite(value):
                raise BindingError(f"{field}: conversion overflow")
            if "unit" in spec:
                conversions.append({"field": field, "input": original, "unit": spec["unit"],
                                    "output": value, "backend_unit": spec["backend_unit"]})
        arguments[spec.get("target", field)] = copy.deepcopy(value)
    # Strict JSON rejects NaN hidden within object inputs too.
    json.dumps(arguments, allow_nan=False)
    return {"backend": binding["id"], "server": binding["codex_server"], "capability": capability,
            "tool": cap["tool"], "arguments": arguments, "input_snapshot": copy.deepcopy(inputs),
            "conversions": conversions, "async": cap.get("async", False),
            "query_tool": cap.get("query_tool"), "task_id_field": cap.get("task_id_field"),
            "status": "prepared_not_executed"}


def normalize_status(binding, capability, raw_status):
    validate_binding(binding)
    cap = binding["capabilities"].get(capability)
    if cap is None:
        raise BindingError(f"required capability not available: {capability}")
    mapped = cap.get("status_map", {}).get(str(raw_status), "unknown")
    return {"status": mapped, "raw_status": raw_status, "needs_query": mapped == "unknown"}
