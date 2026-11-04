"""Explicit local asset fingerprints for takeover and manual-change detection."""
from __future__ import annotations

import hashlib
from pathlib import Path


def fingerprint(path):
    target = Path(path).resolve(strict=True)
    if not target.is_file():
        raise ValueError("asset must be a regular file")
    before = target.stat()
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = target.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("asset changed while fingerprinting; retry after the writer completes")
    return {"path": str(target), "sha256": digest.hexdigest(), "size_bytes": after.st_size,
            "modified_ns": after.st_mtime_ns, "observation": "local_file_fingerprint"}


def check_assets(snapshots):
    if not isinstance(snapshots, list):
        raise ValueError("asset snapshots must be an array")
    results = []
    for previous in snapshots:
        if not isinstance(previous, dict) or not previous.get("path") or not previous.get("sha256"):
            raise ValueError("each snapshot needs path and sha256")
        try:
            current = fingerprint(previous["path"])
            state = "unchanged" if current["sha256"] == previous["sha256"] else "changed"
            results.append({"status": state, "previous": previous, "current": current})
        except FileNotFoundError:
            results.append({"status": "missing", "previous": previous, "current": None})
    return {"assets": results, "requires_impact_review": any(row["status"] != "unchanged" for row in results)}
