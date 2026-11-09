# Runtime execution route

## Activity preset handoff

The caller may provide a pinned activity task snapshot with a drawing request.
Consume its effective values directly; do not perform a fresh preference or
n-gram search for each part. Apply only fields supported by the selected
`DrawingSpec`, and return `applied_style_fields`, `unmapped_style_fields` and
`overridden_style_fields` in the execution evidence. The snapshot identifies
the profile revision and source preference versions so a multi-part batch stays
consistent. A task override is local to that snapshot and is not a default.

Read this index after a local binding has been found and the selected MCP is
expected to be usable. It is deliberately a routing sheet, not a copy of a
vendor manual.

Paths below are relative to the repository root. Locate a heading or capability
row before reading its body; do not read every linked file as a checklist.

| Selected task | Upstream entry to read |
| --- | --- |
| SolidWorks operation routing | Matching row under `## 核心工作流` in `execution-skills/solidworks-automation-skill/SKILL.md`, and matching entries in `capabilities.yaml` in that submodule |
| Part modeling | `execution-skills/solidworks-automation-skill/references/part-modeling.md`, only the requested operation |
| Drawing / 3D-to-2D / drawing BOM and review | First read `execution-skills/solidworks-automation-skill/subskills/solidworks-engineering-drawing/SKILL.md`, especially its capability boundaries. Follow its DrawingSpec schema; use `references/drawing.md` in the root submodule only for the required API detail. |
| Standalone BOM CSV or file delivery | Relevant section of `execution-skills/solidworks-automation-skill/references/export.md`; a BOM placed on a drawing uses the engineering-drawing subskill above. |
| Geometry/result review | Relevant checks in `execution-skills/solidworks-automation-skill/references/review.md` and root Skill `## 结果自审查` |
| COMSOL tool | Matching tool under `## MCP Tools` in `execution-skills/cae-agent-hub/MCP/COMSOL/README.md`, then the target tool's discovered schema; read implementation detail only for a specific ambiguity |

For other tasks, find the appropriate upstream capability row rather than choosing
an unrelated recipe. Schema discovery does not require reading the whole tool list
into the Study owner's context. Keep the existing endpoint's selected COMSOL mode;
do not switch to the Java bridge or another backend just because its guide exists.

For engineering drawings, check the task subskill's supported options before
selecting the generic generator. Section/detail views, specifically identified
dimensions, hole tables and other specialized options can require a different
upstream script; a syntactically valid schema is not evidence that the generic
MCP generator supports them. Keep the limitation visible before document mutation.

## Remote MCP already available

- Read only the selected upstream Skill sections for the requested operation,
  its capability row and the task-specific reference. Do not read the complete
  root Skill or its installation guide.
- For a remote SolidWorks MCP, local COM/Python self-checks in the upstream
  Skill apply only when the executor is actually running the vendor script on
  that same machine. They are not prerequisites for a Codex caller using an
  already-running VM service.
- For CAE Agent Hub, read only the current MCP tool section and input schema in
  the registered COMSOL documentation. Do not load the README's installation,
  Java build or full tool catalogue sections for a normal call.
- Before mutation, verify service identity, target tool name and current schema.
  Preserve the selected model/document identity, unsaved-document state, actual
  file path and returned artifact/hash evidence as applicable.
- Record the pinned source commit and the relevant reference path, but return
  only the requested status, actual-state differences, QoI and evidence paths to
  the Study owner.

If the target tool cannot be discovered or the schema does not match, stop the
runtime route and switch to the matching branch in `execution-setup.md`.
