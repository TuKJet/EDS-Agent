"""Exercise three record paths using declared fixtures, never a CAD/CAE backend."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from eds.assets import check_assets, fingerprint
from eds.knowledge import KnowledgeBase
from eds.study import StudyStore


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def run_demo(root):
    root = Path(root).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("demo output must be a new or empty directory")
    root.mkdir(parents=True, exist_ok=True)
    results = {"provenance": "offline_synthetic_fixture", "real_mcp_calls": 0, "engineering_acceptance": "not_executed", "paths": {}}
    for mode in ("cad", "cae", "coupled"):
        directory = root / mode
        store = StudyStore.create(directory, "Verify records and continuity using synthetic fixture data", mode=mode,
                                  facts=["All observations in this demonstration are synthetic"],
                                  gaps=["No live CAD/CAE execution or physical validation"])
        asset = directory / "fixture-input.json"
        write_json(asset, {"synthetic": True, "length_mm": 100, "width_mm": 20, "thickness_mm": 10})
        original_asset = fingerprint(asset)
        store.update_context(assets=[original_asset])
        design = None
        if mode != "cae":
            design = store.add("design", {"purpose": "Fixture rectangular part", "asset": original_asset,
                                          "dimensions_mm": [100, 20, 10]}, ref="design")
        proposal = store.add("proposal", {"purpose": "Test a declared modelling expression",
                                             "assumptions": ["Fixture only"] if mode == "cad" else ["Fixture only", "Small deformation"],
                                             "refs": [design["ref"]] if design else [],
                                             "expression": "CAD prism" if mode == "cad" else "linear beam"}, ref="proposal")
        store.add("proposal", {"purpose": "Record a materially different example candidate",
                               "assumptions": ["Fixture only"],
                               "expression": "multi-feature CAD expression" if mode == "cad" else "shear-deformable beam"}, ref="alternative")
        realized = store.add("realization", {"proposal_ref": proposal["ref"],
                                              "observation": {"thickness_mm": 10, "source": "fixture"},
                                              "differences": []}, ref="realization")
        if mode == "coupled":
            store.add("mapping", {"refs": [design["ref"], realized["ref"]], "scale_mm_to_m": 0.001,
                                  "axes": "fixture shared XYZ", "valid_when": "input revisions unchanged",
                                  "boundary_mapping": "fixture clamped face to fixed support"}, ref="mapping")
        experiment = store.add("experiment", {"question": "Can a fixture run resume with its exact original input?",
                                                "refs": [realized["ref"]], "observations": ["input revision", "quantity with unit"],
                                                "decision_rule": "Preserve run identity and actual input under later changes"}, ref="experiment")
        run = store.add_run(experiment_ref=experiment["ref"], input_refs=[realized["ref"]], backend="offline-fixture",
                            capability="record-test", input_snapshot={"fixture": True, "thickness_mm": 10}, idempotency_key="fixture-1")
        store.transition_run(run["run_id"], "submitting")
        store.transition_run(run["run_id"], "submitted", task_id="fixture-job-1", output={"fixture": True, "accepted": True})
        store = StudyStore(directory)  # Fresh store reads persisted state, no in-memory chat dependency.
        resumed = store.resume()
        assert run["run_id"] in resumed["query_before_submit"]
        store.transition_run(run["run_id"], "unknown", output={"fixture": True, "reason": "simulated query interruption"})
        quantity = {"volume_mm3": 100 * 20 * 10} if mode == "cad" else {"analytical_tip_displacement_m": 10 * 0.1**3 / (3 * 2e11 * (0.02 * 0.01**3 / 12))}
        raw = {"fixture": True, "quantity": quantity, "actual_thickness_mm": 10, "physical_validation": "not_performed"}
        store.transition_run(run["run_id"], "completed", task_id="fixture-job-1", output=raw)
        raw_path = directory / "fixture-output.json"
        write_json(raw_path, raw)
        evidence = store.add("evidence", {"run_id": run["run_id"], "source": fingerprint(raw_path),
                                          "refs": [realized["ref"]], "observation": raw}, ref="evidence")
        assessment = store.add("assessment", {"evidence_refs": [evidence["ref"]],
                                               "interpretation": "Fixture proves record wiring only; no CAD/CAE capability claim",
                                               "next_action": "Obtain user VM/MCP and execute acceptance tasks",
                                               "applicability": "offline record demonstration"}, ref="assessment")
        write_json(asset, {"synthetic": True, "length_mm": 100, "width_mm": 20, "thickness_mm": 12})
        changes = check_assets([original_asset])
        assert changes["requires_impact_review"]
        if design:
            store.add("design", {"purpose": "Fixture manual change", "asset": fingerprint(asset), "dimensions_mm": [100, 20, 12]}, ref="design")
            impact = store.impact(design["ref"])
        else:
            store.add("proposal", {"purpose": "Fixture changed analysis input", "assumptions": ["Fixture only"],
                                   "actual_thickness_mm": 12}, ref="proposal")
            impact = store.impact(proposal["ref"])
        assert run["run_id"] in impact["old_results_require_review"]
        store.set_summary(next_step="Request live backend resources", stop_reason="Offline fixture finished; live validation pending",
                          artifacts=[str(raw_path)], conditions=["Synthetic records only"])
        store.update_context(gaps=["No live CAD/CAE execution or physical validation",
                                   "Actual backend capabilities and model readback"])
        store.set_metrics(elapsed_seconds=None, human_inputs=0, model_cost=None)
        write_json(directory / "report.json", store.render_report())
        write_json(directory / "impact.json", impact)
        results["paths"][mode] = {"study_id": store.read()["study_id"], "run_id": run["run_id"],
                                  "assessment": assessment["ref"], "manual_change_detected": True,
                                  "task_reconciled_from_fixture": True, "report": str(directory / "report.json")}
    knowledge_root = root / "knowledge"
    knowledge_root.mkdir()
    kb = KnowledgeBase(knowledge_root)
    for source in (Path(__file__).resolve().parent.parent / "examples/knowledge").glob("*.md"):
        if source.name == "README.md":
            continue
        target = knowledge_root / source.name
        shutil.copyfile(source, target)
    for target in knowledge_root.glob("*.md"):
        if "<!-- eds-knowledge:" in target.read_text(encoding="utf-8"):
            kb.register(target)
    results["knowledge"] = {"status": kb.status(), "english_matches": len(kb.search("pressure")),
                            "chinese_matches": len(kb.search("层流"))}
    write_json(root / "demo-report.json", results)
    return results


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    print(json.dumps(run_demo(arguments.output), ensure_ascii=False, indent=2))
